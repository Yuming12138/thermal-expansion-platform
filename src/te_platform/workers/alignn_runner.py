from __future__ import annotations

import json
import os
import subprocess
import time
from dataclasses import asdict, dataclass
from pathlib import Path


DEFAULT_ALIGNN_PYTHON = Path(r"D:\1.Program\1.Anaconda\envs\alignn\python.exe")
DEFAULT_ALIGNN_SOURCE = Path(r"D:\9.Project\12.High_through_screening\alignn-main")
DEFAULT_ALIGNN_MODEL = Path(
    r"D:\9.Project\12.High_through_screening\jv_shear_modulus_gv_alignn"
)
RESULT_PREFIX = "TEP_ALIGNN_RESULT="
WORKER_SCRIPT = Path(__file__).with_name("alignn_worker.py")


@dataclass(frozen=True)
class AlignnWorkerConfiguration:
    python_executable: Path
    source_root: Path
    model_dir: Path

    @classmethod
    def from_environment(cls) -> "AlignnWorkerConfiguration":
        return cls(
            python_executable=Path(
                os.environ.get("TEP_ALIGNN_PYTHON", DEFAULT_ALIGNN_PYTHON)
            ),
            source_root=Path(
                os.environ.get("TEP_ALIGNN_SOURCE", DEFAULT_ALIGNN_SOURCE)
            ),
            model_dir=Path(
                os.environ.get("TEP_ALIGNN_MODEL_DIR", DEFAULT_ALIGNN_MODEL)
            ),
        )

    def issues(self) -> tuple[str, ...]:
        checks = (
            (self.python_executable, "ALIGNN Python executable"),
            (self.source_root, "ALIGNN source directory"),
            (self.model_dir / "config.json", "ALIGNN model configuration"),
        )
        return tuple(f"Missing {label}: {path}" for path, label in checks if not path.exists())


@dataclass(frozen=True)
class AlignnWorkerPrediction:
    prediction: dict[str, object]
    worker_seconds: float
    configuration: dict[str, str]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def predict_alignn_shear(
    structure_path: str | Path,
    *,
    timeout_seconds: float = 60.0,
    configuration: AlignnWorkerConfiguration | None = None,
) -> AlignnWorkerPrediction:
    config = configuration or AlignnWorkerConfiguration.from_environment()
    if issues := config.issues():
        raise RuntimeError("; ".join(issues))
    command = [
        str(config.python_executable),
        str(WORKER_SCRIPT),
        "--structure",
        str(Path(structure_path).resolve()),
        "--alignn-source",
        str(config.source_root.resolve()),
        "--model-dir",
        str(config.model_dir.resolve()),
    ]
    environment = os.environ.copy()
    environment["PYTHONUTF8"] = "1"
    started = time.perf_counter()
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            check=False,
            env=environment,
        )
    except subprocess.TimeoutExpired as error:
        raise RuntimeError(
            f"ALIGNN worker timed out after {timeout_seconds:.0f} seconds"
        ) from error
    if completed.returncode != 0:
        message = completed.stderr.strip() or completed.stdout.strip() or "unknown error"
        raise RuntimeError(f"ALIGNN worker failed: {message[-1200:]}")
    for line in reversed(completed.stdout.splitlines()):
        if line.startswith(RESULT_PREFIX):
            prediction = json.loads(line.removeprefix(RESULT_PREFIX))
            return AlignnWorkerPrediction(
                prediction=prediction,
                worker_seconds=time.perf_counter() - started,
                configuration={
                    "python_executable": str(config.python_executable),
                    "source_root": str(config.source_root),
                    "model_dir": str(config.model_dir),
                },
            )
    raise RuntimeError("ALIGNN worker returned no machine-readable result")
