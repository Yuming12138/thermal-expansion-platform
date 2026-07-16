from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from te_platform.composites.curve_rom import (
    analyze_fraction_robustness,
    mix_curve,
    normalize_target_curve_points,
    optimize_curve_model,
    resolve_target_alpha_curve,
)
from te_platform.db.schema import connect_readonly_database


def _release_materials_with_curves(
    database: str | Path,
    release_slug: str,
    *,
    query: str = "",
    limit: int = 30,
    alpha_sign: int | None = None,
) -> list[dict[str, Any]]:
    if not 1 <= limit <= 100:
        raise ValueError("limit must be between 1 and 100")
    pattern = f"%{query.strip()}%"
    with connect_readonly_database(database) as connection:
        rows = connection.execute(
            """WITH ranked_curves AS (
                SELECT j.material_id, c.points_json,
                       ROW_NUMBER() OVER (
                           PARTITION BY j.material_id
                           ORDER BY j.updated_at DESC, j.id DESC
                       ) AS curve_rank
                FROM calculation_jobs j
                JOIN precision_thermal_expansion_curves c ON c.job_id = j.id
                WHERE j.status = 'SUCCEEDED'
            )
            SELECT m.material_key, m.formula, rc.points_json
            FROM dataset_releases dr
            JOIN dataset_memberships dm ON dm.dataset_release_id = dr.id
            JOIN materials m ON m.id = dm.material_id
            JOIN ranked_curves rc ON rc.material_id = m.id AND rc.curve_rank = 1
            WHERE dr.slug = ?
              AND (? = '%%' OR m.material_key LIKE ? OR m.formula LIKE ?)
            ORDER BY m.material_key""",
            (release_slug, pattern, pattern, pattern),
        ).fetchall()
        output: list[dict[str, Any]] = []
        for row in rows:
            points = json.loads(row["points_json"])
            alpha_300 = _interpolate(points, 300.0)
            if alpha_300 is None or (alpha_sign is not None and alpha_sign * alpha_300 <= 0):
                continue
            output.append(
                {
                    "material_key": row["material_key"],
                    "formula": row["formula"],
                    "alpha_300k_ppm_per_k": alpha_300 * 1_000_000 if alpha_300 is not None else None,
                    "temperature_min_k": float(points[0][0]),
                    "temperature_max_k": float(points[-1][0]),
                    "point_count": len(points),
                }
            )
            if len(output) == limit:
                break
    return output


def curve_materials(
    database: str | Path,
    release_slug: str,
    query: str = "",
    limit: int = 30,
    *,
    alpha_sign: int | None = None,
) -> list[dict[str, Any]]:
    return _release_materials_with_curves(
        database, release_slug, query=query, limit=limit, alpha_sign=alpha_sign
    )


