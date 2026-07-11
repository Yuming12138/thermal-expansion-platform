from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from te_platform.db.schema import connect_database, initialize_database
from te_platform.jobs.states import JobStatus, validate_transition


ALLOWED_WORKFLOWS = frozenset({"precision_elastic_qha"})


def _timestamp() -> str:
    return datetime.now(UTC).isoformat()


def create_job(
    database: str | Path,
    *,
    workflow: str,
    parameters: dict[str, Any],
    model_name: str = "mattersim-v1.0.0-5M",
) -> dict[str, Any]:
    if workflow not in ALLOWED_WORKFLOWS:
        raise ValueError(f"Workflow is not allowlisted: {workflow}")
    initialize_database(database)
    job = {
        "id": str(uuid.uuid4()),
        "workflow": workflow,
        "model_name": model_name,
        "status": JobStatus.PENDING.value,
        "parameters_json": json.dumps(parameters, ensure_ascii=False, sort_keys=True),
        "created_at": _timestamp(),
        "updated_at": _timestamp(),
    }
    with connect_database(database) as connection:
        connection.execute(
            """INSERT INTO calculation_jobs
            (id, workflow, model_name, status, parameters_json, created_at, updated_at)
            VALUES (:id, :workflow, :model_name, :status, :parameters_json, :created_at, :updated_at)""",
            job,
        )
    return get_job(database, job["id"])


def get_job(database: str | Path, job_id: str) -> dict[str, Any]:
    with connect_database(database) as connection:
        row = connection.execute("SELECT * FROM calculation_jobs WHERE id = ?", (job_id,)).fetchone()
    if row is None:
        raise ValueError(f"Unknown calculation job: {job_id}")
    result = dict(row)
    result["parameters"] = json.loads(result.pop("parameters_json"))
    result["result"] = json.loads(result["result_json"]) if result["result_json"] else None
    result.pop("result_json")
    return result


def transition_job(
    database: str | Path,
    job_id: str,
    target: JobStatus,
    *,
    result: dict[str, Any] | None = None,
    error_message: str | None = None,
) -> dict[str, Any]:
    current = JobStatus(get_job(database, job_id)["status"])
    validate_transition(current, target)
    with connect_database(database) as connection:
        connection.execute(
            """UPDATE calculation_jobs
            SET status = ?, result_json = ?, error_message = ?, updated_at = ?
            WHERE id = ?""",
            (
                target.value,
                json.dumps(result, ensure_ascii=False, sort_keys=True) if result else None,
                error_message,
                _timestamp(),
                job_id,
            ),
        )
    return get_job(database, job_id)


def replace_completed_job_result(
    database: str | Path, job_id: str, result: dict[str, Any]
) -> dict[str, Any]:
    """Replace parsed output for a completed task without changing its terminal state."""
    current = get_job(database, job_id)
    if JobStatus(current["status"]) is not JobStatus.SUCCEEDED:
        raise ValueError("Only a succeeded task can have its parsed result refreshed")
    with connect_database(database) as connection:
        connection.execute(
            """UPDATE calculation_jobs
            SET result_json = ?, updated_at = ?
            WHERE id = ?""",
            (json.dumps(result, ensure_ascii=False, sort_keys=True), _timestamp(), job_id),
        )
    return get_job(database, job_id)
