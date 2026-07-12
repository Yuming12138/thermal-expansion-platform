from __future__ import annotations

import os
import subprocess
from pathlib import Path

from te_platform.workers.mattersim_runner import DEFAULT_MATTERSIM_PYTHON


WORKER_SCRIPT = Path(__file__).with_name("structure_convert_worker.py")


def write_precision_poscar(
    work_directory: str | Path,
    *,
    filename: str,
    content: bytes,
    timeout_seconds: float = 30.0,
) -> Path:
    work = Path(work_directory)
    work.mkdir(parents=True, exist_ok=True)
    lower_name = filename.lower()
    is_cif = lower_name.endswith(".cif") or b"_cell_length_a" in content
    poscar = work / "POSCAR"
    if not is_cif:
        poscar.write_bytes(content)
        return poscar

    source = work / "input.cif"
    source.write_bytes(content)
    python = Path(os.environ.get("TEP_MATTERSIM_PYTHON", DEFAULT_MATTERSIM_PYTHON))
    if not python.is_file():
        raise RuntimeError(f"Missing MatterSim Python executable: {python}")
    try:
        completed = subprocess.run(
            [str(python), str(WORKER_SCRIPT), "--input", str(source), "--output", str(poscar)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            check=False,
            env={**os.environ, "PYTHONUTF8": "1"},
        )
    except subprocess.TimeoutExpired as error:
        raise RuntimeError("CIF to POSCAR conversion timed out") from error
    if completed.returncode != 0 or not poscar.is_file():
        message = completed.stderr.strip() or completed.stdout.strip() or "unknown conversion error"
        raise RuntimeError(f"CIF to POSCAR conversion failed: {message[-1200:]}")
    return poscar
