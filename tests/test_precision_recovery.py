import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from te_platform.jobs.precision_runner import PrecisionTaskConfig, resume_precision_qha
from te_platform.jobs.repository import create_job


class PrecisionRecoveryTests(unittest.TestCase):
    def test_resumes_a_qha_child_from_its_elastic_ancestor(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            database = Path(temp) / "jobs.db"
            config = PrecisionTaskConfig().__dict__
            original = create_job(
                database, workflow="precision_elastic_qha", parameters={"config": config}
            )
            original_work = database.parent / "runs" / original["id"]
            (original_work / "elastic").mkdir(parents=True)
            (original_work / "POSCAR").write_text("original-poscar", encoding="utf-8")
            (original_work / "elastic" / "ELASTIC_TENSOR").write_text("tensor", encoding="utf-8")
            child = create_job(
                database,
                workflow="precision_elastic_qha",
                parameters={"config": config, "parent_job_id": original["id"], "mode": "thermal_only"},
            )
            child_work = database.parent / "runs" / child["id"]
            child_work.mkdir(parents=True)
            (child_work / "POSCAR").write_text("child-poscar", encoding="utf-8")

            with patch("te_platform.jobs.precision_runner.prepare_precision_task"), patch(
                "te_platform.jobs.precision_runner.threading.Thread"
            ) as thread:
                recovered = resume_precision_qha(database, child["id"])

            self.assertEqual(recovered["parameters"]["parent_job_id"], child["id"])
            self.assertEqual(recovered["parameters"]["elastic_source_job_id"], original["id"])
            recovered_work = database.parent / "runs" / recovered["id"]
            self.assertEqual((recovered_work / "POSCAR").read_text(encoding="utf-8"), "child-poscar")
            self.assertEqual(
                (recovered_work / "elastic" / "ELASTIC_TENSOR").read_text(encoding="utf-8"), "tensor"
            )
            thread.return_value.start.assert_called_once()


if __name__ == "__main__":
    unittest.main()
