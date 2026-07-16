import tempfile
import unittest
from pathlib import Path

from te_platform.composites.screening import screen_material_pairs
from te_platform.db.schema import connect_database, initialize_database
from te_platform.jobs.repository import import_historical_thermal_expansion_curve


class CompositeScreeningTests(unittest.TestCase):
    def _insert_material(
        self,
        database: Path,
        release_slug: str,
        material_key: str,
        alpha_ppm_per_k: float,
        bulk_modulus_gpa: float,
        shear_modulus_gpa: float,
        *,
        formula: str | None = None,
        lattice_a: float | None = None,
        poscar_species: tuple[tuple[str, int], ...] = (("Si", 1),),
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
                (material_key, formula or material_key.split(".")[-1]),
            )
            material_id = cursor.lastrowid
            connection.execute(
                "INSERT INTO dataset_memberships VALUES (?,?,0,'hash')",
                (release_id, material_id),
            )
            connection.executemany(
                "INSERT INTO material_properties VALUES (?,?,?,?,NULL,'GPa')",
                (
                    (release_id, material_id, "K_GPa", bulk_modulus_gpa),
                    (release_id, material_id, "G_GPa", shear_modulus_gpa),
                ),
            )
            if lattice_a is not None:
                species = " ".join(symbol for symbol, _count in poscar_species)
                counts = " ".join(str(count) for _symbol, count in poscar_species)
                poscar = f"""{formula or material_key}
1.0
{lattice_a} 0 0
0 {lattice_a} 0
0 0 {lattice_a}
{species}
{counts}
Direct
""" + "\n".join("0 0 0" for _symbol, count in poscar_species for _index in range(count)) + "\n"
                connection.execute(
                    "INSERT INTO structures(dataset_release_id,material_id,format,content,content_sha256) VALUES (?,?, 'POSCAR',?,'hash')",
                    (release_id, material_id, poscar),
                )
            import_historical_thermal_expansion_curve(
                connection,
                material_id=material_id,
                source_path=str(database.parent / material_key / "thermal_expansion.dat"),
                thermal_expansion_curve=(
                    (300.0, alpha_ppm_per_k * 1e-6),
                    (600.0, alpha_ppm_per_k * 1e-6),
                ),
                alpha_300k_per_k=alpha_ppm_per_k * 1e-6,
            )

    def test_screens_all_pairs_and_returns_complete_ranking(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            database = Path(temp) / "catalog.db"
            initialize_database(database)
            self._insert_material(database, "pte", "1.PTE10", 10, 100, 40)
            self._insert_material(database, "pte", "2.PTE20", 20, 120, 45)
            self._insert_material(database, "nte", "NTE10", -10, 50, 20)
            self._insert_material(database, "nte", "NTE20", -20, 60, 25)
            self._insert_material(database, "nte", "NTE5", -5, 40, 15)

            result = screen_material_pairs(
                database,
                pte_release_slug="pte",
                nte_release_slug="nte",
                temperature_min_k=300,
                temperature_max_k=600,
                temperature_step_k=100,
                limit=4,
            )

            self.assertEqual(result["eligible_pte_count"], 2)
            self.assertEqual(result["eligible_nte_count"], 3)
            self.assertEqual(result["evaluated_pair_count"], 6)
            self.assertEqual(result["matched_pair_count"], 6)
            self.assertTrue(result["ranking_is_complete"])
            self.assertEqual(result["results"][0]["pte_material_key"], "1.PTE10")
            self.assertEqual(result["results"][0]["nte_material_key"], "NTE20")
            self.assertAlmostEqual(result["results"][0]["nte_volume_fraction"], 1 / 3)
            self.assertAlmostEqual(
                result["results"][0]["zte_temperature_coverage_fraction"], 1.0
            )

    def test_applies_fraction_query_and_kerner_matrix_constraints(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            database = Path(temp) / "catalog.db"
            initialize_database(database)
            self._insert_material(database, "pte", "1.Matrix", 10, 100, 40)
            self._insert_material(database, "nte", "NTE-a", -10, 50, 20)
            self._insert_material(database, "nte", "NTE-b", -20, 60, 25)

            result = screen_material_pairs(
                database,
                pte_release_slug="pte",
                nte_release_slug="nte",
                temperature_min_k=300,
                temperature_max_k=600,
                model="kerner",
                matrix_phase="pte",
                nte_query="NTE-b",
                nte_volume_fraction_max=0.5,
                require_matrix_majority=True,
                limit=10,
            )

            self.assertEqual(result["eligible_nte_count"], 1)
            self.assertEqual(result["evaluated_pair_count"], 1)
            self.assertEqual(result["matched_pair_count"], 1)
            self.assertTrue(result["results"][0]["model_applicable"])
            self.assertLessEqual(result["results"][0]["nte_volume_fraction"], 0.5)

    def test_applies_engineering_element_density_and_modulus_constraints(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            database = Path(temp) / "catalog.db"
            initialize_database(database)
            self._insert_material(
                database, "pte", "1.Al2O3", 10, 100, 40,
                formula="Al2O3", lattice_a=5, poscar_species=(("Al", 2), ("O", 3)),
            )
            self._insert_material(
                database, "nte", "ZrW2O8", -20, 50, 20,
                formula="ZrW2O8", lattice_a=9, poscar_species=(("Zr", 1), ("W", 2), ("O", 8)),
            )
            self._insert_material(
                database, "nte", "PbTiO3", -10, 10, 5,
                formula="PbTiO3", lattice_a=10, poscar_species=(("Pb", 1), ("Ti", 1), ("O", 3)),
            )

            result = screen_material_pairs(
                database,
                pte_release_slug="pte",
                nte_release_slug="nte",
                temperature_min_k=300,
                temperature_max_k=600,
                required_elements=["W"],
                excluded_elements=["Pb"],
                require_mass_fraction=True,
                require_complete_mechanics=True,
                max_density_ratio=2,
                max_bulk_modulus_ratio=3,
                max_shear_modulus_ratio=3,
                limit=10,
            )

            self.assertEqual(result["evaluated_pair_count"], 2)
            self.assertEqual(result["engineering_eligible_pair_count"], 1)
            self.assertEqual(result["matched_pair_count"], 1)
            self.assertEqual(result["results"][0]["nte_material_key"], "ZrW2O8")
            self.assertIsNotNone(result["results"][0]["nte_mass_fraction"])
            self.assertLessEqual(result["results"][0]["density_ratio"], 2)
            self.assertEqual(result["required_elements"], ["W"])
            self.assertEqual(result["excluded_elements"], ["Pb"])

    def test_rejects_invalid_or_conflicting_engineering_elements(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            database = Path(temp) / "catalog.db"
            initialize_database(database)
            with self.assertRaisesRegex(ValueError, "invalid element"):
                screen_material_pairs(
                    database,
                    pte_release_slug="pte",
                    nte_release_slug="nte",
                    required_elements=["Xx"],
                )
            with self.assertRaisesRegex(ValueError, "overlap"):
                screen_material_pairs(
                    database,
                    pte_release_slug="pte",
                    nte_release_slug="nte",
                    required_elements=["W"],
                    excluded_elements=["W"],
                )


if __name__ == "__main__":
    unittest.main()
