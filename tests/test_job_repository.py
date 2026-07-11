import tempfile
import unittest
from pathlib import Path

from te_platform.jobs.repository import create_job, get_job, replace_completed_job_result, transition_job
from te_platform.jobs.states import JobStatus


class JobRepositoryTests(unittest.TestCase):
    def test_persists_allowlisted_precision_job_and_transitions(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            database = Path(temp) / "jobs.db"
            job = create_job(
                database,
                workflow="precision_elastic_qha",
                parameters={"structure_sha256": "a" * 64, "qha_n": 11},
            )
            self.assertEqual(job["status"], "PENDING")
            queued = transition_job(database, job["id"], JobStatus.QUEUED)
            self.assertEqual(queued["status"], "QUEUED")
            transition_job(database, job["id"], JobStatus.RUNNING)
            complete = transition_job(
                database, job["id"], JobStatus.SUCCEEDED, result={"alpha_300k_ppm_per_k": 5.9}
            )
            self.assertEqual(complete["result"]["alpha_300k_ppm_per_k"], 5.9)
            self.assertEqual(get_job(database, job["id"])["status"], "SUCCEEDED")
            refreshed = replace_completed_job_result(
                database, job["id"], {"alpha_300k_ppm_per_k": 6.1, "quality_warnings": ["warning"]}
            )
            self.assertEqual(refreshed["status"], "SUCCEEDED")
            self.assertEqual(refreshed["result"]["alpha_300k_ppm_per_k"], 6.1)


if __name__ == "__main__":
    unittest.main()
