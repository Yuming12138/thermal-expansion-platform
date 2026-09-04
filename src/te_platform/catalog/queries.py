from __future__ import annotations

import json
import math
import re
from collections import Counter
from pathlib import Path
from typing import Any

from te_platform.db.schema import connect_readonly_database
from te_platform.screening.fast_sbr import calculate_bonding_modulus_from_atomic_volume


ELEMENT_SYMBOLS = frozenset(
    "H He Li Be B C N O F Ne Na Mg Al Si P S Cl Ar K Ca Sc Ti V Cr Mn Fe Co Ni Cu Zn "
    "Ga Ge As Se Br Kr Rb Sr Y Zr Nb Mo Tc Ru Rh Pd Ag Cd In Sn Sb Te I Xe Cs Ba La Ce "
    "Pr Nd Pm Sm Eu Gd Tb Dy Ho Er Tm Yb Lu Hf Ta W Re Os Ir Pt Au Hg Tl Pb Bi Po At Rn "
    "Fr Ra Ac Th Pa U Np Pu Am Cm Bk Cf Es Fm Md No Lr Rf Db Sg Bh Hs Mt Ds Rg Cn Nh Fl "
    "Mc Lv Ts Og".split()
)
ELEMENT_PATTERN = re.compile(r"[A-Z][a-z]?")

# Numeric catalog fields are normally stored in material_properties.numeric_value,
# but the AGV2 (tensor-aware) release writes them into text_value as decimal
# strings. Read both. The GLOB guard keeps JSON/text columns (component_summaries,
# motif_family_counts, ...) from being coerced to 0.0 by CAST(x AS REAL), which
# silently returns 0.0 for non-numeric input in SQLite.
_NUMERIC_PROPERTY_SQL = """
    CASE
        WHEN mp.numeric_value IS NOT NULL THEN mp.numeric_value
        WHEN mp.text_value IS NOT NULL
             AND (mp.text_value GLOB '[0-9]*'
                  OR mp.text_value GLOB '-[0-9]*'
                  OR mp.text_value GLOB '+[0-9]*'
                  OR mp.text_value GLOB '.[0-9]*')
        THEN CAST(mp.text_value AS REAL)
        ELSE NULL
    END
"""


def _numeric_property(name: str, alias: str | None = None) -> str:
    return (
        f"MAX(CASE WHEN mp.name = '{name}' THEN {_NUMERIC_PROPERTY_SQL} END)"
        f" AS {alias or name}"
    )


def _canonical_bonding_modulus(row: dict[str, Any]) -> tuple[float | None, str | None]:
    try:
        result = calculate_bonding_modulus_from_atomic_volume(
            float(row["E_coh_eV_per_atom"]),
            float(row["AAV"]),
            float(row["avg_cn"]),
        )
    except (KeyError, TypeError, ValueError):
        # AGV2 has no E_coh_eV_per_atom; it ships the bonding modulus E~ directly.
        return _stored_bonding_modulus(row)
    return result.bonding_modulus_gpa, "paper_definition_UV_over_n"


def _stored_bonding_modulus(row: dict[str, Any]) -> tuple[float | None, str | None]:
    for key in ("stored_E_tilde_GPa", "bond_modulus"):
        raw = row.get(key)
        if raw is None or isinstance(raw, bool):
            continue
        try:
            value = float(raw)
        except (TypeError, ValueError):
            continue
        if math.isfinite(value) and value > 0:
            return value, "catalog_bond_modulus_field"
    return None, None


def _canonicalize_material_row(row: Any) -> dict[str, Any]:
    result = dict(row)
    value, source = _canonical_bonding_modulus(result)
    result["E_tilde_GPa"] = value
    result["E_tilde_source"] = source
    try:
        shear_modulus = float(result["G_GPa"])
        result["xi"] = shear_modulus / value if value and value > 0 else None
    except (KeyError, TypeError, ValueError):
        result["xi"] = None
    result.pop("stored_E_tilde_GPa", None)
    return result


