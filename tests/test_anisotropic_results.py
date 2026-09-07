import json
import tempfile
import unittest
from pathlib import Path

from te_platform.precision.results import parse_anisotropic_results


class AnisotropicResultsTests(unittest.TestCase):
    def test_parses_cartesian_and_directional_curves(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "gruneisen_aniso_1M_v2"
            root.mkdir()
            (root / "thermal_expansion_cartesian.dat").write_text(
                "# T_K alpha_xx alpha_yy alpha_zz alpha_yz_eng alpha_xz_eng alpha_xy_eng alpha_volume\n"
                "100 -1 -2 -3 0 0 0 -6\n300 1 2 3 0 0 0 6\n",
                encoding="utf-8",
            )
            (root / "thermal_expansion_directional.dat").write_text(
                "# T_K alpha_a alpha_b alpha_c alpha_volume F_ani\n"
                "100 -1 -2 -3 -6 .2\n300 1 2 3 6 .3\n",
                encoding="utf-8",
            )
            (root / "quality_report.json").write_text(
                json.dumps({"production_readiness": {"status": "ready"}}),
                encoding="utf-8",
            )
            result = parse_anisotropic_results(directory, crystal_system="tetragonal")
            self.assertEqual(result.calculation_method, "anisotropic_gruneisen_v2")
            self.assertAlmostEqual(result.alpha_300k_ppm_per_k, 6.0)
            self.assertEqual(result.crystal_system, "tetragonal")
            self.assertEqual(len(result.thermal_expansion_directional_curve), 2)

    def test_accepts_unavailable_directional_anisotropy_factor(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "gruneisen_aniso_1M_v2"
            root.mkdir()
            (root / "thermal_expansion_cartesian.dat").write_text(
                "# T_K alpha_xx alpha_yy alpha_zz alpha_yz_eng alpha_xz_eng alpha_xy_eng alpha_volume\n"
                "100 0 0 0 0 0 0 0\n300 0 0 0 0 0 0 0\n",
                encoding="utf-8",
            )
            (root / "thermal_expansion_directional.dat").write_text(
                "# T_K alpha_a alpha_b alpha_c alpha_volume F_ani\n"
                "100 0 0 0 0 nan\n300 0 0 0 0 nan\n",
                encoding="utf-8",
            )
            result = parse_anisotropic_results(directory)
            self.assertIsNone(result.thermal_expansion_directional_curve[0]["F_ani"])
            self.assertIn("anisotropy factor is unavailable", result.quality_warnings[0])


if __name__ == "__main__":
    unittest.main()
