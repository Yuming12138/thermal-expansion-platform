import unittest

from te_platform.composites.curve_rom import optimize_curve_rom, optimize_curve_turner


class CurveROMTests(unittest.TestCase):
    def test_optimizes_curve_and_converts_mass_fraction(self) -> None:
        result = optimize_curve_rom([8, 10, 12], [-12, -15, -18], pte_density=2, nte_density=4)
        self.assertAlmostEqual(result.nte_volume_fraction, 0.4)
        self.assertAlmostEqual(result.nte_mass_fraction, 0.5714285714)
        self.assertAlmostEqual(result.rms_error_ppm_per_k, 0.0)
        self.assertEqual(result.model, "linear_rom")

    def test_turner_uses_bulk_modulus_weighting(self) -> None:
        result = optimize_curve_turner(
            [10, 10, 10],
            [-10, -10, -10],
            temperatures_k=[300, 400, 500],
            pte_density=2,
            nte_density=4,
            pte_bulk_modulus_gpa=100,
            nte_bulk_modulus_gpa=50,
        )
        self.assertAlmostEqual(result.nte_volume_fraction, 2 / 3)
        self.assertAlmostEqual(result.nte_mass_fraction, 0.8)
        self.assertAlmostEqual(result.rms_error_ppm_per_k, 0.0)
        self.assertAlmostEqual(result.zte_temperature_coverage_fraction, 1.0)
        self.assertEqual(result.zte_temperature_ranges_k, ((300.0, 500.0),))

    def test_reports_continuous_zte_temperature_coverage(self) -> None:
        result = optimize_curve_rom(
            [10, 10],
            [0, 0],
            target_alpha=0,
            temperatures_k=[300, 500],
            zte_tolerance_ppm_per_k=2,
        )
        self.assertAlmostEqual(result.nte_volume_fraction, 1.0)
        self.assertAlmostEqual(result.zte_temperature_coverage_fraction, 1.0)
        self.assertAlmostEqual(result.zte_temperature_span_k, 200.0)


if __name__ == "__main__":
    unittest.main()