def formula_elements(formula: str | None) -> frozenset[str]:
    return frozenset(ELEMENT_PATTERN.findall(formula or ""))


def _selected_elements(elements: list[str] | tuple[str, ...] | None) -> frozenset[str]:
    selected = frozenset(str(element).strip() for element in elements or [] if str(element).strip())
    invalid = sorted(selected - ELEMENT_SYMBOLS)
    if invalid:
        raise ValueError(f"Unknown element symbols: {', '.join(invalid)}")
    return selected


def _precision_thermal_expansion(job: Any | None) -> dict[str, Any] | None:
    if job is None:
        return None
    result = json.loads(job["result_json"]) if job["result_json"] else {}
    curve = json.loads(job["points_json"]) if job["points_json"] else result.get("thermal_expansion_curve")
    if not isinstance(curve, list):
        return None
    points: list[dict[str, float]] = []
    for point in curve:
        if not isinstance(point, list | tuple) or len(point) < 2:
            continue
        try:
            temperature_k, alpha_per_k = float(point[0]), float(point[1])
        except (TypeError, ValueError):
            continue
        if math.isfinite(temperature_k) and math.isfinite(alpha_per_k):
            points.append(
                {
                    "temperature_k": temperature_k,
                    "alpha_ppm_per_k": alpha_per_k * 1_000_000,
                }
            )
    if len(points) < 2:
        return None
    return {
        "job_id": job["id"],
        "model_name": job["model_name"],
        "method": result.get("thermal_expansion_method") or job["model_name"],
        "updated_at": job["updated_at"],
        "points": points,
        "quality_warnings": result.get("quality_warnings", []),
        "source_path": job["source_path"] or result.get("thermal_expansion_source_path"),
    }


def _anisotropic_thermal_expansion(rows: list[Any]) -> dict[str, Any] | None:
    """Decode the published tensor-aware curves stored in the release catalog.

    ``points_json`` deliberately remains a JSON payload in SQLite so that the
    release is immutable and portable.  The API exposes a small, stable shape
    independent of the source file's on-disk location.
    """
    curves: dict[str, Any] = {}
    for row in rows:
        kind = str(row["curve_kind"])
        try:
            points = json.loads(row["points_json"])
            columns = json.loads(row["columns_json"])
            column_units = json.loads(row["column_units_json"])
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        if not isinstance(points, list) or len(points) < 2:
            continue
        normalized_points: list[dict[str, float]] = []
        for point in points:
            if not isinstance(point, dict):
                continue
            normalized: dict[str, float] = {}
            valid = True
            for key, value in point.items():
                try:
                    numeric = float(value)
                except (TypeError, ValueError):
                    valid = False
                    break
                if not math.isfinite(numeric):
                    valid = False
                    break
                normalized[str(key)] = numeric
            if valid and normalized:
                normalized_points.append(normalized)
        if len(normalized_points) < 2:
            continue
        curves[kind] = {
            "curve_kind": kind,
            "points": normalized_points,
            "columns": columns if isinstance(columns, list) else [],
            "column_units": column_units if isinstance(column_units, dict) else {},
            "unit": row["unit"],
            "method": row["method"],
            "source_path": row["source_path"],
            "source_sha256": row["source_sha256"],
            "temperature_min_k": float(row["temperature_min_k"]),
            "temperature_max_k": float(row["temperature_max_k"]),
            "point_count": int(row["point_count"]),
            "parsed_at": row["parsed_at"],
        }
    return curves or None


