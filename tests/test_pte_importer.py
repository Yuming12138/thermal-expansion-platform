import csv
import tempfile
import unittest
from pathlib import Path

from te_platform.catalog.pte_importer import import_pte_reference
from te_platform.db.schema import connect_database


class PteImporterTests(unittest.TestCase):
    def test_imports_pte_material_structure_properties_and_curve(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "PTE_materials"
            material = source / "25.Fe3O4-mp-19306"
            material.mkdir(parents=True)
            (material / "POSCAR").write_text("Fe3O4\n", encoding="utf-8")
            (material / "thermal_expansion.dat").write_text(
                "0 0\n300 1.5e-5\n600 2e-5\n", encoding="utf-8"
            )
            summary_csv = root / "pte.csv"
            with summary_csv.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=["material_folder", "G_GPa", "source"],
                )
                writer.writeheader()
                writer.writerow(
                    {"material_folder": "25.Fe3O4-mp-19306", "G_GPa": "40", "source": "our"}
                )
            database = root / "platform.db"

            summary = import_pte_reference(database, source, summary_csv)

            self.assertEqual(summary.materials, 1)
            self.assertEqual(summary.curves, 1)
            with connect_database(database) as connection:
                release = connection.execute(
                    "SELECT record_count FROM dataset_releases WHERE slug = 'pte-reference-185-v1'"
                ).fetchone()
                curve_count = connection.execute(
                    "SELECT COUNT(*) FROM precision_thermal_expansion_curves"
                ).fetchone()[0]
                phase = connection.execute(
                    "SELECT text_value FROM material_properties WHERE name='thermal_expansion_class'"
                ).fetchone()
                formula = connection.execute("SELECT formula FROM materials").fetchone()
            self.assertEqual(release["record_count"], 1)
            self.assertEqual(curve_count, 1)
            self.assertEqual(phase["text_value"], "PTE")
            self.assertEqual(formula["formula"], "Fe3O4")


if __name__ == "__main__":
    unittest.main()
