from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from te_platform.composites.curve_rom import optimize_curve_rom
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
            """SELECT m.id, m.material_key, m.formula
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
    if curve is None:
        raise ValueError(f"Material has no stored thermal-expansion curve: {material_key}")
    return {
        "material_id": row["id"],
        "material_key": row["material_key"],
        "formula": row["formula"],
        "points": json.loads(curve["points_json"]),
        "source_path": curve["source_path"],
        "job_id": curve["job_id"],
    }


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
) -> dict[str, Any]:
    if temperature_max_k <= temperature_min_k:
        raise ValueError("temperature_max_k must be greater than temperature_min_k")
    pte = _material_curve(database, pte_release_slug, pte_material_key)
    nte = _material_curve(database, nte_release_slug, nte_material_key)
    overlap_min = max(float(pte["points"][0][0]), float(nte["points"][0][0]), temperature_min_k)
    overlap_max = min(float(pte["points"][-1][0]), float(nte["points"][-1][0]), temperature_max_k)
    if overlap_max <= overlap_min:
        raise ValueError("Selected materials have no overlapping curve points in the requested temperature range")
    optimization_temperatures = sorted(
        {
            float(point[0])
            for curve in (pte["points"], nte["points"])
            for point in curve
            if overlap_min <= float(point[0]) <= overlap_max
        }
        | {overlap_min, overlap_max}
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
    result = optimize_curve_rom(
        optimization_pte_alpha, optimization_nte_alpha, target_alpha_ppm_per_k
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
        | {curve_min, curve_max}
    )
    pte_alpha = [_interpolate(pte["points"], temperature) * 1_000_000 for temperature in temperatures]
    nte_alpha = [_interpolate(nte["points"], temperature) * 1_000_000 for temperature in temperatures]
    mixed_alpha = [
        (1.0 - result.nte_volume_fraction) * pte_value
        + result.nte_volume_fraction * nte_value
        for pte_value, nte_value in zip(pte_alpha, nte_alpha)
    ]
    result_data = result.to_dict()
    result_data["mixed_alpha_ppm_per_k"] = mixed_alpha
    return {
        "pte_material": {key: pte[key] for key in ("material_key", "formula", "job_id", "source_path")},
        "nte_material": {key: nte[key] for key in ("material_key", "formula", "job_id", "source_path")},
        "temperature_min_k": overlap_min,
        "temperature_max_k": overlap_max,
        "curve_temperature_min_k": curve_min,
        "curve_temperature_max_k": curve_max,
        "temperatures_k": temperatures,
        "pte_alpha_ppm_per_k": pte_alpha,
        "nte_alpha_ppm_per_k": nte_alpha,
        "target_alpha_ppm_per_k": target_alpha_ppm_per_k,
        **result_data,
    }