def dataset_summary(
    database_path: str | Path,
    release_slug: str,
) -> dict[str, Any]:
    with connect_readonly_database(database_path) as connection:
        release = connection.execute(
            """
            SELECT id, slug, title, version, record_count, source_file_name,
                   source_sha256, imported_at
            FROM dataset_releases
            WHERE slug = ?
            """,
            (release_slug,),
        ).fetchone()
        if release is None:
            raise ValueError(f"Dataset release is not imported: {release_slug}")
        counts = connection.execute(
            """
            SELECT
                COUNT(DISTINCT dm.material_id) AS materials,
                COUNT(DISTINCT s.id) AS structures,
                COUNT(DISTINCT mp.name) AS property_fields,
                COUNT(mp.name) AS property_values
            FROM dataset_memberships dm
            LEFT JOIN structures s
              ON s.dataset_release_id = dm.dataset_release_id
             AND s.material_id = dm.material_id
            LEFT JOIN material_properties mp
              ON mp.dataset_release_id = dm.dataset_release_id
             AND mp.material_id = dm.material_id
            WHERE dm.dataset_release_id = ?
            """,
            (release["id"],),
        ).fetchone()
        flags = connection.execute(
            """
            SELECT code, severity, COUNT(*) AS count
            FROM data_quality_flags
            WHERE dataset_release_id = ?
            GROUP BY code, severity
            ORDER BY severity, code
            """,
            (release["id"],),
        ).fetchall()
    return {
        "release": dict(release),
        "counts": dict(counts),
        "quality_flags": [dict(row) for row in flags],
    }


def search_materials(
    database_path: str | Path,
    release_slug: str,
    query: str = "",
    limit: int = 20,
    *,
    elements: list[str] | tuple[str, ...] | None = None,
    element_mode: str = "contains",
    sort_by: str = "material_key",
    sort_order: str = "ascending",
    cte_min_ppm: float | None = None,
    cte_max_ppm: float | None = None,
) -> list[dict[str, Any]]:
    if limit < 1 or limit > 500:
        raise ValueError("limit must be between 1 and 500")
    if element_mode not in {"contains", "exact"}:
        raise ValueError("element_mode must be 'contains' or 'exact'")
    if sort_by not in {"material_key", "G_GPa", "E_tilde_GPa", "CTE_ppm", "xi"}:
        raise ValueError("sort_by must be material_key, G_GPa, E_tilde_GPa, CTE_ppm, or xi")
    if sort_order not in {"ascending", "descending"}:
        raise ValueError("sort_order must be 'ascending' or 'descending'")
    if cte_min_ppm is not None and cte_max_ppm is not None and cte_min_ppm > cte_max_ppm:
        raise ValueError("cte_min_ppm cannot be greater than cte_max_ppm")
    selected = _selected_elements(elements)
    pattern = f"%{query.strip()}%"
    sort_expression = {
        "material_key": "material_key",
        "G_GPa": "G_GPa",
        "E_tilde_GPa": "canonical_E_tilde_GPa",
        "CTE_ppm": "CTE_ppm",
        "xi": "(G_GPa / canonical_E_tilde_GPa)",
    }[sort_by]
    sort_direction = "DESC" if sort_order == "descending" else "ASC"
    with connect_readonly_database(database_path) as connection:
        filtered_ids: list[int] | None = None
        if selected:
            candidates = connection.execute(
                """
                SELECT m.id, m.formula
                FROM dataset_releases dr
                JOIN dataset_memberships dm ON dm.dataset_release_id = dr.id
                JOIN materials m ON m.id = dm.material_id
                WHERE dr.slug = ?
                  AND (
                    ? = '%%'
                    OR m.material_key LIKE ?
                    OR m.formula LIKE ?
                    OR m.external_id LIKE ?
                  )
                """,
                (release_slug, pattern, pattern, pattern, pattern),
            ).fetchall()
            filtered_ids = [
                int(row["id"])
                for row in candidates
                if (
                    formula_elements(row["formula"]) == selected
                    if element_mode == "exact"
                    else selected <= formula_elements(row["formula"])
                )
            ]
            if not filtered_ids:
                return []
        material_filter = ""
        material_filter_values: tuple[int, ...] = ()
        if filtered_ids is not None:
            placeholders = ",".join("?" for _ in filtered_ids)
            material_filter = f"AND m.id IN ({placeholders})"
            material_filter_values = tuple(filtered_ids)
        rows = connection.execute(
            f"""WITH material_metrics AS (
                SELECT
                    m.material_key,
                    m.formula,
                    m.external_id,
                    {_numeric_property("K_GPa")},
                    {_numeric_property("G_GPa")},
                    {_numeric_property("E_tilde_GPa", "stored_E_tilde_GPa")},
                    {_numeric_property("E_coh_eV_per_atom")},
                    {_numeric_property("AAV")},
                    {_numeric_property("avg_cn")},
                    {_numeric_property("CTE_ppm")},
                    {_numeric_property("bond_modulus")},
                    {_numeric_property("xi", "stored_xi")}
                FROM dataset_releases dr
                JOIN dataset_memberships dm ON dm.dataset_release_id = dr.id
                JOIN materials m ON m.id = dm.material_id
                LEFT JOIN material_properties mp
                  ON mp.dataset_release_id = dr.id
                 AND mp.material_id = m.id
                WHERE dr.slug = ?
                  AND (
                    ? = '%%'
                    OR m.material_key LIKE ?
                    OR m.formula LIKE ?
                    OR m.external_id LIKE ?
                  )
                  {material_filter}
                GROUP BY m.id
            ), canonical_metrics AS (
                SELECT *,
                    CASE
                        WHEN E_coh_eV_per_atom IS NOT NULL AND AAV > 0 AND avg_cn > 0
                        THEN 160.21766208 * ABS(E_coh_eV_per_atom) / (AAV * avg_cn)
                    END AS canonical_E_tilde_GPa
                FROM material_metrics
            )
            SELECT material_key, formula, external_id, K_GPa, G_GPa,
                   stored_E_tilde_GPa, E_coh_eV_per_atom, AAV, avg_cn, CTE_ppm,
                   bond_modulus, stored_xi
            FROM canonical_metrics
            WHERE (? IS NULL OR CTE_ppm >= ?)
              AND (? IS NULL OR CTE_ppm <= ?)
            ORDER BY ({sort_expression}) IS NULL,
                     {sort_expression} {sort_direction},
                     material_key ASC
            LIMIT ?
            """,
            (
                release_slug,
                pattern,
                pattern,
                pattern,
                pattern,
                *material_filter_values,
                cte_min_ppm,
                cte_min_ppm,
                cte_max_ppm,
                cte_max_ppm,
                limit,
            ),
        ).fetchall()
    return [_canonicalize_material_row(row) for row in rows]


