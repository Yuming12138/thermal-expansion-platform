from __future__ import annotations

import shutil
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from te_platform.precision.script_compat import copy_compatible_qha_script


SOURCE_ROOT = Path(r"D:\9.Project\10.recalcu_elastic_nte\auto_elastic_sh")
WSL_DISTRO = "Ubuntu-24.04"
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
    for name in ("complete_properties_calc.sh", "elastic_calculator.py", "file_utils.py"):
        shutil.copy2(SOURCE_ROOT / name, tools / name)
    copy_compatible_qha_script(SOURCE_ROOT / "qha_calcu.py", tools / "qha_calcu.py")
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
    command = (
        "source /home/gmchen/anaconda3/etc/profile.d/conda.sh && "
        "export PATH=\"$HOME/1.software/vaspkit.1.5.1/bin:$PATH\" && "
        f"conda run -n mattersim bash {shlex.quote(windows_to_wsl(script))}{mode_flag} --device cpu --parallel {config.parallel_workers} "
        f"--qha-n {config.qha_points} --qha-mesh {config.qha_mesh} "
        f"--qha-scale {config.qha_scale} {shlex.quote(windows_to_wsl(work / 'POSCAR'))}"
    )
    return ["wsl", "-d", WSL_DISTRO, "--", "bash", "-lc", command]
