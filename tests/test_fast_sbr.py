import unittest

from te_platform.screening.fast_sbr import (
    calculate_bonding_modulus,
    calculate_bonding_modulus_from_atomic_volume,
    fast_screen_sbr,
)


class FastSBRTests(unittest.TestCase):
    def test_bonding_modulus_formula(self) -> None:
        result = calculate_bonding_modulus(-4.0, 80.0, 8, 4.0)
        self.assertAlmostEqual(result.volume_per_atom_a3, 10.0)
        self.assertAlmostEqual(result.bonding_modulus_gpa, 16.021766208)

        from_atomic_volume = calculate_bonding_modulus_from_atomic_volume(
            -4.0, 10.0, 4.0
        )
        self.assertAlmostEqual(from_atomic_volume.bonding_modulus_gpa, 16.021766208)

    def test_boundary_result_recommends_precision_workflow(self) -> None:
        result = fast_screen_sbr(
            predicted_shear_modulus_gpa=42.0,
            cohesive_energy_ev_per_atom=-4.0,
            cell_volume_a3=80.0,
            atom_count=8,
            average_coordination_number=4.0,
        )
        self.assertEqual(result.decision_quality, "boundary_review")
        self.assertIn("full elastic tensor", result.recommended_next_step)

    def test_robust_nte(self) -> None:
        result = fast_screen_sbr(
            predicted_shear_modulus_gpa=10.0,
            cohesive_energy_ev_per_atom=-5.0,
            cell_volume_a3=50.0,
            atom_count=10,
            average_coordination_number=3.0,
            shear_model_mae_gpa=2.0,
        )
        self.assertEqual(result.decision_quality, "robust_high_probability_nte")


if __name__ == "__main__":
    unittest.main()
