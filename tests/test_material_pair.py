import tempfile
import unittest
from pathlib import Path

from te_platform.composites.material_pair import curve_materials, optimize_material_pair
from te_platform.db.schema import connect_database, initialize_database
from te_platform.jobs.repository import import_historical_thermal_expansion_curve


class MaterialPairTests(unittest.TestCase):
    def _insert_curve_material(
        self,
        database: Path,
        release_slug: str,
        material_key: str,
        curve: tuple[tuple[float, float], ...],
    ) -> None:
        with connect_database(database) as connection:
            release = connection.execute(
                "SELECT id FROM dataset_releases WHERE slug=?", (release_slug,)
            ).fetchone()
            if release is None:
                cursor = connection.execute(
                    """INSERT INTO dataset_releases
                    (slug,title,version,record_count,source_file_name,source_sha256,manifest_json,imported_at)
                    VALUES (?,?,'1',1,'test','hash','{}','now')""",
                    (release_slug, release_slug),
                )
                release_id = cursor.lastrowid
            else:
                release_id = release["id"]
            cursor = connection.execute(
                "INSERT INTO materials(material_key,formula) VALUES (?,?)",
                (material_key, material_key.split(".")[-1]),
            )
            material_id = cursor.lastrowid
            connection.execute(
                "INSERT INTO dataset_memberships VALUES (?,?,0,'hash')",
                (release_id, material_id),
            )
            import_historical_thermal_expansion_curve(
                connection,
                material_id=material_id,
                source_path=str(database.parent / material_key / "thermal_expansion.dat"),
                thermal_expansion_curve=curve,
                alpha_300k_per_k=curve[1][1],
            )

    def test_lists_curve_materials_and_optimizes_pair_over_temperature_window(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            database = Path(temp) / "platform.db"
            initialize_database(database)
            pte_curve = ((0.0, 10e-6), (300.0, 10e-6), (600.0, 12e-6))
            nte_curve = ((0.0, -10e-6), (300.0, -10e-6), (600.0, -12e-6))
            self._insert_curve_material(database, "pte", "1.CaO", pte_curve)
            self._insert_curve_material(database, "nte", "NTE-mp-1", nte_curve)

            choices = curve_materials(database, "pte")
            positive_choices = curve_materials(database, "pte", alpha_sign=1)
            rejected_choices = curve_materials(database, "pte", alpha_sign=-1)
            result = optimize_material_pair(
                database,
                pte_release_slug="pte",
                nte_release_slug="nte",
                pte_material_key="1.CaO",
                nte_material_key="NTE-mp-1",
                temperature_min_k=300,
                temperature_max_k=600,
            )

            self.assertEqual(choices[0]["material_key"], "1.CaO")
            self.assertEqual(positive_choices[0]["formula"], "CaO")
            self.assertEqual(rejected_choices, [])
            self.assertAlmostEqual(result["nte_volume_fraction"], 0.5)
            self.assertAlmostEqual(result["rms_error_ppm_per_k"], 0.0)
            self.assertEqual(result["temperature_min_k"], 300.0)
            self.assertEqual(result["temperature_max_k"], 600.0)
            self.assertEqual(result["curve_temperature_min_k"], 0.0)
            self.assertEqual(result["curve_temperature_max_k"], 600.0)
            self.assertEqual(result["temperatures_k"], [0.0, 300.0, 600.0])
            self.assertEqual(result["mixed_alpha_ppm_per_k"], [0.0, 0.0, 0.0])


if __name__ == "__main__":
    unittest.main()
