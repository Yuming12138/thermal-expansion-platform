from __future__ import annotations

import json
import math
import re
import sqlite3
from pathlib import Path
from time import monotonic
from typing import Any

from te_platform.db.schema import connect_readonly_database


CATALOG_TABLES = (
    "schema_metadata",
    "dataset_releases",
    "materials",
    "dataset_memberships",
    "structures",
    "material_properties",
    "data_quality_flags",
    "calculation_jobs",
    "precision_thermal_expansion_curves",
    "composite_designs",
)

TABLE_NOTES = {
    "dataset_releases": "数据集版本、记录数、源文件和校验信息。",
    "materials": "材料主表；material_key是平台稳定标识，formula为化学式。",
    "dataset_memberships": "材料与NTE/PTE数据版本的归属关系。",
    "structures": "已保存的POSCAR/CIF等结构文本；content可能很长。",
    "material_properties": (
        "长表形式的材料属性。常用name包括G_GPa、E_tilde_GPa、CTE_ppm、"
        "E_coh_eV_per_atom、avg_cn和K_GPa。"
    ),
    "data_quality_flags": "材料数据质量问题及严重程度。",
    "calculation_jobs": "已导入或已提交计算任务的工作流、模型、状态和结果摘要。",
    "precision_thermal_expansion_curves": (
        "真实QHA热膨胀曲线。points_json为[[temperature_K, alpha_1_per_K], ...]。"
    ),
    "composite_designs": "已保存的PTE/NTE复合设计结果。",
}

_DENIED_FUNCTIONS = frozenset(
    {
        "load_extension",
        "readfile",
        "writefile",
        "fts3_tokenizer",
        "randomblob",
        "zeroblob",
    }
)
_ALLOWED_AUTHOR_ACTIONS = frozenset(
    {
        sqlite3.SQLITE_SELECT,
        sqlite3.SQLITE_READ,
        sqlite3.SQLITE_FUNCTION,
        getattr(sqlite3, "SQLITE_RECURSIVE", 33),
    }
)


def _curve_points(points_json: str) -> list[tuple[float, float]]:
    raw_points = json.loads(points_json)
    points: list[tuple[float, float]] = []
    for point in raw_points:
        if isinstance(point, dict):
            temperature = point.get("temperature_k")
            alpha = point.get("alpha_1_per_k", point.get("alpha"))
        else:
            temperature, alpha = point[0], point[1]
        temperature_value = float(temperature)
        alpha_value = float(alpha)
        if math.isfinite(temperature_value) and math.isfinite(alpha_value):
            points.append((temperature_value, alpha_value))
    points.sort(key=lambda item: item[0])
    return points


def alpha_at_temperature(points_json: str | None, temperature_k: float) -> float | None:
    """Linearly interpolate a stored alpha(T) curve and return alpha in 1/K."""

    if not points_json:
        return None
    points = _curve_points(points_json)
    target = float(temperature_k)
    if len(points) < 2 or target < points[0][0] or target > points[-1][0]:
        return None
    for left, right in zip(points, points[1:]):
        left_t, left_alpha = left
        right_t, right_alpha = right
        if left_t <= target <= right_t:
            if target == left_t:
                return left_alpha
            if right_t == left_t:
                return right_alpha
            fraction = (target - left_t) / (right_t - left_t)
            return left_alpha + fraction * (right_alpha - left_alpha)
    return points[-1][1] if target == points[-1][0] else None


