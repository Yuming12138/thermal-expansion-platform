from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from te_platform.db.schema import connect_database, initialize_database


PENDING_APPROVAL = "PENDING_APPROVAL"
APPROVED = "APPROVED"
EXECUTED = "EXECUTED"
REJECTED = "REJECTED"
FAILED = "FAILED"
ALLOWED_ACTIONS = frozenset(
    {"submit_qha_calculation", "submit_structure_calculation"}
)


def _timestamp() -> str:
    return datetime.now(UTC).isoformat()


def _row_to_action(row: Any) -> dict[str, Any]:
    result = dict(row)
    result["arguments"] = json.loads(result.pop("arguments_json"))
    result["result"] = json.loads(result["result_json"]) if result["result_json"] else None
    result.pop("result_json")
    return result


def create_action_request(
    database: str | Path,
    *,
    action: str,
    summary: str,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    if action not in ALLOWED_ACTIONS:
        raise ValueError(f"Agent action is not allowlisted: {action}")
    initialize_database(database)
    now = _timestamp()
    action_id = str(uuid.uuid4())
    with connect_database(database) as connection:
        connection.execute(
            """INSERT INTO agent_action_requests
            (id, action, status, summary, arguments_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                action_id,
                action,
                PENDING_APPROVAL,
                summary,
                json.dumps(arguments, ensure_ascii=False, sort_keys=True),
                now,
                now,
            ),
        )
    return get_action_request(database, action_id)


def get_action_request(database: str | Path, action_id: str) -> dict[str, Any]:
    initialize_database(database)
    with connect_database(database) as connection:
        row = connection.execute(
            "SELECT * FROM agent_action_requests WHERE id = ?", (action_id,)
        ).fetchone()
    if row is None:
        raise ValueError(f"Unknown Agent action request: {action_id}")
    return _row_to_action(row)


def list_action_requests(
    database: str | Path,
    *,
    status: str | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    initialize_database(database)
    row_limit = max(1, min(int(limit), 100))
    query = "SELECT * FROM agent_action_requests"
    parameters: tuple[Any, ...] = ()
    if status is not None:
        if status not in {PENDING_APPROVAL, APPROVED, EXECUTED, REJECTED, FAILED}:
            raise ValueError(f"Unknown Agent action status: {status}")
        query += " WHERE status = ?"
        parameters = (status,)
    query += " ORDER BY created_at DESC LIMIT ?"
    parameters += (row_limit,)
    with connect_database(database) as connection:
        rows = connection.execute(query, parameters).fetchall()
    return [_row_to_action(row) for row in rows]


def claim_action_request(database: str | Path, action_id: str) -> dict[str, Any]:
    failure_status: str | None = None
    with connect_database(database) as connection:
        updated = connection.execute(
            """UPDATE agent_action_requests
            SET status = ?, updated_at = ?
            WHERE id = ? AND status = ?""",
            (APPROVED, _timestamp(), action_id, PENDING_APPROVAL),
        )
        if updated.rowcount != 1:
            row = connection.execute(
                "SELECT status FROM agent_action_requests WHERE id = ?", (action_id,)
            ).fetchone()
            failure_status = row["status"] if row is not None else "UNKNOWN"
    if failure_status is not None:
        raise ValueError(f"Agent action cannot be approved from status {failure_status}")
    return get_action_request(database, action_id)


def complete_action_request(
    database: str | Path,
    action_id: str,
    result: dict[str, Any],
) -> dict[str, Any]:
    with connect_database(database) as connection:
        connection.execute(
            """UPDATE agent_action_requests
            SET status = ?, result_json = ?, error_message = NULL, updated_at = ?
            WHERE id = ?""",
            (EXECUTED, json.dumps(result, ensure_ascii=False, sort_keys=True), _timestamp(), action_id),
        )
    return get_action_request(database, action_id)


def fail_action_request(
    database: str | Path,
    action_id: str,
    error_message: str,
) -> dict[str, Any]:
    with connect_database(database) as connection:
        connection.execute(
            """UPDATE agent_action_requests
            SET status = ?, error_message = ?, updated_at = ? WHERE id = ?""",
            (FAILED, error_message[:1000], _timestamp(), action_id),
        )
    return get_action_request(database, action_id)


def reject_action_request(database: str | Path, action_id: str) -> dict[str, Any]:
    failure_status: str | None = None
    with connect_database(database) as connection:
        updated = connection.execute(
            """UPDATE agent_action_requests
            SET status = ?, updated_at = ?
            WHERE id = ? AND status = ?""",
            (REJECTED, _timestamp(), action_id, PENDING_APPROVAL),
        )
        if updated.rowcount != 1:
            row = connection.execute(
                "SELECT status FROM agent_action_requests WHERE id = ?", (action_id,)
            ).fetchone()
            failure_status = row["status"] if row is not None else "UNKNOWN"
    if failure_status is not None:
        raise ValueError(f"Agent action cannot be rejected from status {failure_status}")
    return get_action_request(database, action_id)
