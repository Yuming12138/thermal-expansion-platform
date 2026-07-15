from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from te_platform.agent.database_tools import (
    describe_catalog_database,
    execute_catalog_sql,
)
from te_platform.db.schema import connect_database, initialize_database


class AgentDatabaseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.database = Path(self.temporary_directory.name) / "catalog.sqlite"
        initialize_database(self.database)
        points = [[0.0, -1.0e-6], [300.0, -4.0e-6], [600.0, 2.0e-6]]
        with connect_database(self.database) as connection:
            release_id = connection.execute(
                """INSERT INTO dataset_releases
                (slug, title, version, record_count, source_file_name, source_sha256,
                 manifest_json, imported_at)
                VALUES ('nte-v1', 'NTE', '1.0', 1, 'source.json', 'abc', '{}', 'now')"""
            ).lastrowid
            material_id = connection.execute(
                "INSERT INTO materials(material_key, formula) VALUES ('sample-1', 'AB2')"
            ).lastrowid
            connection.execute(
                """INSERT INTO dataset_memberships
                (dataset_release_id, material_id, ordinal, source_record_sha256)
                VALUES (?, ?, 1, 'record')""",
                (release_id, material_id),
            )
            connection.execute(
                """INSERT INTO calculation_jobs
                (id, material_id, workflow, status, parameters_json, created_at, updated_at)
                VALUES ('job-1', ?, 'precision_qha', 'SUCCEEDED', '{}', 'now', 'now')""",
                (material_id,),
            )
            connection.execute(
                """INSERT INTO precision_thermal_expansion_curves
                (job_id, points_json, unit, parsed_at)
                VALUES ('job-1', ?, '1/K', 'now')""",
                (json.dumps(points),),
            )

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_describes_schema_and_domain_sql_function(self) -> None:
        result = describe_catalog_database(self.database)
        table_names = {item["name"] for item in result["tables"]}
        self.assertIn("materials", table_names)
        self.assertIn("precision_thermal_expansion_curves", table_names)
        self.assertEqual(result["access"], "read_only")
        self.assertEqual(
            result["sql_functions"][0]["name"],
            "alpha_at_temperature(points_json, temperature_k)",
        )

    def test_executes_parameterized_readonly_interpolation_query(self) -> None:
        result = execute_catalog_sql(
            self.database,
            """SELECT m.material_key,
                      alpha_at_temperature(c.points_json, :temperature_k) * 1000000 AS alpha_ppm
               FROM materials m
               JOIN calculation_jobs j ON j.material_id = m.id
               JOIN precision_thermal_expansion_curves c ON c.job_id = j.id""",
            parameters={"temperature_k": 300},
        )
        self.assertEqual(result["returned_row_count"], 1)
        self.assertEqual(result["rows"][0]["material_key"], "sample-1")
        self.assertAlmostEqual(result["rows"][0]["alpha_ppm"], -4.0)
        self.assertEqual(result["access"], "read_only")

    def test_denies_mutation_and_database_attachment(self) -> None:
        with self.assertRaisesRegex(ValueError, "Only SELECT"):
            execute_catalog_sql(self.database, "DELETE FROM materials")
        with self.assertRaisesRegex(ValueError, "Read-only SQL failed"):
            execute_catalog_sql(
                self.database,
                "WITH changed AS (DELETE FROM materials RETURNING id) SELECT * FROM changed",
            )
        with self.assertRaisesRegex(ValueError, "Only SELECT"):
            execute_catalog_sql(self.database, "ATTACH DATABASE 'other.sqlite' AS other")
        with self.assertRaisesRegex(ValueError, "Read-only SQL failed"):
            execute_catalog_sql(self.database, "SELECT randomblob(1000000)")

    def test_limits_rows_and_truncates_large_cells(self) -> None:
        result = execute_catalog_sql(
            self.database,
            "SELECT material_key, printf('%.*c', 9000, 'x') AS large_text FROM materials",
            max_rows=1,
        )
        self.assertTrue(result["rows"][0]["large_text"].endswith("…[truncated]"))
        self.assertEqual(result["truncated_cell_count"], 1)


if __name__ == "__main__":
    unittest.main()
