import sqlite3
import tempfile
import unittest
from pathlib import Path

from te_platform.api.services import ensure_catalog_database, ensure_workspace_database
from te_platform.db.schema import connect_database, connect_readonly_database, initialize_database


class DatabaseSeparationTests(unittest.TestCase):
    def test_missing_catalog_fails_without_creating_or_importing_data(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            catalog = Path(temp) / "missing-catalog.sqlite"

            with self.assertRaisesRegex(RuntimeError, "Catalog database is missing"):
                ensure_catalog_database(catalog)

            self.assertFalse(catalog.exists())

    def test_workspace_initialization_does_not_create_catalog_releases(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            workspace = Path(temp) / "workspace.sqlite"

            ensure_workspace_database(workspace)

            with connect_readonly_database(workspace) as connection:
                release_count = connection.execute(
                    "SELECT COUNT(*) FROM dataset_releases"
                ).fetchone()[0]
                job_count = connection.execute(
                    "SELECT COUNT(*) FROM calculation_jobs"
                ).fetchone()[0]
                with self.assertRaises(sqlite3.OperationalError):
                    connection.execute(
                        "INSERT INTO schema_metadata(key,value) VALUES ('forbidden','write')"
                    )
            self.assertEqual(release_count, 0)
            self.assertEqual(job_count, 0)

    def test_catalog_release_requirements_can_be_scoped_per_app_instance(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            catalog = Path(temp) / "catalog.sqlite"
            initialize_database(catalog)
            with connect_database(catalog) as connection:
                connection.executemany(
                    """
                    INSERT INTO dataset_releases(
                        slug, title, version, record_count, source_file_name,
                        source_sha256, manifest_json, imported_at
                    ) VALUES (?, ?, ?, 0, ?, ?, ?, ?)
                    """,
                    [
                        (
                            "test-nte",
                            "Test NTE",
                            "1.0",
                            "synthetic://nte",
                            "0" * 64,
                            "{}",
                            "1970-01-01",
                        ),
                        (
                            "test-pte",
                            "Test PTE",
                            "1.0",
                            "synthetic://pte",
                            "0" * 64,
                            "{}",
                            "1970-01-01",
                        ),
                    ],
                )

            ensure_catalog_database(
                catalog,
                required_release_slugs=("test-nte", "test-pte"),
            )
            with self.assertRaisesRegex(RuntimeError, "nte-candidates-3665-agv2-v2"):
                ensure_catalog_database(catalog)


if __name__ == "__main__":
    unittest.main()
