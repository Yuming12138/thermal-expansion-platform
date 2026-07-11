import tempfile
import unittest
from pathlib import Path

from te_platform.jobs.precision_runner import precision_progress


class PrecisionProgressTests(unittest.TestCase):
    def test_reads_latest_qha_displacement_progress(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            database = Path(temp) / "jobs.db"
            work = database.parent / "runs" / "job-1"
            work.mkdir(parents=True)
            (work / "qha_calc.log").write_text(
                "  1%| | 2/192 [00:05<08:00, 2.5s/it]\n"
                " 21%| | 41/192 [01:31<05:33, 2.2s/it]\n",
                encoding="utf-8",
            )

            progress = precision_progress(database, "job-1")

            self.assertEqual(progress["stage"], "qha_force_constants")
            self.assertEqual(progress["completed_displacements"], 41)
            self.assertEqual(progress["total_displacements"], 192)
            self.assertAlmostEqual(progress["percent"], 21.4)


if __name__ == "__main__":
    unittest.main()
