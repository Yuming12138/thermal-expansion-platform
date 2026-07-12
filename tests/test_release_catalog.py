import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from te_platform.catalog.release_catalog import build_release_catalog
from te_platform.db.schema import connect_database, initialize_database


class ReleaseCatalogTests(unittest.TestCase):
    def test_builds_sanitized_catalog_and_removes_development_jobs(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "dev.db"
            output = root / "catalog-v1.sqlite"
            initialize_database(source)
            with connect_database(source) as connection:
                release_id = connection.execute(
                    """INSERT INTO dataset_releases
                    (slug,title,version,record_count,source_file_name,source_sha256,manifest_json,imported_at)
                    VALUES ('nte','NTE','1',1,'source.json','hash',?,'now')""",
                    (json.dumps({"source_root": r"D:\research\NTE_data"}),),
                ).lastrowid
                material_id = connection.execute(
                    "INSERT INTO materials(material_key,formula) VALUES ('NTE-mp-1','NTE')"
                ).lastrowid
                connection.execute(
                    "INSERT INTO dataset_memberships VALUES (?,?,0,'hash')",
                    (release_id, material_id),
                )
                connection.execute(
                    "INSERT INTO structures(dataset_release_id,material_id,format,content,content_sha256) VALUES (?,?,'POSCAR','NTE','hash')",
                    (release_id, material_id),
                )
                connection.execute(
                    "INSERT INTO material_properties VALUES (?,?, 'CTE_ppm',-10,NULL,'ppm/K')",
                    (release_id, material_id),
                )
                connection.execute(
                    """INSERT INTO calculation_jobs
                    VALUES ('historical',?,'historical_qha_thermal_expansion','historical-qha-import','SUCCEEDED',?,?,NULL,'now','now')""",
                    (
                        material_id,
                        json.dumps({"source_path": r"D:\research\NTE_data\NTE-mp-1\thermal_expansion.dat"}),
                        json.dumps(
                            {
                                "thermal_expansion_source_path": r"D:\research\NTE_data\NTE-mp-1\thermal_expansion.dat"
                            }
                        ),
                    ),
                )
                connection.execute(
                    "INSERT INTO precision_thermal_expansion_curves VALUES ('historical','[[0,0],[300,-1e-5]]','1/K',?,'now')",
                    (r"D:\research\NTE_data\NTE-mp-1\thermal_expansion.dat",),
                )
                connection.execute(
                    """INSERT INTO calculation_jobs
                    VALUES ('development',?,'precision_elastic_qha','mattersim','FAILED','{}',NULL,'failed','now','now')""",
                    (material_id,),
                )

            summary = build_release_catalog(source, output)

            self.assertEqual(summary.materials, 1)
            self.assertEqual(summary.curves, 1)
            self.assertEqual(summary.removed_development_jobs, 1)
            self.assertTrue(Path(summary.manifest_path).is_file())
            with closing(sqlite3.connect(output)) as connection:
                jobs = connection.execute("SELECT id,parameters_json FROM calculation_jobs").fetchall()
                curve_path = connection.execute(
                    "SELECT source_path FROM precision_thermal_expansion_curves"
                ).fetchone()[0]
                manifest_json = connection.execute(
                    "SELECT manifest_json FROM dataset_releases"
                ).fetchone()[0]
                integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
            self.assertEqual([row[0] for row in jobs], ["historical"])
            self.assertIn("catalog://nte/NTE-mp-1/thermal_expansion.dat", jobs[0][1])
            self.assertEqual(curve_path, "catalog://nte/NTE-mp-1/thermal_expansion.dat")
            self.assertNotIn("D:\\", manifest_json)
            self.assertEqual(integrity, "ok")


if __name__ == "__main__":
    unittest.main()
