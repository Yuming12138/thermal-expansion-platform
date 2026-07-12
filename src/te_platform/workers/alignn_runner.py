from __future__ import annotations

import json
import subprocess
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from te_platform.config import compute_setting

RESULT_PREFIX = "TEP_ALIGNN_RESULT="
WORKER_SCRIPT = Path(__file__).with_name("alignn_worker.py")


@dataclass(frozen=True)
class AlignnWorkerConfiguration:
    python_executable: Path | None
    source_root: Path | None
    model_dir: Path | None

    @classmethod
    def from_environment(cls) -> "AlignnWorkerConfiguration":
        return cls(
            python_executable=_optional_path(compute_setting("TEP_ALIGNN_PYTHON")),
            source_root=_optional_path(compute_setting("TEP_ALIGNN_SOURCE")),
            model_dir=_optional_path(compute_setting("TEP_ALIGNN_MODEL_DIR")),
        )

    def issues(self) -> tuple[str, ...]:
        issues = []
        checks = (
            (self.python_executable, "TEP_ALIGNN_PYTHON", "ALIGNN Python executable"),
            (self.source_root, "TEP_ALIGNN_SOURCE", "ALIGNN source directory"),
            (self.model_dir, "TEP_ALIGNN_MODEL_DIR", "ALIGNN model directory"),
        )
        for path, setting, label in checks:
            if path is None:
                issues.append(f"Not configured: {setting}")
            elif not path.exists():
                issues.append(f"Missing {label}: {path}")
        if self.model_dir is not None and not (self.model_dir / "config.json").is_file():
            issues.append(f"Missing ALIGNN model configuration: {self.model_dir / 'config.json'}")
        return tuple(issues)


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
    assert config.python_executable is not None
    assert config.source_root is not None
    assert config.model_dir is not None
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
    import os

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


def _optional_path(value: str | None) -> Path | None:
    return Path(value).expanduser() if value else None
