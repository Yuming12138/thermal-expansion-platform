import unittest

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


if __name__ == "__main__":
    unittest.main()