def material_element_statistics(
    database_path: str | Path,
    release_slug: str,
) -> dict[str, Any]:
    with connect_readonly_database(database_path) as connection:
        rows = connection.execute(
            """
            SELECT m.formula
            FROM dataset_releases dr
            JOIN dataset_memberships dm ON dm.dataset_release_id = dr.id
            JOIN materials m ON m.id = dm.material_id
            WHERE dr.slug = ?
            """,
            (release_slug,),
        ).fetchall()
    counts: Counter[str] = Counter()
    for row in rows:
        counts.update(formula_elements(row["formula"]))
    return {
        "material_count": len(rows),
        "elements": {element: counts.get(element, 0) for element in sorted(ELEMENT_SYMBOLS)},
    }


def material_detail(
    database_path: str | Path,
    release_slug: str,
    material_key: str,
) -> dict[str, Any]:
    with connect_readonly_database(database_path) as connection:
        material = connection.execute(
            """
            SELECT m.id, m.material_key, m.formula, m.external_id, dr.id AS release_id,
                   dr.slug AS release_slug, dr.title AS release_title,
                   dr.version AS release_version, dr.source_file_name,
                   dr.source_sha256, dr.imported_at
            FROM dataset_releases dr
            JOIN dataset_memberships dm ON dm.dataset_release_id = dr.id
            JOIN materials m ON m.id = dm.material_id
            WHERE dr.slug = ? AND m.material_key = ?
            """,
            (release_slug, material_key),
        ).fetchone()
        if material is None:
            raise ValueError(f"Material is not present in {release_slug}: {material_key}")
        properties = connection.execute(
            """
            SELECT name, numeric_value, text_value, unit
            FROM material_properties
            WHERE dataset_release_id = ? AND material_id = ?
            ORDER BY name
            """,
            (material["release_id"], material["id"]),
        ).fetchall()
        precision_job = connection.execute(
            """
            SELECT j.id, j.model_name, j.result_json, j.updated_at,
                   c.points_json, c.source_path
            FROM calculation_jobs j
            LEFT JOIN precision_thermal_expansion_curves c ON c.job_id = j.id
            WHERE j.material_id = ? AND j.status = 'SUCCEEDED'
              AND (c.points_json IS NOT NULL OR j.result_json IS NOT NULL)
            ORDER BY updated_at DESC
            LIMIT 1
            """,
            (material["id"],),
        ).fetchone()
        structures = connection.execute(
            """
            SELECT format, content, content_sha256, LENGTH(content) AS content_characters
            FROM structures
            WHERE dataset_release_id = ? AND material_id = ?
            -- A detail view needs a renderable crystallographic structure first.
            -- Elastic tensors are stored alongside POSCAR/CIF files, but are
            -- not structure documents and must never become the viewer input.
            ORDER BY CASE UPPER(format)
                       WHEN 'POSCAR' THEN 0
                       WHEN 'VASP' THEN 0
                       WHEN 'CIF' THEN 1
                       ELSE 2
                     END,
                     format
            """,
            (material["release_id"], material["id"]),
        ).fetchall()
        anisotropic_curves = connection.execute(
            """
            SELECT curve_kind, points_json, columns_json, column_units_json,
                   unit, method, source_path, source_sha256,
                   temperature_min_k, temperature_max_k, point_count, parsed_at
            FROM anisotropic_thermal_expansion_curves
            WHERE dataset_release_id = ? AND material_id = ?
            ORDER BY curve_kind
            """,
            (material["release_id"], material["id"]),
        ).fetchall()
        flags = connection.execute(
            """
            SELECT code, severity, message, observed_value_json
            FROM data_quality_flags
            WHERE dataset_release_id = ? AND material_id = ?
            ORDER BY severity, code
            """,
            (material["release_id"], material["id"]),
        ).fetchall()

    property_map = {
        row["name"]: {
            "value": row["numeric_value"]
            if row["numeric_value"] is not None
            else row["text_value"],
            "unit": row["unit"],
        }
        for row in properties
    }
    property_values = {
        name: value["value"] for name, value in property_map.items()
    }
    property_values["stored_E_tilde_GPa"] = property_values.get("E_tilde_GPa")
    bonding_modulus, bonding_source = _canonical_bonding_modulus(property_values)
    if bonding_modulus is not None:
        property_map["E_tilde_GPa"] = {
            "value": bonding_modulus,
            "unit": "GPa",
            "source": bonding_source,
            "formula": "160.21766208*abs(E_coh_eV_per_atom)/(AAV*avg_cn)",
        }
    shear_method_note = (
        "本NTE目录中的剪切模量字段主要来自论文高通量流程中的ALIGNN预测；"
        "不等同于对每个材料重新计算完整弹性张量。"
        if str(material["release_slug"]).startswith("nte-")
        else "展示目录版本中已记录的剪切模量字段；若字段缺失则不进行推断。"
    )
    return {
        "material": {
            "material_key": material["material_key"],
            "formula": material["formula"],
            "external_id": material["external_id"],
        },
        "properties": property_map,
        "bonding_modulus_definition": {
            "symbol": "E_tilde",
            "formula": "U_V/n = 160.21766208*abs(E_coh_eV_per_atom)/(AAV*avg_cn)",
            "unit": "GPa",
            "source": bonding_source,
        },
        "dataset_release": {
            "slug": material["release_slug"],
            "title": material["release_title"],
            "version": material["release_version"],
            "source_file_name": material["source_file_name"],
            "source_sha256": material["source_sha256"],
            "imported_at": material["imported_at"],
        },
        "method_notes": {
            "G_GPa": shear_method_note,
            "E_tilde_GPa": (
                "按论文定义由内聚能、平均原子体积和平均配位数现场重算："
                "E_tilde=160.21766208*abs(E_coh)/(AAV*avg_cn)。"
            ),
            "CTE_ppm": (
                "目录筛选字段用于材料检索和总体比较；精确温度依赖行为应优先参考"
                "已关联的各向异性 Cartesian/directional alpha_volume 曲线。"
            ),
            "precision_thermal_expansion": (
                "legacy 体积曲线；AGV2 记录来自 Cartesian alpha_volume，QHA 记录来自标量 QHA。"
            ),
            "anisotropic_thermal_expansion": (
                "AGV2 材料保留完整 Cartesian 六分量及晶轴 directional 曲线；"
                "立方 QHA 材料为 alpha_V/3 的显式各向同性派生表示。"
            ),
        },
        "precision_thermal_expansion": _precision_thermal_expansion(precision_job),
        "anisotropic_thermal_expansion": _anisotropic_thermal_expansion(anisotropic_curves),
        "structures": [dict(row) for row in structures],
        "quality_flags": [dict(row) for row in flags],
    }