def query_thermal_expansion_catalog(
    database: str | Path,
    release_slugs: str | tuple[str, ...],
    *,
    temperature_k: float = 300.0,
    query: str = "",
    alpha_min_ppm_per_k: float | None = None,
    alpha_max_ppm_per_k: float | None = None,
    sort_order: str = "ascending",
    limit: int = 20,
) -> dict[str, Any]:
    """Evaluate stored curves at one temperature, then filter and rank the full scope."""
    if temperature_k < 0:
        raise ValueError("temperature_k must be non-negative")
    if sort_order not in {"ascending", "descending"}:
        raise ValueError("sort_order must be 'ascending' or 'descending'")
    if not 1 <= limit <= 100:
        raise ValueError("limit must be between 1 and 100")
    slugs = (release_slugs,) if isinstance(release_slugs, str) else release_slugs
    if not slugs:
        raise ValueError("At least one release slug is required")
    placeholders = ",".join("?" for _ in slugs)
    pattern = f"%{query.strip()}%"
    with connect_readonly_database(database) as connection:
        membership_count = connection.execute(
            f"""SELECT COUNT(*)
            FROM dataset_releases dr
            JOIN dataset_memberships dm ON dm.dataset_release_id = dr.id
            WHERE dr.slug IN ({placeholders})""",
            slugs,
        ).fetchone()[0]
        rows = connection.execute(
            f"""WITH ranked_curves AS (
                SELECT j.material_id, c.points_json, c.source_path,
                       ROW_NUMBER() OVER (
                           PARTITION BY j.material_id
                           ORDER BY j.updated_at DESC, j.id DESC
                       ) AS curve_rank
                FROM calculation_jobs j
                JOIN precision_thermal_expansion_curves c ON c.job_id = j.id
                WHERE j.status = 'SUCCEEDED'
            )
            SELECT dr.slug AS release_slug, m.material_key, m.formula,
                   rc.points_json, rc.source_path
            FROM dataset_releases dr
            JOIN dataset_memberships dm ON dm.dataset_release_id = dr.id
            JOIN materials m ON m.id = dm.material_id
            JOIN ranked_curves rc ON rc.material_id = m.id AND rc.curve_rank = 1
            WHERE dr.slug IN ({placeholders})
              AND (? = '%%' OR m.material_key LIKE ? OR m.formula LIKE ?)
            ORDER BY m.material_key""",
            (*slugs, pattern, pattern, pattern),
        ).fetchall()

    evaluated: list[dict[str, Any]] = []
    outside_curve_range = 0
    invalid_curves = 0
    for row in rows:
        try:
            points = json.loads(row["points_json"])
            alpha = _interpolate(points, temperature_k)
        except (json.JSONDecodeError, IndexError, TypeError, ValueError, ZeroDivisionError):
            invalid_curves += 1
            continue
        if alpha is None:
            outside_curve_range += 1
            continue
        alpha_ppm = alpha * 1_000_000
        if not math.isfinite(alpha_ppm):
            invalid_curves += 1
            continue
        if alpha_min_ppm_per_k is not None and alpha_ppm < alpha_min_ppm_per_k:
            continue
        if alpha_max_ppm_per_k is not None and alpha_ppm > alpha_max_ppm_per_k:
            continue
        evaluated.append(
            {
                "release_slug": row["release_slug"],
                "material_key": row["material_key"],
                "formula": row["formula"],
                "temperature_k": float(temperature_k),
                "alpha_ppm_per_k": alpha_ppm,
                "curve_temperature_min_k": float(points[0][0]),
                "curve_temperature_max_k": float(points[-1][0]),
                "curve_point_count": len(points),
                "source_path": row["source_path"],
            }
        )
    evaluated.sort(
        key=lambda item: (item["alpha_ppm_per_k"], item["material_key"]),
        reverse=sort_order == "descending",
    )
    results = evaluated[:limit]
    for rank, item in enumerate(results, start=1):
        item["rank"] = rank
    return {
        "temperature_k": float(temperature_k),
        "sort_order": sort_order,
        "query": query,
        "release_slugs": list(slugs),
        "scope_material_count": int(membership_count),
        "stored_curve_count": len(rows),
        "evaluated_material_count": len(evaluated),
        "outside_curve_range_count": outside_curve_range,
        "invalid_curve_count": invalid_curves,
        "returned_count": len(results),
        "ranking_is_complete_for_evaluated_scope": True,
        "results": results,
    }


def _interpolate(points: list[list[float]], target: float) -> float | None:
    if target < points[0][0] or target > points[-1][0]:
        return None
    for left, right in zip(points, points[1:]):
        left_t, left_alpha = float(left[0]), float(left[1])
        right_t, right_alpha = float(right[0]), float(right[1])
        if left_t <= target <= right_t:
            if target == left_t:
                return left_alpha
            return left_alpha + (target - left_t) / (right_t - left_t) * (right_alpha - left_alpha)
    return float(points[-1][1]) if target == points[-1][0] else None


