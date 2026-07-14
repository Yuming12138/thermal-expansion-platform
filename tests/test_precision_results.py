import os
import tempfile
import unittest
from pathlib import Path

from te_platform.precision.results import (
    parse_elastic_results,
    parse_precision_results,
    parse_qha_results,
    parse_thermal_expansion_file,
)


class PrecisionResultsTests(unittest.TestCase):
    @unittest.skipUnless(
        os.environ.get("TEP_REFERENCE_PRECISION_RESULT"),
        "Set TEP_REFERENCE_PRECISION_RESULT to run the workstation reference-result test",
    )
    def test_parses_known_bacrsio_result(self) -> None:
        result = parse_precision_results(os.environ["TEP_REFERENCE_PRECISION_RESULT"])
        self.assertTrue(result.elastic_positive_definite)
        self.assertEqual(len(result.elastic_tensor_gpa), 6)
        self.assertGreater(result.elastic_min_eigenvalue_gpa, 0)
        self.assertAlmostEqual(result.alpha_300k_per_k, 5.922688175e-6)
        self.assertAlmostEqual(result.alpha_300k_ppm_per_k, 5.922688175)
        self.assertIn("re-optimization", " ".join(result.quality_warnings))

    def test_warns_when_qha_log_reports_imaginary_phonons(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            elastic = root / "elastic"
            thermal = root / "thermal_properties"
            elastic.mkdir()
            thermal.mkdir()
            (elastic / "ELASTIC_TENSOR").write_text(
                "\n".join(
                    " ".join("1" if row == column else "0" for column in range(6))
                    for row in range(6)
                ),
                encoding="utf-8",
            )
            (thermal / "thermal_expansion.dat").write_text("100 1e-6\n500 2e-6\n", encoding="utf-8")
            (root / "qha_calc.log").write_text("Warning! Imaginary frequencies found!\n", encoding="utf-8")

            result = parse_precision_results(root)

            self.assertIn("Imaginary phonon frequencies", " ".join(result.quality_warnings))

    def test_reads_standalone_thermal_expansion_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "thermal_expansion.dat"
            path.write_text("0 0\n300 -1.23e-5\n", encoding="utf-8")
            self.assertEqual(parse_thermal_expansion_file(path), ((0.0, 0.0), (300.0, -1.23e-5)))

    def test_parses_elastic_only_and_qha_only_results(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            elastic = root / "elastic"
            thermal = root / "qha_calculation" / "thermal_properties"
            elastic.mkdir()
            thermal.mkdir(parents=True)
            (elastic / "ELASTIC_TENSOR").write_text(
                "\n".join(" ".join("100" if row == column else "0" for column in range(6)) for row in range(6)),
                encoding="utf-8",
            )
            (thermal / "thermal_expansion.dat").write_text("0 0\n300 -2e-6\n", encoding="utf-8")

            elastic_result = parse_elastic_results(root)
            qha_result = parse_qha_results(root)

            self.assertAlmostEqual(elastic_result.shear_modulus_hill_gpa, 75.7142857143)
            self.assertAlmostEqual(qha_result.alpha_300k_ppm_per_k, -2.0)


if __name__ == "__main__":
    unittest.main()
