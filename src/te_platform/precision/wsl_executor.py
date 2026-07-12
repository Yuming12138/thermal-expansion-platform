from __future__ import annotations

import shutil
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from te_platform.config import compute_setting
from te_platform.precision.script_compat import copy_compatible_qha_script


ALLOWED_QHA_POINTS = frozenset({7, 9, 11})


def windows_to_wsl(path: str | Path) -> str:
    value = str(Path(path).resolve()).replace("\\", "/")
    if len(value) < 3 or value[1:3] != ":/":
        raise ValueError(f"Expected an absolute Windows path: {path}")
    return f"/mnt/{value[0].lower()}/{value[3:]}"


@dataclass(frozen=True)
class PrecisionTaskConfig:
    qha_points: int = 11
    qha_mesh: int = 30
    qha_scale: float = 0.003
    parallel_workers: int = 1

    def validate(self) -> None:
        if self.qha_points not in ALLOWED_QHA_POINTS:
            raise ValueError(f"qha_points must be one of {sorted(ALLOWED_QHA_POINTS)}")
        if not 10 <= self.qha_mesh <= 60 or not 0 < self.qha_scale <= 0.01:
            raise ValueError("QHA mesh or scale is outside the allowlisted range")
        if not 1 <= self.parallel_workers <= 4:
            raise ValueError("parallel_workers must be between 1 and 4")


def prepare_precision_task(work_directory: str | Path) -> Path:
    work = Path(work_directory)
    tools = work / "workflow_scripts"
    tools.mkdir(parents=True, exist_ok=True)
    source_setting = compute_setting("TEP_PRECISION_SOURCE_ROOT")
    if not source_setting:
        raise RuntimeError(
            "Precision workflows are not configured: set TEP_PRECISION_SOURCE_ROOT"
        )
    source_root = Path(source_setting).expanduser()
    for name in ("complete_properties_calc.sh", "elastic_calculator.py", "file_utils.py"):
        shutil.copy2(source_root / name, tools / name)
    copy_compatible_qha_script(source_root / "qha_calcu.py", tools / "qha_calcu.py")
    return tools


def build_precision_command(
    work_directory: str | Path,
    config: PrecisionTaskConfig,
    *,
    mode: Literal["combined", "elastic", "qha"] = "combined",
) -> list[str]:
    config.validate()
    work = Path(work_directory).resolve()
    script = work / "workflow_scripts" / "complete_properties_calc.sh"
    if not (work / "POSCAR").is_file() or not script.is_file():
        raise ValueError("Precision task requires POSCAR and prepared workflow scripts")
    mode_flag = {
        "combined": "",
        "elastic": " --elastic-only",
        "qha": " --thermal-only",
    }[mode]
    distro = compute_setting("TEP_WSL_DISTRO", "Ubuntu-24.04") or "Ubuntu-24.04"
    conda_init = compute_setting("TEP_PRECISION_CONDA_INIT")
    conda_environment = compute_setting("TEP_PRECISION_CONDA_ENV", "mattersim") or "mattersim"
    vaspkit_bin = compute_setting("TEP_VASPKIT_BIN_DIR")
    missing = [
        name
        for name, value in (
            ("TEP_PRECISION_CONDA_INIT", conda_init),
            ("TEP_VASPKIT_BIN_DIR", vaspkit_bin),
        )
        if not value
    ]
    if missing:
        raise RuntimeError("Precision WSL environment is not configured: " + ", ".join(missing))
    command = (
        f"source {shlex.quote(conda_init)} && "
        f"export PATH={shlex.quote(vaspkit_bin)}:\"$PATH\" && "
        f"conda run -n {shlex.quote(conda_environment)} bash {shlex.quote(windows_to_wsl(script))}{mode_flag} --device cpu --parallel {config.parallel_workers} "
        f"--qha-n {config.qha_points} --qha-mesh {config.qha_mesh} "
        f"--qha-scale {config.qha_scale} {shlex.quote(windows_to_wsl(work / 'POSCAR'))}"
    )
    return ["wsl", "-d", distro, "--", "bash", "-lc", command]