def _material_curve(
    database: str | Path, release_slug: str, material_key: str
) -> dict[str, Any]:
    with connect_readonly_database(database) as connection:
        row = connection.execute(
            """SELECT m.id, m.material_key, m.formula, dr.id AS dataset_release_id
            FROM dataset_releases dr
            JOIN dataset_memberships dm ON dm.dataset_release_id = dr.id
            JOIN materials m ON m.id = dm.material_id
            WHERE dr.slug = ? AND m.material_key = ?""",
            (release_slug, material_key),
        ).fetchone()
        if row is None:
            raise ValueError(f"Material is not present in {release_slug}: {material_key}")
        curve = connection.execute(
            """SELECT c.points_json, c.source_path, j.id AS job_id
            FROM calculation_jobs j
            JOIN precision_thermal_expansion_curves c ON c.job_id = j.id
            WHERE j.material_id = ? AND j.status = 'SUCCEEDED'
            ORDER BY j.updated_at DESC LIMIT 1""",
            (row["id"],),
        ).fetchone()
        bulk_modulus = connection.execute(
            """SELECT numeric_value
            FROM material_properties
            WHERE dataset_release_id = ? AND material_id = ? AND name = 'K_GPa'""",
            (row["dataset_release_id"], row["id"]),
        ).fetchone()
        shear_modulus = connection.execute(
            """SELECT numeric_value
            FROM material_properties
            WHERE dataset_release_id = ? AND material_id = ? AND name = 'G_GPa'""",
            (row["dataset_release_id"], row["id"]),
        ).fetchone()
        structure = connection.execute(
            """SELECT format, content
            FROM structures
            WHERE dataset_release_id = ? AND material_id = ?
            ORDER BY CASE WHEN UPPER(format) = 'POSCAR' THEN 0 ELSE 1 END, id
            LIMIT 1""",
            (row["dataset_release_id"], row["id"]),
        ).fetchone()
    if curve is None:
        raise ValueError(f"Material has no stored thermal-expansion curve: {material_key}")
    density = None
    density_warning = None
    if structure is not None:
        try:
            from pymatgen.core import Structure

            structure_format = str(structure["format"] or "").lower()
            parser_format = "poscar" if structure_format in {"poscar", "vasp"} else structure_format
            density = float(Structure.from_str(structure["content"], fmt=parser_format).density)
        except (AttributeError, IndexError, KeyError, TypeError, ValueError) as error:
            density_warning = f"无法从结构计算密度：{error}"
    else:
        density_warning = "没有可用于质量分数换算的结构文件"
    return {
        "material_id": row["id"],
        "material_key": row["material_key"],
        "formula": row["formula"],
        "points": json.loads(curve["points_json"]),
        "source_path": curve["source_path"],
        "job_id": curve["job_id"],
        "bulk_modulus_gpa": (
            float(bulk_modulus["numeric_value"])
            if bulk_modulus is not None and bulk_modulus["numeric_value"] is not None
            else None
        ),
        "shear_modulus_gpa": (
            float(shear_modulus["numeric_value"])
            if shear_modulus is not None and shear_modulus["numeric_value"] is not None
            else None
        ),
        "density_g_cm3": density,
        "density_warning": density_warning,
    }


def _uniform_temperatures(start: float, end: float, step: float) -> list[float]:
    if step <= 0:
        raise ValueError("temperature_step_k must be positive")
    temperatures = [start]
    current = start + step
    while current < end - 1e-9:
        temperatures.append(current)
        current += step
    if end > start:
        temperatures.append(end)
    return temperatures


