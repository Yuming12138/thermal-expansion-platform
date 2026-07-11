import unittest

from te_platform.composites.rom import mix_alpha, optimize_zte_fraction


class ROMTests(unittest.TestCase):
    def test_mix_alpha(self) -> None:
        self.assertAlmostEqual(mix_alpha(10.0, -10.0, 0.25), 5.0)

    def test_exact_zte_fraction(self) -> None:
        result = optimize_zte_fraction(8.0, -12.0)
        self.assertAlmostEqual(result.nte_volume_fraction, 0.4)
        self.assertAlmostEqual(result.predicted_alpha, 0.0)
        self.assertTrue(result.feasible_exact_solution)

    def test_clamps_infeasible_target(self) -> None:
        result = optimize_zte_fraction(8.0, 4.0, target_alpha=0.0)
        self.assertEqual(result.nte_volume_fraction, 1.0)
        self.assertFalse(result.feasible_exact_solution)


if __name__ == "__main__":
    unittest.main()
