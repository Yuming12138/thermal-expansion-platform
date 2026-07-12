from __future__ import annotations

import json
import os
import re
import sqlite3
from contextlib import closing
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path, PureWindowsPath
from typing import Any
from urllib.parse import quote


HISTORICAL_CURVE_WORKFLOW = "historical_qha_thermal_expansion"
WINDOWS_ABSOLUTE_PATH = re.compile(r"^[A-Za-z]:[\\/]")


@dataclass(frozen=True)
class ReleaseCatalogSummary:
    database_path: str
    manifest_path: str
    sha256: str
    file_bytes: int
    releases: int
    materials: int
    structures: int
    property_values: int
    curves: int
    removed_development_jobs: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _logical_source_path(release_slug: str, material_key: str) -> str:
    return f"catalog://{quote(release_slug, safe='')}/{quote(material_key, safe='')}/thermal_expansion.dat"


def _sanitize_manifest_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _sanitize_manifest_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_sanitize_manifest_value(item) for item in value]
    if isinstance(value, str) and (WINDOWS_ABSOLUTE_PATH.match(value) or value.startswith("/")):
        name = PureWindowsPath(value).name or "source"
        return f"source://{quote(name, safe='._-')}"
    return value


def _assert_no_absolute_paths(connection: sqlite3.Connection) -> None:
    candidates = [
        ("dataset_releases", "manifest_json"),
        ("calculation_jobs", "parameters_json"),
        ("calculation_jobs", "result_json"),
        ("calculation_jobs", "error_message"),
        ("precision_thermal_expansion_curves", "source_path"),
    ]
    for table, column in candidates:
        rows = connection.execute(f"SELECT {column} FROM {table} WHERE {column} IS NOT NULL")
        for row in rows:
            value = str(row[0])
            if re.search(r"(?<![A-Za-z0-9+.-])[A-Za-z]:[\\/]", value):
                raise ValueError(f"Release catalog still contains a Windows absolute path in {table}.{column}")


def build_release_catalog(
    source_database: str | Path,
    output_database: str | Path,
    *,
    replace: bool = False,
) -> ReleaseCatalogSummary:
    source = Path(source_database).resolve()
    output = Path(output_database).resolve()
    if not source.is_file():
        raise ValueError(f"Source database does not exist: {source}")
    if source == output:
        raise ValueError("Release catalog output must differ from the development database")
    if output.exists() and not replace:
        raise ValueError(f"Release catalog already exists: {output}; use --replace")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".building")
    if temporary.exists():
        temporary.unlink()

    removed_development_jobs = 0
    try:
        with closing(sqlite3.connect(source)) as source_connection, closing(
            sqlite3.connect(temporary)
        ) as target:
            source_connection.backup(target)
            target.row_factory = sqlite3.Row
            target.execute("PRAGMA foreign_keys = ON")

            removed_development_jobs = target.execute(
                "SELECT COUNT(*) FROM calculation_jobs WHERE workflow != ?",
                (HISTORICAL_CURVE_WORKFLOW,),
            ).fetchone()[0]
            target.execute("DELETE FROM composite_designs")
            target.execute(
                "DELETE FROM calculation_jobs WHERE workflow != ?",
                (HISTORICAL_CURVE_WORKFLOW,),
            )

            releases = target.execute("SELECT id, manifest_json FROM dataset_releases").fetchall()
            for release in releases:
                manifest = json.loads(release["manifest_json"])
                target.execute(
                    "UPDATE dataset_releases SET manifest_json=? WHERE id=?",
                    (
                        json.dumps(
                            _sanitize_manifest_value(manifest),
                            ensure_ascii=False,
                            sort_keys=True,
                            separators=(",", ":"),
                        ),
                        release["id"],
                    ),
                )

            jobs = target.execute(
                """SELECT j.id, j.parameters_json, j.result_json,
                          m.material_key, dr.slug AS release_slug
                FROM calculation_jobs j
                JOIN materials m ON m.id = j.material_id
                JOIN dataset_memberships dm ON dm.material_id = m.id
                JOIN dataset_releases dr ON dr.id = dm.dataset_release_id
                WHERE j.workflow = ?""",
                (HISTORICAL_CURVE_WORKFLOW,),
            ).fetchall()
            for job in jobs:
                logical_path = _logical_source_path(job["release_slug"], job["material_key"])
                parameters = json.loads(job["parameters_json"] or "{}")
                result = json.loads(job["result_json"] or "{}")
                parameters["source_path"] = logical_path
                if "thermal_expansion_source_path" in result:
                    result["thermal_expansion_source_path"] = logical_path
                target.execute(
                    """UPDATE calculation_jobs
                    SET parameters_json=?, result_json=?, error_message=NULL
                    WHERE id=?""",
                    (
                        json.dumps(parameters, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
                        json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
                        job["id"],
                    ),
                )
                target.execute(
                    "UPDATE precision_thermal_expansion_curves SET source_path=? WHERE job_id=?",
                    (logical_path, job["id"]),
                )

            built_at = datetime.now(UTC).isoformat()
            metadata = {
                "catalog_version": "1",
                "catalog_built_at": built_at,
                "catalog_scope": "read-only materials, structures, properties, quality flags, and historical QHA curves",
            }
            target.executemany(
                "INSERT OR REPLACE INTO schema_metadata(key,value) VALUES (?,?)",
                metadata.items(),
            )
            _assert_no_absolute_paths(target)
            if target.execute("PRAGMA foreign_key_check").fetchall():
                raise ValueError("Release catalog contains foreign-key violations")
            integrity = target.execute("PRAGMA integrity_check").fetchone()[0]
            if integrity != "ok":
                raise ValueError(f"Release catalog integrity check failed: {integrity}")
            target.commit()
            target.execute("PRAGMA journal_mode = DELETE")
            target.execute("VACUUM")

        os.replace(temporary, output)
    finally:
        if temporary.exists():
            temporary.unlink()

    with closing(sqlite3.connect(output)) as connection:
        counts = {
            "releases": connection.execute("SELECT COUNT(*) FROM dataset_releases").fetchone()[0],
            "materials": connection.execute("SELECT COUNT(*) FROM materials").fetchone()[0],
            "structures": connection.execute("SELECT COUNT(*) FROM structures").fetchone()[0],
            "property_values": connection.execute("SELECT COUNT(*) FROM material_properties").fetchone()[0],
            "curves": connection.execute(
                "SELECT COUNT(*) FROM precision_thermal_expansion_curves"
            ).fetchone()[0],
        }
    database_sha256 = _sha256_file(output)
    manifest_path = output.with_suffix(output.suffix + ".manifest.json")
    manifest = {
        "catalog_version": "1",
        "database_file": output.name,
        "database_sha256": database_sha256,
        "file_bytes": output.stat().st_size,
        "counts": counts,
        "removed_development_jobs": removed_development_jobs,
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return ReleaseCatalogSummary(
        database_path=str(output),
        manifest_path=str(manifest_path),
        sha256=database_sha256,
        file_bytes=output.stat().st_size,
        removed_development_jobs=removed_development_jobs,
        **counts,
    )