def optimize_material_pair(
    database: str | Path,
    *,
    pte_release_slug: str,
    nte_release_slug: str,
    pte_material_key: str,
    nte_material_key: str,
    temperature_min_k: float,
    temperature_max_k: float,
    target_alpha_ppm_per_k: float = 0.0,
    target_curve_points: list[dict[str, float]] | list[tuple[float, float]] | None = None,
    model: str = "linear_rom",
    matrix_phase: str = "pte",
    temperature_step_k: float = 10.0,
    zte_tolerance_ppm_per_k: float = 5.0,
    minimum_target_coverage_fraction: float = 0.9,
    robustness_fraction_step: float = 0.005,
    formulation_total_mass_g: float = 10.0,
    balance_resolution_g: float = 0.001,
) -> dict[str, Any]:
    if temperature_max_k <= temperature_min_k:
        raise ValueError("temperature_max_k must be greater than temperature_min_k")
    pte = _material_curve(database, pte_release_slug, pte_material_key)
    nte = _material_curve(database, nte_release_slug, nte_material_key)
    overlap_min = max(float(pte["points"][0][0]), float(nte["points"][0][0]), temperature_min_k)
    overlap_max = min(float(pte["points"][-1][0]), float(nte["points"][-1][0]), temperature_max_k)
    if overlap_max <= overlap_min:
        raise ValueError("Selected materials have no overlapping curve points in the requested temperature range")
    optimization_temperatures = _uniform_temperatures(
        overlap_min,
        overlap_max,
        temperature_step_k,
    )
    if len(optimization_temperatures) < 2:
        raise ValueError("At least two common temperature samples are required")
    optimization_pte_alpha = [
        _interpolate(pte["points"], temperature) * 1_000_000
        for temperature in optimization_temperatures
    ]
    optimization_nte_alpha = [
        _interpolate(nte["points"], temperature) * 1_000_000
        for temperature in optimization_temperatures
    ]
    normalized_target_points = normalize_target_curve_points(target_curve_points)
    optimization_target_alpha = resolve_target_alpha_curve(
        optimization_temperatures,
        target_alpha_ppm_per_k,
        normalized_target_points,
    )
    curve_min = max(float(pte["points"][0][0]), float(nte["points"][0][0]))
    curve_max = min(float(pte["points"][-1][0]), float(nte["points"][-1][0]))
    temperatures = sorted(
        {
            float(point[0])
            for curve in (pte["points"], nte["points"])
            for point in curve
            if curve_min <= float(point[0]) <= curve_max
        }
        | set(optimization_temperatures)
        | {curve_min, curve_max}
    )
    pte_alpha = [_interpolate(pte["points"], temperature) * 1_000_000 for temperature in temperatures]
    nte_alpha = [_interpolate(nte["points"], temperature) * 1_000_000 for temperature in temperatures]
    model_results: dict[str, dict[str, Any]] = {}
    warnings = [
        warning
        for warning in (pte.get("density_warning"), nte.get("density_warning"))
        if warning
    ]
    for model_name in ("linear_rom", "turner", "kerner"):
        try:
            result = optimize_curve_model(
                optimization_pte_alpha,
                optimization_nte_alpha,
                target_alpha_ppm_per_k,
                model=model_name,
                temperatures_k=optimization_temperatures,
                pte_density=pte.get("density_g_cm3"),
                nte_density=nte.get("density_g_cm3"),
                pte_bulk_modulus_gpa=pte.get("bulk_modulus_gpa"),
                nte_bulk_modulus_gpa=nte.get("bulk_modulus_gpa"),
                pte_shear_modulus_gpa=pte.get("shear_modulus_gpa"),
                nte_shear_modulus_gpa=nte.get("shear_modulus_gpa"),
                matrix_phase=matrix_phase,
                zte_tolerance_ppm_per_k=zte_tolerance_ppm_per_k,
                target_alpha_curve=optimization_target_alpha,
            )
        except ValueError as error:
            if model_name == model:
                raise
            warnings.append(f"{model_name}不可用：{error}")
            continue
        result_data = result.to_dict()
        result_data["optimization_temperatures_k"] = optimization_temperatures
        result_data["optimization_pte_alpha_ppm_per_k"] = optimization_pte_alpha
        result_data["optimization_nte_alpha_ppm_per_k"] = optimization_nte_alpha
        result_data["optimization_mixed_alpha_ppm_per_k"] = result_data.pop(
            "mixed_alpha_ppm_per_k"
        )
        result_data["mixed_alpha_ppm_per_k"] = list(
            mix_curve(
                pte_alpha,
                nte_alpha,
                result.nte_volume_fraction,
                model=model_name,
                pte_bulk_modulus_gpa=pte.get("bulk_modulus_gpa"),
                nte_bulk_modulus_gpa=nte.get("bulk_modulus_gpa"),
                pte_shear_modulus_gpa=pte.get("shear_modulus_gpa"),
                nte_shear_modulus_gpa=nte.get("shear_modulus_gpa"),
                matrix_phase=matrix_phase,
            )
        )
        result_data["robustness_analysis"] = analyze_fraction_robustness(
            optimization_pte_alpha,
            optimization_nte_alpha,
            optimal_nte_volume_fraction=result.nte_volume_fraction,
            target_alpha_curve=optimization_target_alpha,
            temperatures_k=optimization_temperatures,
            model=model_name,
            pte_density=pte.get("density_g_cm3"),
            nte_density=nte.get("density_g_cm3"),
            pte_bulk_modulus_gpa=pte.get("bulk_modulus_gpa"),
            nte_bulk_modulus_gpa=nte.get("bulk_modulus_gpa"),
            pte_shear_modulus_gpa=pte.get("shear_modulus_gpa"),
            nte_shear_modulus_gpa=nte.get("shear_modulus_gpa"),
            matrix_phase=matrix_phase,
            target_tolerance_ppm_per_k=zte_tolerance_ppm_per_k,
            minimum_target_coverage_fraction=minimum_target_coverage_fraction,
            fraction_step=robustness_fraction_step,
            formulation_total_mass_g=formulation_total_mass_g,
            balance_resolution_g=balance_resolution_g,
        )
        model_results[model_name] = result_data
    if model not in model_results:
        raise ValueError(f"Requested model is unavailable: {model}")
    selected_result = model_results[model]
    if model == "kerner":
        matrix_fraction = (
            1.0 - float(selected_result["nte_volume_fraction"])
            if matrix_phase == "pte"
            else float(selected_result["nte_volume_fraction"])
        )
        if matrix_fraction < 0.5:
            warnings.append(
                f"Kerner所选{matrix_phase.upper()}连续基体仅占{matrix_fraction * 100:.2f}%；"
                "少数相未必能形成连续基体，该结果应视为数学外推。"
            )
    return {
        "pte_material": {
            key: pte[key]
            for key in (
                "material_key",
                "formula",
                "job_id",
                "source_path",
                "bulk_modulus_gpa",
                "shear_modulus_gpa",
                "density_g_cm3",
            )
        },
        "nte_material": {
            key: nte[key]
            for key in (
                "material_key",
                "formula",
                "job_id",
                "source_path",
                "bulk_modulus_gpa",
                "shear_modulus_gpa",
                "density_g_cm3",
            )
        },
        "selected_model": model,
        "matrix_phase": matrix_phase if model == "kerner" else None,
        "model_results": model_results,
        "quality_warnings": warnings,
        "temperature_min_k": overlap_min,
        "temperature_max_k": overlap_max,
        "temperature_step_k": float(temperature_step_k),
        "curve_temperature_min_k": curve_min,
        "curve_temperature_max_k": curve_max,
        "temperatures_k": temperatures,
        "pte_alpha_ppm_per_k": pte_alpha,
        "nte_alpha_ppm_per_k": nte_alpha,
        "target_alpha_ppm_per_k": target_alpha_ppm_per_k,
        "target_curve_points": [
            {"temperature_k": temperature, "alpha_ppm_per_k": alpha}
            for temperature, alpha in normalized_target_points
        ],
        "target_temperatures_k": optimization_temperatures,
        "target_alpha_curve_ppm_per_k": list(optimization_target_alpha),
        "minimum_target_coverage_fraction": minimum_target_coverage_fraction,
        "robustness_fraction_step": robustness_fraction_step,
        "formulation_total_mass_g": formulation_total_mass_g,
        "balance_resolution_g": balance_resolution_g,
        **selected_result,
    }
