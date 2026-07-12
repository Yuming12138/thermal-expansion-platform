from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from te_platform.db.schema import connect_database


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
        "updated_at": job["updated_at"],
        "points": points,
        "quality_warnings": result.get("quality_warnings", []),
        "source_path": job["source_path"] or result.get("thermal_expansion_source_path"),
    }


def dataset_summary(
    database_path: str | Path,
    release_slug: str,
) -> dict[str, Any]:
    with connect_database(database_path) as connection:
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
) -> list[dict[str, Any]]:
    if limit < 1 or limit > 500:
        raise ValueError("limit must be between 1 and 500")
    pattern = f"%{query.strip()}%"
    with connect_database(database_path) as connection:
        rows = connection.execute(
            """
            SELECT
                m.material_key,
                m.formula,
                m.external_id,
                MAX(CASE WHEN mp.name = 'K_GPa' THEN mp.numeric_value END) AS K_GPa,
                MAX(CASE WHEN mp.name = 'G_GPa' THEN mp.numeric_value END) AS G_GPa,
                MAX(CASE WHEN mp.name = 'E_tilde_GPa' THEN mp.numeric_value END) AS E_tilde_GPa,
                MAX(CASE WHEN mp.name = 'CTE_ppm' THEN mp.numeric_value END) AS CTE_ppm
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
            GROUP BY m.id
            ORDER BY m.material_key
            LIMIT ?
            """,
            (release_slug, pattern, pattern, pattern, pattern, limit),
        ).fetchall()
    return [dict(row) for row in rows]


def material_detail(
    database_path: str | Path,
    release_slug: str,
    material_key: str,
) -> dict[str, Any]:
    with connect_database(database_path) as connection:
        material = connection.execute(
            """
            SELECT m.id, m.material_key, m.formula, m.external_id, dr.id AS release_id
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
            SELECT format, content_sha256, LENGTH(content) AS content_characters
            FROM structures
            WHERE dataset_release_id = ? AND material_id = ?
            ORDER BY format
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
    return {
        "material": {
            "material_key": material["material_key"],
            "formula": material["formula"],
            "external_id": material["external_id"],
        },
        "properties": property_map,
        "precision_thermal_expansion": _precision_thermal_expansion(precision_job),
        "structures": [dict(row) for row in structures],
        "quality_flags": [dict(row) for row in flags],
    }


def material_landscape(
    database_path: str | Path,
    release_slug: str,
    limit: int = 2000,
) -> list[dict[str, Any]]:
    if limit < 1 or limit > 7001:
        raise ValueError("limit must be between 1 and 7001")
    with connect_database(database_path) as connection:
        rows = connection.execute(
            """
            SELECT
                m.material_key,
                m.formula,
                MAX(CASE WHEN mp.name = 'G_GPa' THEN mp.numeric_value END) AS G_GPa,
                MAX(CASE WHEN mp.name = 'E_tilde_GPa' THEN mp.numeric_value END) AS E_tilde_GPa,
                MAX(CASE WHEN mp.name = 'CTE_ppm' THEN mp.numeric_value END) AS CTE_ppm
            FROM dataset_releases dr
            JOIN dataset_memberships dm ON dm.dataset_release_id = dr.id
            JOIN materials m ON m.id = dm.material_id
            JOIN material_properties mp
              ON mp.dataset_release_id = dr.id
             AND mp.material_id = m.id
            WHERE dr.slug = ?
            GROUP BY m.id
            HAVING G_GPa IS NOT NULL AND E_tilde_GPa IS NOT NULL
            ORDER BY m.material_key
            LIMIT ?
            """,
            (release_slug, limit),
        ).fetchall()
    return [dict(row) for row in rows]
