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
    # AGV2 uses the published v2 defaults.  These are kept separate from the
    # legacy scalar-QHA controls so a QHA-only request cannot accidentally
    # change the anisotropic calculation contract.
    agv2_mesh: int = 20
    agv2_strain: float = 0.005
    agv2_displacement: float = 0.01
    agv2_min_supercell_length: float = 12.0
    agv2_model_size: Literal["1M", "5M"] = "1M"

    def validate(self) -> None:
        if self.qha_points not in ALLOWED_QHA_POINTS:
            raise ValueError(f"qha_points must be one of {sorted(ALLOWED_QHA_POINTS)}")
        if not 10 <= self.qha_mesh <= 60 or not 0 < self.qha_scale <= 0.01:
            raise ValueError("QHA mesh or scale is outside the allowlisted range")
        if not 1 <= self.parallel_workers <= 4:
            raise ValueError("parallel_workers must be between 1 and 4")
        if not 8 <= self.agv2_mesh <= 40:
            raise ValueError("agv2_mesh must be between 8 and 40")
        if not 0 < self.agv2_strain <= 0.02 or not 0 < self.agv2_displacement <= 0.1:
            raise ValueError("AGV2 strain or displacement is outside the allowlisted range")
        if self.agv2_min_supercell_length < 8:
            raise ValueError("agv2_min_supercell_length must be at least 8 Å")


def _agv2_source_root() -> Path:
    source_setting = compute_setting("TEP_AGV2_SOURCE_ROOT")
    if not source_setting:
        raise RuntimeError("AGV2 workflows are not configured: set TEP_AGV2_SOURCE_ROOT")
    source_root = Path(source_setting).expanduser()
    nested = source_root / "0.scripts" / "gruneisen_anisotropy_calcu"
    if (nested / "run_gruneisen_thermal_expansion_v2.py").is_file():
        return nested
    if (source_root / "run_gruneisen_thermal_expansion_v2.py").is_file():
        return source_root
    raise RuntimeError(f"Missing AGV2 runner under {source_root}")


def prepare_precision_task(work_directory: str | Path, *, include_agv2: bool = False) -> Path:
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
    if include_agv2:
        agv2_root = _agv2_source_root()
        agv2_tools = tools / "agv2"
        agv2_tools.mkdir(parents=True, exist_ok=True)
        for name in ("run_gruneisen_thermal_expansion_v2.py", "gruneisen_v2_core.py"):
            shutil.copy2(agv2_root / name, agv2_tools / name)
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


def build_anisotropic_command(
    work_directory: str | Path,
    config: PrecisionTaskConfig,
) -> list[str]:
    """Build the non-cubic pipeline: elastic tensor first, then AGV2.

    The command intentionally has no QHA fallback.  If either stage fails,
    the task remains failed and the UI reports the exact stage to the user.
    """
    config.validate()
    work = Path(work_directory).resolve()
    script = work / "workflow_scripts" / "complete_properties_calc.sh"
    runner = work / "workflow_scripts" / "agv2" / "run_gruneisen_thermal_expansion_v2.py"
    if not (work / "POSCAR").is_file() or not script.is_file() or not runner.is_file():
        raise ValueError("AGV2 task requires POSCAR, prepared precision scripts, and the v2 runner")
    distro = compute_setting("TEP_WSL_DISTRO", "Ubuntu-24.04") or "Ubuntu-24.04"
    conda_init = compute_setting("TEP_PRECISION_CONDA_INIT")
    conda_environment = compute_setting("TEP_PRECISION_CONDA_ENV", "mattersim") or "mattersim"
    vaspkit_bin = compute_setting("TEP_VASPKIT_BIN_DIR")
    missing = [
        name for name, value in (("TEP_PRECISION_CONDA_INIT", conda_init), ("TEP_VASPKIT_BIN_DIR", vaspkit_bin)) if not value
    ]
    if missing:
        raise RuntimeError("Precision WSL environment is not configured: " + ", ".join(missing))
    work_wsl = windows_to_wsl(work)
    # Keep the expensive MatterSim/Phonopy stages on the WSL-native filesystem.
    # The Windows work directory remains the durable UI-visible copy; only the
    # small input bundle is copied into /tmp before the calculation starts.
    native_wsl = f"/tmp/tep-agv2-{work.name}"
    native_script = f"{native_wsl}/workflow_scripts/complete_properties_calc.sh"
    native_runner = f"{native_wsl}/workflow_scripts/agv2/run_gruneisen_thermal_expansion_v2.py"
    elastic_cmd = (
        f"mkdir -p {shlex.quote(native_wsl)} && cp -a {shlex.quote(work_wsl)}/. {shlex.quote(native_wsl)}/ && "
        f"conda run -n {shlex.quote(conda_environment)} bash {shlex.quote(native_script)} "
        f"--elastic-only --device auto --parallel {config.parallel_workers} --model 1M {shlex.quote(native_wsl)}"
    )
    agv2_cmd = (
        f"conda run -n {shlex.quote(conda_environment)} python {shlex.quote(native_runner)} "
        f"--material-dir {shlex.quote(native_wsl)} --result-subdir gruneisen_aniso_1M_v2 "
        f"--model-size {config.agv2_model_size} --device auto --dtype float64 "
        f"--strain {config.agv2_strain} --displacement {config.agv2_displacement} "
        f"--mesh {config.agv2_mesh} {config.agv2_mesh} {config.agv2_mesh} "
        f"--min-supercell-length {config.agv2_min_supercell_length} "
        f"--batch-relax --batch-relax-atom-cap 1024"
    )
    agv2_model = compute_setting("TEP_AGV2_MODEL")
    if agv2_model:
        model_path = Path(agv2_model).expanduser()
        model_arg = windows_to_wsl(model_path) if len(str(model_path)) >= 3 and str(model_path)[1:3] == ":\\" else str(model_path)
        agv2_cmd += f" --model {shlex.quote(model_arg)}"
    sync_back = (
        f"cp -a {shlex.quote(native_wsl)}/elastic {shlex.quote(work_wsl)}/ && "
        f"cp -a {shlex.quote(native_wsl)}/gruneisen_aniso_1M_v2 {shlex.quote(work_wsl)}/"
    )
    command = (
        f"source {shlex.quote(conda_init)} && export PATH={shlex.quote(vaspkit_bin)}:\"$PATH\" && "
        f"{elastic_cmd} && {agv2_cmd} && {sync_back}"
    )
    return ["wsl", "-d", distro, "--", "bash", "-lc", command]
