import unittest

from te_platform.screening.sbr import classify_sbr


class SBRTests(unittest.TestCase):
    def test_high_probability_nte(self) -> None:
        result = classify_sbr(20.0, 10.0)
        self.assertEqual(result.classification, "high_probability_nte")
        self.assertAlmostEqual(result.xi, 2.0)

    def test_nte_between_two_thresholds(self) -> None:
        result = classify_sbr(26.0, 10.0)
        self.assertEqual(result.classification, "nte")

    def test_pte(self) -> None:
        result = classify_sbr(30.0, 10.0)
        self.assertEqual(result.classification, "pte")

    def test_rejects_nonpositive_bonding_modulus(self) -> None:
        with self.assertRaises(ValueError):
            classify_sbr(10.0, 0.0)


if __name__ == "__main__":
    unittest.main()
