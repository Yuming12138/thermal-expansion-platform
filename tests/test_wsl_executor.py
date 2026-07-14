import os
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from te_platform.precision.wsl_executor import PrecisionTaskConfig, build_precision_command


class WslExecutorTests(unittest.TestCase):
    @unittest.skipUnless(os.name == "nt", "WSL command construction is Windows-specific")
    def test_builds_fixed_command_for_prepared_task(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            work = Path(temp)
            (work / "POSCAR").write_text("test", encoding="utf-8")
            tools = work / "workflow_scripts"
            tools.mkdir()
            (tools / "complete_properties_calc.sh").write_text("#!/bin/bash", encoding="utf-8")
            settings = {
                "TEP_WSL_DISTRO": "Ubuntu-24.04",
                "TEP_PRECISION_CONDA_INIT": "/opt/conda/etc/profile.d/conda.sh",
                "TEP_PRECISION_CONDA_ENV": "mattersim",
                "TEP_VASPKIT_BIN_DIR": "/opt/vaspkit/bin",
            }
            with patch.dict("os.environ", settings):
                command = build_precision_command(work, PrecisionTaskConfig(qha_points=11))
                elastic = build_precision_command(work, PrecisionTaskConfig(), mode="elastic")
                qha = build_precision_command(work, PrecisionTaskConfig(), mode="qha")
            self.assertEqual(command[:5], ["wsl", "-d", "Ubuntu-24.04", "--", "bash"])
            self.assertIn("--qha-n 11", command[-1])
            self.assertNotIn("--elastic-only", command[-1])
            self.assertNotIn("--thermal-only", command[-1])

            self.assertIn("--elastic-only", elastic[-1])
            self.assertIn("--thermal-only", qha[-1])


if __name__ == "__main__":
    unittest.main()
