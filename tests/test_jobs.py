import unittest

from te_platform.jobs.states import JobStatus, validate_transition


class JobStateTests(unittest.TestCase):
    def test_valid_transition(self) -> None:
        validate_transition(JobStatus.PENDING, JobStatus.QUEUED)

    def test_terminal_state_cannot_restart(self) -> None:
        with self.assertRaises(ValueError):
            validate_transition(JobStatus.SUCCEEDED, JobStatus.RUNNING)


if __name__ == "__main__":
    unittest.main()
