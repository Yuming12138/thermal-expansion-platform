from __future__ import annotations

from enum import StrEnum


class JobStatus(StrEnum):
    PENDING = "PENDING"
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


ALLOWED_TRANSITIONS = {
    JobStatus.PENDING: {JobStatus.QUEUED, JobStatus.CANCELLED},
    JobStatus.QUEUED: {JobStatus.RUNNING, JobStatus.CANCELLED, JobStatus.FAILED},
    JobStatus.RUNNING: {
        JobStatus.SUCCEEDED,
        JobStatus.FAILED,
        JobStatus.CANCELLED,
    },
    JobStatus.SUCCEEDED: set(),
    JobStatus.FAILED: set(),
    JobStatus.CANCELLED: set(),
}


def validate_transition(current: JobStatus, target: JobStatus) -> None:
    if target not in ALLOWED_TRANSITIONS[current]:
        raise ValueError(f"Invalid job transition: {current} -> {target}")
