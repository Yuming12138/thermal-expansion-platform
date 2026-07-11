import tempfile
import unittest
from pathlib import Path

from te_platform.precision.wsl_executor import PrecisionTaskConfig, build_precision_command


class WslExecutorTests(unittest.TestCase):
    def test_builds_fixed_command_for_prepared_task(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            work = Path(temp)
            (work / "POSCAR").write_text("test", encoding="utf-8")
            tools = work / "workflow_scripts"
            tools.mkdir()
            (tools / "complete_properties_calc.sh").write_text("#!/bin/bash", encoding="utf-8")
            command = build_precision_command(work, PrecisionTaskConfig(qha_points=11))
            self.assertEqual(command[:5], ["wsl", "-d", "Ubuntu-24.04", "--", "bash"])
            self.assertIn("--qha-n 11", command[-1])


if __name__ == "__main__":
    unittest.main()
