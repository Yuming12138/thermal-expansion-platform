import tempfile
import unittest
from pathlib import Path

from te_platform.catalog.qha_curve_importer import import_historical_qha_curves
from te_platform.db.schema import connect_database, initialize_database


class QhaCurveImporterTests(unittest.TestCase):
    def test_imports_curves_matches_bad_suffix_and_skips_unknown_materials(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            database = root / "platform.db"
            initialize_database(database)
            with connect_database(database) as connection:
                connection.execute(
                    "INSERT INTO materials(material_key, formula, external_id) VALUES (?, ?, ?)",
                    ("Ag(AuF4)2-mp-18125", "Ag(AuF4)2", "mp-18125"),
                )
            good = root / "qha" / "0.bad_NTE" / "Ag(AuF4)2-mp-18125-bad"
            good.mkdir(parents=True)
            (good / "thermal_expansion.dat").write_text("0 0\n300 -1e-5\n", encoding="utf-8")
            unknown = root / "qha" / "Unknown-mp-999"
            unknown.mkdir()
            (unknown / "thermal_expansion.dat").write_text("0 0\n300 1e-5\n", encoding="utf-8")

            summary = import_historical_qha_curves(database, [root / "qha"])

            self.assertEqual(summary.scanned_files, 2)
            self.assertEqual(summary.imported_curves, 1)
            self.assertEqual(summary.unmatched_files, 1)
            with connect_database(database) as connection:
                row = connection.execute(
                    "SELECT points_json FROM precision_thermal_expansion_curves"
                ).fetchone()
            self.assertEqual(row["points_json"], "[[0.0,0.0],[300.0,-1e-05]]")


if __name__ == "__main__":
    unittest.main()