def _curve_alpha_at_temperature(
    curve: dict[str, Any] | None,
    temperature_k: float,
) -> float | None:
    if curve is None:
        return None
    points = curve.get("points") or []
    if len(points) < 2:
        return None
    if temperature_k < float(points[0]["temperature_k"]) or temperature_k > float(
        points[-1]["temperature_k"]
    ):
        return None
    for left, right in zip(points, points[1:]):
        left_t = float(left["temperature_k"])
        right_t = float(right["temperature_k"])
        if left_t <= temperature_k <= right_t:
            left_alpha = float(left["alpha_ppm_per_k"])
            right_alpha = float(right["alpha_ppm_per_k"])
            if temperature_k == left_t or right_t == left_t:
                return left_alpha
            fraction = (temperature_k - left_t) / (right_t - left_t)
            return left_alpha + fraction * (right_alpha - left_alpha)
    return float(points[-1]["alpha_ppm_per_k"]) if temperature_k == float(
        points[-1]["temperature_k"]
    ) else None


def _anisotropic_alpha_at_temperature(
    curves: dict[str, Any] | None,
    temperature_k: float,
) -> float | None:
    """Interpolate the tensor-aware volumetric component at one temperature.

    Cartesian is preferred because it is the canonical six-component export;
    directional is a compatible fallback for releases that only contain the
    crystallographic-axis representation.  The returned value is in ppm/K,
    matching the catalog CTE field and the browser plots.
    """
    for kind in ("cartesian", "directional"):
        curve = (curves or {}).get(kind) or {}
        points = curve.get("points") or []
        normalized = []
        for point in points:
            try:
                temperature = float(point["T_K"])
                alpha = float(point["alpha_volume"])
            except (KeyError, TypeError, ValueError):
                continue
            if math.isfinite(temperature) and math.isfinite(alpha):
                normalized.append((temperature, alpha))
        if len(normalized) < 2:
            continue
        normalized.sort(key=lambda item: item[0])
        if temperature_k < normalized[0][0] or temperature_k > normalized[-1][0]:
            continue
        for (left_t, left_alpha), (right_t, right_alpha) in zip(normalized, normalized[1:]):
            if left_t <= temperature_k <= right_t:
                if temperature_k == left_t or right_t == left_t:
                    return left_alpha
                fraction = (temperature_k - left_t) / (right_t - left_t)
                return left_alpha + fraction * (right_alpha - left_alpha)
        if temperature_k == normalized[-1][0]:
            return normalized[-1][1]
    return None


