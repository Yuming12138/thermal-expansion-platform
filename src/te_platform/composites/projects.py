from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from te_platform.db.schema import connect_database


PROJECT_MODEL_NAME = "zte_screening_project"


def _now() -> str:
    return datetime.now(UTC).isoformat()


def save_screening_project(
    database: str | Path,
    *,
    project_name: str,
    screening_parameters: dict[str, Any],
    screening_result: dict[str, Any],
    selected_pairs: list[dict[str, Any]],
) -> dict[str, Any]:
    project_id = str(uuid4())
    created_at = _now()
    parameters = {
        "project_name": project_name.strip(),
        "screening_parameters": screening_parameters,
    }
    result = {
        "screening_result": screening_result,
        "selected_pairs": selected_pairs,
    }
    with connect_database(database) as connection:
        connection.execute(
            """INSERT INTO composite_designs
            (id,pte_material_id,nte_material_id,model_name,parameters_json,result_json,created_at)
            VALUES (?,NULL,NULL,?,?,?,?)""",
            (
                project_id,
                PROJECT_MODEL_NAME,
                json.dumps(parameters, ensure_ascii=False, separators=(",", ":")),
                json.dumps(result, ensure_ascii=False, separators=(",", ":")),
                created_at,
            ),
        )
    return {
        "id": project_id,
        "project_name": parameters["project_name"],
        "created_at": created_at,
        "result_count": len(screening_result.get("results") or []),
        "selected_pair_count": len(selected_pairs),
    }


def list_screening_projects(database: str | Path) -> list[dict[str, Any]]:
    with connect_database(database) as connection:
        rows = connection.execute(
            """SELECT id,parameters_json,result_json,created_at
            FROM composite_designs WHERE model_name=?
            ORDER BY created_at DESC""",
            (PROJECT_MODEL_NAME,),
        ).fetchall()
    projects = []
    for row in rows:
        parameters = json.loads(row["parameters_json"])
        result = json.loads(row["result_json"])
        screening_result = result.get("screening_result") or {}
        projects.append(
            {
                "id": row["id"],
                "project_name": parameters.get("project_name") or "未命名筛选项目",
                "created_at": row["created_at"],
                "model": (parameters.get("screening_parameters") or {}).get("model"),
                "result_count": len(screening_result.get("results") or []),
                "selected_pair_count": len(result.get("selected_pairs") or []),
            }
        )
    return projects


def get_screening_project(database: str | Path, project_id: str) -> dict[str, Any]:
    with connect_database(database) as connection:
        row = connection.execute(
            """SELECT id,parameters_json,result_json,created_at
            FROM composite_designs WHERE id=? AND model_name=?""",
            (project_id, PROJECT_MODEL_NAME),
        ).fetchone()
    if row is None:
        raise ValueError(f"ZTE screening project not found: {project_id}")
    parameters = json.loads(row["parameters_json"])
    result = json.loads(row["result_json"])
    return {
        "id": row["id"],
        "project_name": parameters.get("project_name") or "未命名筛选项目",
        "created_at": row["created_at"],
        "screening_parameters": parameters.get("screening_parameters") or {},
        "screening_result": result.get("screening_result") or {},
        "selected_pairs": result.get("selected_pairs") or [],
    }


def delete_screening_project(database: str | Path, project_id: str) -> bool:
    with connect_database(database) as connection:
        cursor = connection.execute(
            "DELETE FROM composite_designs WHERE id=? AND model_name=?",
            (project_id, PROJECT_MODEL_NAME),
        )
    return cursor.rowcount > 0
