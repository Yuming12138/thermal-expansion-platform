"""Read-only validation for the published 3665-material catalog."""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path


def verify(path: Path) -> dict[str, object]:
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    try:
        nte_slug = "nte-candidates-3665-agv2-v2"
        return {
            "database": str(path.resolve()),
            "integrity": connection.execute("PRAGMA integrity_check").fetchone()[0],
            "foreign_key_violations": len(connection.execute("PRAGMA foreign_key_check").fetchall()),
            "releases": [
                dict(row)
                for row in connection.execute(
                    "SELECT slug, record_count, version FROM dataset_releases ORDER BY id"
                )
            ],
            "nte_members": connection.execute(
                """SELECT COUNT(*) FROM dataset_memberships dm
                JOIN dataset_releases dr ON dr.id = dm.dataset_release_id
                WHERE dr.slug = ?""",
                (nte_slug,),
            ).fetchone()[0],
            "structures": [
                dict(row)
                for row in connection.execute(
                    """SELECT format, COUNT(*) AS count FROM structures s
                    JOIN dataset_releases dr ON dr.id = s.dataset_release_id
                    WHERE dr.slug = ? GROUP BY format ORDER BY format""",
                    (nte_slug,),
                )
            ],
            "anisotropic_curves": [
                dict(row)
                for row in connection.execute(
                    """SELECT curve_kind, COUNT(*) AS count
                    FROM anisotropic_thermal_expansion_curves ac
                    JOIN dataset_releases dr ON dr.id = ac.dataset_release_id
                    WHERE dr.slug = ? GROUP BY curve_kind ORDER BY curve_kind""",
                    (nte_slug,),
                )
            ],
            "methods": [
                dict(row)
                for row in connection.execute(
                    """SELECT text_value AS method, COUNT(*) AS count
                    FROM material_properties mp
                    JOIN dataset_releases dr ON dr.id = mp.dataset_release_id
                    WHERE dr.slug = ? AND mp.name = 'thermal_expansion_method'
                    GROUP BY text_value ORDER BY text_value""",
                    (nte_slug,),
                )
            ],
            "recalculation_adopted": connection.execute(
                """SELECT COUNT(*) FROM material_properties mp
                JOIN dataset_releases dr ON dr.id = mp.dataset_release_id
                WHERE dr.slug = ? AND mp.name = 'recalculation_adopted'
                  AND mp.numeric_value = 1""",
                (nte_slug,),
            ).fetchone()[0],
        }
    finally:
        connection.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("database", type=Path)
    args = parser.parse_args()
    if not args.database.is_file():
        raise SystemExit(f"Database does not exist: {args.database}")
    print(json.dumps(verify(args.database), ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