def compare_materials(
    database_path: str | Path,
    release_slug: str,
    material_keys: list[str] | tuple[str, ...],
    *,
    temperature_k: float = 300.0,
) -> dict[str, Any]:
    if temperature_k < 0:
        raise ValueError("temperature_k must be non-negative")
    unique_keys = list(dict.fromkeys(str(key).strip() for key in material_keys if str(key).strip()))
    if not 2 <= len(unique_keys) <= 6:
        raise ValueError("Compare between 2 and 6 unique materials")
    compared: list[dict[str, Any]] = []
    for material_key in unique_keys:
        detail = material_detail(database_path, release_slug, material_key)
        properties = detail["properties"]

        def numeric_property(name: str) -> float | None:
            property_value = properties.get(name, {}).get("value")
            try:
                value = float(property_value)
            except (TypeError, ValueError):
                return None
            return value if math.isfinite(value) else None

        shear_modulus = numeric_property("G_GPa")
        bonding_modulus = numeric_property("E_tilde_GPa")
        xi = (
            shear_modulus / bonding_modulus
            if shear_modulus is not None and bonding_modulus is not None and bonding_modulus > 0
            else None
        )
        curve = detail["precision_thermal_expansion"]
        anisotropic_curves = detail["anisotropic_thermal_expansion"]
        alpha_at_temperature = _anisotropic_alpha_at_temperature(
            anisotropic_curves, temperature_k
        )
        if alpha_at_temperature is None:
            # Keep older catalog releases readable while all current 3665
            # records use the tensor-aware export above.
            alpha_at_temperature = _curve_alpha_at_temperature(curve, temperature_k)
        compared.append(
            {
                "material": detail["material"],
                "metrics": {
                    "G_GPa": shear_modulus,
                    "E_tilde_GPa": bonding_modulus,
                    "xi": xi,
                    "CTE_ppm": numeric_property("CTE_ppm"),
                    "K_GPa": numeric_property("K_GPa"),
                    "E_coh_eV_per_atom": numeric_property("E_coh_eV_per_atom"),
                    "avg_cn": numeric_property("avg_cn"),
                    "alpha_at_temperature_ppm_per_k": alpha_at_temperature,
                },
                "curve": curve,
                "anisotropic_thermal_expansion": detail["anisotropic_thermal_expansion"],
                "dataset_release": detail["dataset_release"],
                "quality_flags": detail["quality_flags"],
            }
        )
    return {
        "release_slug": release_slug,
        "temperature_k": float(temperature_k),
        "material_count": len(compared),
        "materials": compared,
        "method_note": (
            "表格比较目录字段；alpha(T)列由已存储的各向异性 alpha_volume 曲线线性插值得到。"
        ),
    }


