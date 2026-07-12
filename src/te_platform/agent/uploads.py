from __future__ import annotations

import re
from hashlib import sha256
from pathlib import Path
from typing import Any

from te_platform.api.structures import inspect_structure


STRUCTURE_ID_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def store_agent_structure(
    workspace_database: str | Path,
    *,
    filename: str,
    content: bytes,
) -> dict[str, Any]:
    inspection = inspect_structure(filename, content)
    structure_id = sha256(content).hexdigest()
    suffix = Path(filename).suffix.lower() or ".vasp"
    upload_directory = Path(workspace_database).parent / "uploads"
    upload_directory.mkdir(parents=True, exist_ok=True)
    existing = sorted(
        path for path in upload_directory.glob(f"{structure_id}.*") if path.is_file()
    )
    path = existing[0] if existing else upload_directory / f"{structure_id}{suffix}"
    if not existing:
        path.write_bytes(content)
    return {
        "structure_id": structure_id,
        "filename": filename,
        "bytes": len(content),
        "inspection": inspection.to_dict(),
    }


def find_agent_structure(
    workspace_database: str | Path,
    structure_id: str,
) -> Path:
    if not STRUCTURE_ID_PATTERN.fullmatch(structure_id):
        raise ValueError("Invalid structure_id")
    upload_directory = Path(workspace_database).parent / "uploads"
    matches = [
        path
        for path in upload_directory.glob(f"{structure_id}.*")
        if path.is_file()
    ]
    if not matches:
        raise ValueError(f"Uploaded structure is unavailable: {structure_id}")
    return sorted(matches)[0]


def inspect_agent_structure(
    workspace_database: str | Path,
    structure_id: str,
) -> dict[str, Any]:
    path = find_agent_structure(workspace_database, structure_id)
    content = path.read_bytes()
    return {
        "structure_id": structure_id,
        "stored_filename": path.name,
        "bytes": len(content),
        "inspection": inspect_structure(path.name, content).to_dict(),
    }
