from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from te_platform.db.schema import connect_database, initialize_database
from te_platform.jobs.states import JobStatus, validate_transition


ALLOWED_WORKFLOWS = frozenset(
    {
        "fast_structure_screening",
        "precision_elastic_qha",
        "precision_elastic",
        "precision_qha",
    }
)


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


def _persist_thermal_expansion_curve(connection: Any, job_id: str, result: dict[str, Any]) -> None:
    """Store a complete QHA alpha(T) sequence independently of summary values."""
    curve = result.get("thermal_expansion_curve")
    if not isinstance(curve, list | tuple) or len(curve) < 2:
        return
    points: list[list[float]] = []
    for point in curve:
        if not isinstance(point, list | tuple) or len(point) < 2:
            return
        try:
            temperature, alpha = float(point[0]), float(point[1])
        except (TypeError, ValueError):
            return
        points.append([temperature, alpha])
    connection.execute(
        """INSERT INTO precision_thermal_expansion_curves
        (job_id, points_json, unit, source_path, parsed_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(job_id) DO UPDATE SET
            points_json = excluded.points_json,
            unit = excluded.unit,
            source_path = excluded.source_path,
            parsed_at = excluded.parsed_at""",
        (
            job_id,
            json.dumps(points, ensure_ascii=False, separators=(",", ":")),
            "1/K",
            result.get("thermal_expansion_source_path"),
            _timestamp(),
        ),
    )


def import_historical_thermal_expansion_curve(
    connection: Any,
    *,
    material_id: int,
    source_path: str,
    thermal_expansion_curve: tuple[tuple[float, float], ...],
    alpha_300k_per_k: float | None,
) -> str:
    """Idempotently register a pre-existing QHA curve in an open database transaction."""
    job_id = str(uuid.uuid5(uuid.NAMESPACE_URL, Path(source_path).resolve().as_uri()))
    now = _timestamp()
    result = {
        "alpha_300k_per_k": alpha_300k_per_k,
        "alpha_300k_ppm_per_k": alpha_300k_per_k * 1_000_000
        if alpha_300k_per_k is not None
        else None,
        "quality_warnings": [],
        "thermal_expansion_source_path": source_path,
    }
    connection.execute(
        """INSERT INTO calculation_jobs
        (id, material_id, workflow, model_name, status, parameters_json, result_json,
         error_message, created_at, updated_at)
        VALUES (?, ?, ?, ?, 'SUCCEEDED', ?, ?, NULL, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            material_id = excluded.material_id,
            result_json = excluded.result_json,
            updated_at = excluded.updated_at""",
        (
            job_id,
            material_id,
            "historical_qha_thermal_expansion",
            "historical-qha-import",
            json.dumps({"source_path": source_path}, ensure_ascii=False, sort_keys=True),
            json.dumps(result, ensure_ascii=False, sort_keys=True),
            now,
            now,
        ),
    )
    _persist_thermal_expansion_curve(
        connection,
        job_id,
        {
            **result,
            "thermal_expansion_curve": thermal_expansion_curve,
        },
    )
    return job_id


def associate_job_with_material(
    database: str | Path, job_id: str, material_key: str
) -> dict[str, Any]:
    """Associate an existing calculation with one catalogued material by its stable key."""
    initialize_database(database)
    with connect_database(database) as connection:
        material = connection.execute(
            "SELECT id FROM materials WHERE material_key = ?", (material_key,)
        ).fetchone()
        if material is None:
            raise ValueError(f"Unknown material key: {material_key}")
        updated = connection.execute(
            "UPDATE calculation_jobs SET material_id = ?, updated_at = ? WHERE id = ?",
            (material["id"], _timestamp(), job_id),
        )
        if updated.rowcount != 1:
            raise ValueError(f"Unknown calculation job: {job_id}")
    return get_job(database, job_id)


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
        if target is JobStatus.SUCCEEDED and result is not None:
            _persist_thermal_expansion_curve(connection, job_id, result)
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
        _persist_thermal_expansion_curve(connection, job_id, result)
    return get_job(database, job_id)