def material_landscape(
    database_path: str | Path,
    release_slug: str,
    limit: int = 2000,
) -> list[dict[str, Any]]:
    if limit < 1 or limit > 7001:
        raise ValueError("limit must be between 1 and 7001")
    with connect_readonly_database(database_path) as connection:
        rows = connection.execute(
            f"""
            SELECT
                m.material_key,
                m.formula,
                {_numeric_property("G_GPa")},
                {_numeric_property("E_tilde_GPa", "stored_E_tilde_GPa")},
                {_numeric_property("E_coh_eV_per_atom")},
                {_numeric_property("AAV")},
                {_numeric_property("avg_cn")},
                {_numeric_property("CTE_ppm")},
                {_numeric_property("bond_modulus")},
                {_numeric_property("xi", "stored_xi")}
            FROM dataset_releases dr
            JOIN dataset_memberships dm ON dm.dataset_release_id = dr.id
            JOIN materials m ON m.id = dm.material_id
            JOIN material_properties mp
              ON mp.dataset_release_id = dr.id
             AND mp.material_id = m.id
            WHERE dr.slug = ?
            GROUP BY m.id
            HAVING G_GPa IS NOT NULL
            ORDER BY m.material_key
            LIMIT ?
            """,
            (release_slug, limit),
        ).fetchall()
    return [
        result
        for row in rows
        if (result := _canonicalize_material_row(row))["E_tilde_GPa"] is not None
    ]
