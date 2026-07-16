import unittest

from te_platform.composites.curve_rom import (
    analyze_fraction_robustness,
    mix_curve,
    optimize_curve_kerner,
    optimize_curve_rom,
    optimize_curve_turner,
    resolve_target_alpha_curve,
)


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

    def test_kerner_uses_matrix_shear_constraint(self) -> None:
        mixed = mix_curve(
            [10, 10],
            [-10, -10],
            0.5,
            model="kerner",
            pte_bulk_modulus_gpa=100,
            nte_bulk_modulus_gpa=50,
            pte_shear_modulus_gpa=40,
            nte_shear_modulus_gpa=20,
            matrix_phase="pte",
        )
        self.assertAlmostEqual(mixed[0], 1.4814814815)

    def test_kerner_optimizes_fraction_and_records_matrix_phase(self) -> None:
        result = optimize_curve_kerner(
            [10, 10, 10],
            [-10, -10, -10],
            temperatures_k=[300, 400, 500],
            pte_bulk_modulus_gpa=100,
            nte_bulk_modulus_gpa=50,
            pte_shear_modulus_gpa=40,
            nte_shear_modulus_gpa=20,
            matrix_phase="pte",
        )
        self.assertGreater(result.nte_volume_fraction, 0.5)
        self.assertAlmostEqual(result.rms_error_ppm_per_k, 0.0, places=8)
        self.assertAlmostEqual(result.effective_nte_thermal_weight, 0.5, places=8)
        self.assertEqual(result.matrix_phase, "pte")
        self.assertEqual(result.model_label, "Kerner 模型（PTE基体）")

    def test_kerner_reduces_to_linear_rom_when_bulk_moduli_match(self) -> None:
        mixed = mix_curve(
            [10, 20],
            [-10, -20],
            0.25,
            model="kerner",
            pte_bulk_modulus_gpa=80,
            nte_bulk_modulus_gpa=80,
            pte_shear_modulus_gpa=30,
            nte_shear_modulus_gpa=25,
            matrix_phase="nte",
        )
        self.assertEqual(mixed, (5.0, 10.0))

    def test_optimizes_against_arbitrary_target_curve(self) -> None:
        result = optimize_curve_rom(
            [10, 20],
            [-10, 0],
            temperatures_k=[300, 500],
            target_alpha_curve=[5, 15],
        )
        self.assertAlmostEqual(result.nte_volume_fraction, 0.25)
        self.assertAlmostEqual(result.rms_error_ppm_per_k, 0.0)
        self.assertEqual(result.target_alpha_curve_ppm_per_k, (5.0, 15.0))

    def test_interpolates_piecewise_target_curve_and_requires_coverage(self) -> None:
        values = resolve_target_alpha_curve(
            [300, 350, 500],
            target_curve_points=[(300, 5), (400, 10), (500, 15)],
        )
        self.assertEqual(values, (5.0, 7.5, 15.0))
        with self.assertRaisesRegex(ValueError, "cover"):
            resolve_target_alpha_curve(
                [300, 500],
                target_curve_points=[(350, 5), (500, 15)],
            )

    def test_analyzes_robust_fraction_window_and_rounded_formulation(self) -> None:
        analysis = analyze_fraction_robustness(
            [10, 10, 10],
            [-10, -10, -10],
            optimal_nte_volume_fraction=0.5,
            target_alpha_curve=[0, 0, 0],
            temperatures_k=[300, 400, 500],
            pte_density=2,
            nte_density=4,
            target_tolerance_ppm_per_k=2,
            minimum_target_coverage_fraction=1,
            fraction_step=0.05,
            formulation_total_mass_g=10,
            balance_resolution_g=0.1,
        )
        self.assertAlmostEqual(analysis["robust_fraction_min"], 0.4)
        self.assertAlmostEqual(analysis["robust_fraction_max"], 0.6)
        self.assertAlmostEqual(analysis["robust_fraction_span"], 0.2)
        formulation = analysis["optimal_formulation"]
        self.assertTrue(formulation["available"])
        self.assertAlmostEqual(formulation["rounded_pte_mass_g"], 3.3)
        self.assertAlmostEqual(formulation["rounded_nte_mass_g"], 6.7)
        self.assertAlmostEqual(formulation["actual_nte_volume_fraction"], 0.5037593985)


if __name__ == "__main__":
    unittest.main()
