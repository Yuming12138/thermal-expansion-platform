import tempfile
import unittest
from pathlib import Path

from te_platform.precision.results import parse_precision_results


class PrecisionResultsTests(unittest.TestCase):
    def test_parses_known_bacrsio_result(self) -> None:
        result = parse_precision_results(
            r"D:\9.Project\10.recalcu_elastic_nte\1.Gaoqilong_data\1.Gaoqilong\1.ordered\BaCrSi4O10"
        )
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


if __name__ == "__main__":
    unittest.main()
