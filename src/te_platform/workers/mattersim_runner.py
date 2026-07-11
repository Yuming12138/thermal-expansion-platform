from __future__ import annotations

import json
import os
import subprocess
import time
from dataclasses import asdict, dataclass
from pathlib import Path


DEFAULT_MATTERSIM_PYTHON = Path(r"D:\1.Program\1.Anaconda\envs\mattersim\python.exe")
DEFAULT_MATTERSIM_MODEL = "mattersim-v1.0.0-5M"
RESULT_PREFIX = "TEP_MATTERSIM_RESULT="
WORKER_SCRIPT = Path(__file__).with_name("mattersim_worker.py")


@dataclass(frozen=True)
class MatterSimPrediction:
    descriptors: dict[str, object]
    worker_seconds: float

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def predict_mattersim_descriptors(
    structure_path: str | Path,
    *,
    timeout_seconds: float = 90.0,
) -> MatterSimPrediction:
    python = Path(os.environ.get("TEP_MATTERSIM_PYTHON", DEFAULT_MATTERSIM_PYTHON))
    model = os.environ.get("TEP_MATTERSIM_MODEL", DEFAULT_MATTERSIM_MODEL)
    if not python.is_file():
        raise RuntimeError(f"Missing MatterSim Python executable: {python}")
    started = time.perf_counter()
    try:
        completed = subprocess.run(
            [str(python), str(WORKER_SCRIPT), "--structure", str(Path(structure_path).resolve()), "--model", model],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            check=False,
            env={**os.environ, "PYTHONUTF8": "1"},
        )
    except subprocess.TimeoutExpired as error:
        raise RuntimeError(f"MatterSim worker timed out after {timeout_seconds:.0f} seconds") from error
    if completed.returncode != 0:
        raise RuntimeError(f"MatterSim worker failed: {(completed.stderr.strip() or completed.stdout.strip())[-1200:]}")
    for line in reversed(completed.stdout.splitlines()):
        if line.startswith(RESULT_PREFIX):
            return MatterSimPrediction(
                descriptors=json.loads(line.removeprefix(RESULT_PREFIX)),
                worker_seconds=time.perf_counter() - started,
            )
    raise RuntimeError("MatterSim worker returned no machine-readable result")
