import sqlite3
import tempfile
import unittest
from pathlib import Path

from te_platform.api.services import ensure_catalog_database, ensure_workspace_database
from te_platform.db.schema import connect_readonly_database


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


if __name__ == "__main__":
    unittest.main()