def describe_catalog_database(database: str | Path) -> dict[str, Any]:
    tables: list[dict[str, Any]] = []
    with connect_readonly_database(database) as connection:
        existing = {
            row["name"]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        for table_name in CATALOG_TABLES:
            if table_name not in existing:
                continue
            columns = [
                {
                    "name": row["name"],
                    "type": row["type"] or "",
                    "nullable": not bool(row["notnull"]),
                    "primary_key": bool(row["pk"]),
                }
                for row in connection.execute(f'PRAGMA table_info("{table_name}")').fetchall()
            ]
            foreign_keys = [
                {
                    "column": row["from"],
                    "references_table": row["table"],
                    "references_column": row["to"],
                }
                for row in connection.execute(
                    f'PRAGMA foreign_key_list("{table_name}")'
                ).fetchall()
            ]
            tables.append(
                {
                    "name": table_name,
                    "description": TABLE_NOTES.get(table_name, "平台内部数据表。"),
                    "columns": columns,
                    "foreign_keys": foreign_keys,
                }
            )
    return {
        "database": "catalog",
        "access": "read_only",
        "tables": tables,
        "sql_functions": [
            {
                "name": "alpha_at_temperature(points_json, temperature_k)",
                "returns": "线性插值得到的体热膨胀系数，单位1/K；超出曲线温区返回NULL。",
            }
        ],
        "units": {
            "precision_thermal_expansion_curves.points_json alpha": "1/K",
            "material_properties.CTE_ppm": "ppm/K",
            "G_GPa/E_tilde_GPa/K_GPa": "GPa",
        },
        "query_rules": [
            "只允许单条SELECT、WITH或EXPLAIN查询。",
            "全库排名必须报告参与查询、具有曲线和覆盖目标温度的材料数量。",
            "使用alpha_at_temperature后乘以1e6可转换为ppm/K。",
            "不要直接返回大量structures.content或完整points_json；应在SQL内聚合、筛选和排序。",
        ],
    }


def _leading_keyword(sql: str) -> str:
    remaining = sql
    while True:
        stripped = remaining.lstrip()
        if stripped.startswith("--"):
            newline = stripped.find("\n")
            remaining = "" if newline < 0 else stripped[newline + 1 :]
            continue
        if stripped.startswith("/*"):
            end = stripped.find("*/", 2)
            if end < 0:
                raise ValueError("SQL contains an unterminated comment")
            remaining = stripped[end + 2 :]
            continue
        match = re.match(r"([A-Za-z]+)", stripped)
        return match.group(1).upper() if match else ""


def _safe_cell(value: Any, *, max_characters: int = 8_000) -> tuple[Any, bool]:
    if value is None or isinstance(value, (int, float)):
        return value, False
    if isinstance(value, bytes):
        return {"binary_bytes": len(value)}, True
    text = str(value)
    if len(text) <= max_characters:
        return text, False
    return text[:max_characters] + "…[truncated]", True


def execute_catalog_sql(
    database: str | Path,
    sql: str,
    parameters: dict[str, str | int | float | None] | None = None,
    max_rows: int = 100,
    timeout_ms: int = 2_000,
) -> dict[str, Any]:
    if not isinstance(sql, str) or not sql.strip():
        raise ValueError("sql must be a non-empty string")
    if len(sql) > 20_000:
        raise ValueError("SQL exceeds the 20000 character limit")
    if _leading_keyword(sql) not in {"SELECT", "WITH", "EXPLAIN"}:
        raise ValueError("Only SELECT, WITH, or EXPLAIN queries are allowed")
    row_limit = max(1, min(int(max_rows), 500))
    timeout = max(100, min(int(timeout_ms), 5_000))
    bound_parameters = parameters or {}
    if not isinstance(bound_parameters, dict):
        raise ValueError("parameters must be a JSON object with named SQL parameters")

    deadline = monotonic() + timeout / 1_000
    truncated_cells = 0
    started = monotonic()
    with connect_readonly_database(database) as connection:
        connection.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, 1_000_000)
        connection.setlimit(sqlite3.SQLITE_LIMIT_COLUMN, 200)
        connection.setlimit(sqlite3.SQLITE_LIMIT_COMPOUND_SELECT, 50)
        connection.setlimit(sqlite3.SQLITE_LIMIT_EXPR_DEPTH, 100)
        connection.create_function(
            "alpha_at_temperature",
            2,
            alpha_at_temperature,
            deterministic=True,
        )

        def authorizer(
            action: int,
            argument_1: str | None,
            argument_2: str | None,
            _database_name: str | None,
            _trigger_name: str | None,
        ) -> int:
            if action not in _ALLOWED_AUTHOR_ACTIONS:
                return sqlite3.SQLITE_DENY
            if action == sqlite3.SQLITE_READ and argument_1 not in CATALOG_TABLES:
                return sqlite3.SQLITE_DENY
            if action == sqlite3.SQLITE_FUNCTION:
                function_name = str(argument_2 or argument_1 or "").lower()
                if function_name in _DENIED_FUNCTIONS:
                    return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK

        connection.set_authorizer(authorizer)
        connection.set_progress_handler(lambda: int(monotonic() > deadline), 1_000)
        try:
            cursor = connection.execute(sql, bound_parameters)
            columns = [item[0] for item in cursor.description or []]
            raw_rows = cursor.fetchmany(row_limit + 1)
        except sqlite3.DatabaseError as error:
            message = str(error)
            if "interrupted" in message.lower():
                raise ValueError(f"Read-only SQL exceeded the {timeout} ms time limit") from error
            raise ValueError(f"Read-only SQL failed: {message}") from error
        finally:
            connection.set_progress_handler(None, 0)
            connection.set_authorizer(None)

    result_rows = []
    output_characters = 0
    truncated_by_size = False
    for row in raw_rows[:row_limit]:
        result_row: dict[str, Any] = {}
        for column in columns:
            safe_value, was_truncated = _safe_cell(row[column])
            result_row[column] = safe_value
            truncated_cells += int(was_truncated)
        row_characters = len(json.dumps(result_row, ensure_ascii=False, default=str))
        if result_rows and output_characters + row_characters > 120_000:
            truncated_by_size = True
            break
        result_rows.append(result_row)
        output_characters += row_characters
    return {
        "columns": columns,
        "rows": result_rows,
        "returned_row_count": len(result_rows),
        "truncated": len(raw_rows) > row_limit or truncated_by_size,
        "truncated_by_output_size": truncated_by_size,
        "truncated_cell_count": truncated_cells,
        "max_rows": row_limit,
        "elapsed_ms": round((monotonic() - started) * 1_000, 2),
        "access": "read_only",
    }
