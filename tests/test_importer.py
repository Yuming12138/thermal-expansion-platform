import gzip
import json
import tempfile
import unittest
from pathlib import Path

from te_platform.catalog.importer import import_dataset
from te_platform.catalog.provenance import sha256_file
from te_platform.catalog.queries import search_materials
from te_platform.db.schema import connect_database


class DatasetImporterTests(unittest.TestCase):
    def test_imports_versioned_dataset(self) -> None:
        rows = [
            {
                "material_folder": "ZrW2O8-mp-1",
                "POSCAR": "ZrW2O8\n1.0\n",
                "G_GPa": 20.0,
                "E_tilde_GPa": 10.0,
                "CTE_ppm": -8.0,
            },
            {
                "material_folder": "Al2O3-mp-2",
                "POSCAR": "Al2O3\n1.0\n",
                "G_GPa": 100.0,
                "E_tilde_GPa": 20.0,
                "CTE_ppm": 7.0,
                "porosity": -0.1,
            },
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            dataset = root / "sample.json.gz"
            with gzip.open(dataset, "wt", encoding="utf-8") as handle:
                json.dump(rows, handle)
            manifest = root / "manifest.json"
            manifest.write_text(
                json.dumps(
                    {
                        "release_slug": "test-v1",
                        "title": "Test dataset",
                        "version": "1.0.0",
                        "record_count": 2,
                        "snapshot_sha256": sha256_file(dataset),
                    }
                ),
                encoding="utf-8",
            )
            database = root / "test.db"
            summary = import_dataset(database, dataset, manifest)
            self.assertEqual(summary.records, 2)
            self.assertEqual(summary.properties, 7)
            self.assertEqual(summary.quality_flags, 1)
            with connect_database(database) as connection:
                count = connection.execute("SELECT COUNT(*) FROM materials").fetchone()[0]
            self.assertEqual(count, 2)
            found = search_materials(database, "test-v1", "ZrW2O8")
            self.assertEqual(len(found), 1)
            self.assertEqual(found[0]["external_id"], "mp-1")


if __name__ == "__main__":
    unittest.main()
