import unittest

from te_platform.reports.zte_report import build_zte_screening_report_pdf


class ZteReportTests(unittest.TestCase):
    def test_builds_screening_pdf_with_curves_and_pareto_data(self) -> None:
        design = {
            "rank": 1,
            "pte_material": {"formula": "CaO", "material_key": "1.CaO"},
            "nte_material": {"material_key": "NTE-1"},
            "nte_volume_fraction": 0.4,
            "nte_mass_fraction": 0.5,
            "zte_temperature_coverage_fraction": 1.0,
            "rms_error_ppm_per_k": 0.2,
            "zte_temperature_ranges_k": [[300, 600]],
            "temperatures_k": [300, 400, 500, 600],
            "mixed_alpha_ppm_per_k": [0.2, 0.1, -0.1, -0.2],
        }
        content = build_zte_screening_report_pdf(
            {
                "project_name": "ZTE test",
                "screening_parameters": {
                    "model": "linear_rom",
                    "temperature_min_k": 300,
                    "temperature_max_k": 600,
                    "target_alpha_ppm_per_k": 0,
                    "zte_tolerance_ppm_per_k": 5,
                },
                "ranked_results": [
                    {
                        "nte_volume_fraction": 0.4,
                        "rms_error_ppm_per_k": 0.2,
                        "zte_temperature_coverage_fraction": 1.0,
                    }
                ],
                "designs": [design],
            }
        )
        self.assertTrue(content.startswith(b"%PDF"))

    def test_builds_single_candidate_three_model_report(self) -> None:
        temperatures = [300, 400, 500, 600]
        model_results = {}
        for index, model in enumerate(("linear_rom", "turner", "kerner")):
            model_results[model] = {
                "model_label": model,
                "nte_volume_fraction": 0.4 + index * 0.05,
                "nte_mass_fraction": 0.5,
                "zte_temperature_coverage_fraction": 1.0,
                "rms_error_ppm_per_k": 0.2 + index * 0.1,
                "zte_temperature_ranges_k": [[300, 600]],
                "mixed_alpha_ppm_per_k": [0.2, 0.1, -0.1, -0.2],
            }
        design = {
            "rank": 1,
            "pte_material": {"formula": "CaO", "material_key": "1.CaO"},
            "nte_material": {"formula": "NTE", "material_key": "NTE-1"},
            "nte_volume_fraction": 0.4,
            "nte_mass_fraction": 0.5,
            "zte_temperature_coverage_fraction": 1.0,
            "rms_error_ppm_per_k": 0.2,
            "zte_temperature_ranges_k": [[300, 600]],
            "temperatures_k": temperatures,
            "pte_alpha_ppm_per_k": [10, 11, 12, 13],
            "nte_alpha_ppm_per_k": [-10, -11, -12, -13],
            "mixed_alpha_ppm_per_k": [0.2, 0.1, -0.1, -0.2],
            "model_results": model_results,
        }
        content = build_zte_screening_report_pdf(
            {
                "project_name": "Three model candidate",
                "screening_parameters": {
                    "model": "linear_rom",
                    "temperature_min_k": 300,
                    "temperature_max_k": 600,
                    "target_alpha_ppm_per_k": 0,
                    "zte_tolerance_ppm_per_k": 5,
                },
                "ranked_results": [],
                "designs": [design],
            }
        )
        self.assertTrue(content.startswith(b"%PDF"))


if __name__ == "__main__":
    unittest.main()
