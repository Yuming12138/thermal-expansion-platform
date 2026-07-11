import unittest

from fastapi.testclient import TestClient

from te_platform.api.app import create_app


POSCAR = b"""BaCrSi4O10
1.0
5.000000 0.000000 0.000000
0.000000 5.000000 0.000000
0.000000 0.000000 5.000000
Ba Cr Si O
1 1 4 10
Direct
"""

CIF = b"""data_example
_cell_length_a 5.0
_cell_length_b 5.0
_cell_length_c 5.0
_cell_angle_alpha 90
_cell_angle_beta 90
_cell_angle_gamma 90
loop_
_atom_site_label
_atom_site_type_symbol
_atom_site_fract_x
Ba1 Ba 0 0 0
"""


class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client_context = TestClient(create_app())
        cls.client = cls.client_context.__enter__()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.client_context.__exit__(None, None, None)

    def test_health_and_dataset_summary(self) -> None:
        home = self.client.get("/")
        self.assertEqual(home.status_code, 200)
        self.assertIn("热膨胀材料智能计算与设计平台", home.text)

        health = self.client.get("/api/health")
        self.assertEqual(health.status_code, 200)
        self.assertEqual(health.json()["status"], "ok")
        self.assertEqual(health.json()["material_count"], 6701)

        dataset = self.client.get("/api/datasets/current")
        self.assertEqual(dataset.status_code, 200)
        self.assertEqual(dataset.json()["counts"]["materials"], 6701)

    def test_material_search_detail_and_landscape(self) -> None:
        materials = self.client.get("/api/materials", params={"query": "BaCrSi4O10"})
        self.assertEqual(materials.status_code, 200)
        self.assertGreaterEqual(len(materials.json()), 1)
        material_key = materials.json()[0]["material_key"]

        detail = self.client.get(f"/api/materials/{material_key}")
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.json()["material"]["material_key"], material_key)

        landscape = self.client.get("/api/materials/landscape", params={"limit": 10})
        self.assertEqual(landscape.status_code, 200)
        self.assertGreaterEqual(len(landscape.json()), 1)

    def test_scientific_calculation_endpoints(self) -> None:
        sbr = self.client.post(
            "/api/sbr/classify",
            json={"shear_modulus_gpa": 20.0, "bonding_modulus_gpa": 10.0},
        )
        self.assertEqual(sbr.status_code, 200)
        self.assertEqual(sbr.json()["classification"], "high_probability_nte")

        fast = self.client.post(
            "/api/sbr/fast-screen",
            json={
                "predicted_shear_modulus_gpa": 10.0,
                "cohesive_energy_ev_per_atom": -5.0,
                "cell_volume_a3": 50.0,
                "atom_count": 10,
                "average_coordination_number": 3.0,
                "shear_model_mae_gpa": 2.0,
            },
        )
        self.assertEqual(fast.status_code, 200)
        self.assertEqual(fast.json()["decision_quality"], "robust_high_probability_nte")

        rom = self.client.post(
            "/api/composites/rom",
            json={"alpha_pte": 8.0, "alpha_nte": -12.0, "target_alpha": 0.0},
        )
        self.assertEqual(rom.status_code, 200)
        self.assertAlmostEqual(rom.json()["nte_volume_fraction"], 0.4)

    def test_structure_inspection_for_poscar_and_cif(self) -> None:
        poscar = self.client.post(
            "/api/structures/inspect",
            files={"file": ("POSCAR", POSCAR, "text/plain")},
        )
        self.assertEqual(poscar.status_code, 200)
        self.assertEqual(poscar.json()["inspection"]["atom_count"], 16)
        self.assertAlmostEqual(poscar.json()["inspection"]["cell_volume_a3"], 125.0)

        cif = self.client.post(
            "/api/structures/inspect",
            files={"file": ("example.cif", CIF, "text/plain")},
        )
        self.assertEqual(cif.status_code, 200)
        self.assertAlmostEqual(cif.json()["inspection"]["cell_volume_a3"], 125.0)


if __name__ == "__main__":
    unittest.main()
