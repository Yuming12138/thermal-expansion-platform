from __future__ import annotations

from pathlib import Path
from typing import Any

from te_platform.db.schema import connect_database


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
        "structures": [dict(row) for row in structures],
        "quality_flags": [dict(row) for row in flags],
    }
