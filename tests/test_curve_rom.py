import unittest

from te_platform.composites.curve_rom import optimize_curve_rom


class CurveROMTests(unittest.TestCase):
    def test_optimizes_curve_and_converts_mass_fraction(self) -> None:
        result = optimize_curve_rom([8, 10, 12], [-12, -15, -18], pte_density=2, nte_density=4)
        self.assertAlmostEqual(result.nte_volume_fraction, 0.4)
        self.assertAlmostEqual(result.nte_mass_fraction, 0.5714285714)
        self.assertAlmostEqual(result.rms_error_ppm_per_k, 0.0)


if __name__ == "__main__":
    unittest.main()
