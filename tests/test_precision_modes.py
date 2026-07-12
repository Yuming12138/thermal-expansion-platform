import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from te_platform.jobs.precision_runner import _parse_completed_result
from te_platform.workers.mattersim_runner import MatterSimPrediction


class PrecisionModeTests(unittest.TestCase):
    @patch("te_platform.jobs.precision_runner.predict_mattersim_descriptors")
    def test_elastic_mode_combines_tensor_bonding_and_sbr(self, mattersim_mock) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            elastic = root / "elastic"
            elastic.mkdir()
            (root / "POSCAR").write_text("test", encoding="utf-8")
            (elastic / "ELASTIC_TENSOR").write_text(
                "\n".join(" ".join("100" if row == column else "0" for column in range(6)) for row in range(6)),
                encoding="utf-8",
            )
            mattersim_mock.return_value = MatterSimPrediction(
                descriptors={
                    "cohesive_energy_ev_per_atom": -5.0,
                    "cell_volume_a3": 100.0,
                    "atom_count": 10,
                    "average_coordination_number": 4.0,
                },
                worker_seconds=1.0,
            )

            result = _parse_completed_result(root, "elastic")

            self.assertEqual(result["calculation_mode"], "elastic")
            self.assertEqual(len(result["elastic_tensor_gpa"]), 6)
            self.assertAlmostEqual(result["bonding"]["bonding_modulus_gpa"], 20.02720776)
            self.assertAlmostEqual(result["sbr"]["shear_modulus_gpa"], 75.7142857143)


if __name__ == "__main__":
    unittest.main()
