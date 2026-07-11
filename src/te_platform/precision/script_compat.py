from __future__ import annotations

from pathlib import Path


OLD_IMPORT = "from ase.constraints import ExpCellFilter"
OLD_THERMAL_COPY = "shutil.copy('thermal_properties.yaml', os.path.join(thermal_properties_dir, f'thermal_properties_{i}.yaml'))"
NEW_THERMAL_COPY = "if os.path.exists('thermal_properties.yaml'): shutil.copy('thermal_properties.yaml', os.path.join(thermal_properties_dir, f'thermal_properties_{i}.yaml'))"
NEW_IMPORT = """try:
    from ase.filters import ExpCellFilter
except ImportError:
    from ase.constraints import ExpCellFilter
import ase.constraints as ase_constraints
from ase.stress import full_3x3_to_voigt_6_stress, voigt_6_to_full_3x3_stress
if not hasattr(ase_constraints, "full_3x3_to_voigt_6_stress"):
    ase_constraints.full_3x3_to_voigt_6_stress = full_3x3_to_voigt_6_stress
if not hasattr(ase_constraints, "voigt_6_to_full_3x3_stress"):
    ase_constraints.voigt_6_to_full_3x3_stress = voigt_6_to_full_3x3_stress"""


def make_qha_script_ase_compatible(source: str) -> str:
    if NEW_IMPORT in source:
        result = source
    elif OLD_IMPORT in source:
        result = source.replace(OLD_IMPORT, NEW_IMPORT, 1)
    else:
        raise ValueError("QHA script does not contain the expected ExpCellFilter import")
    patched_lines: list[str] = []
    for line in result.splitlines(keepends=True):
        if line.strip() != OLD_THERMAL_COPY:
            patched_lines.append(line)
            continue

        indentation = line[: len(line) - len(line.lstrip())]
        line_ending = "\n" if line.endswith("\n") else ""
        patched_lines.append(f"{indentation}{NEW_THERMAL_COPY}{line_ending}")
    return "".join(patched_lines)


def copy_compatible_qha_script(source_path: str | Path, target_path: str | Path) -> Path:
    source = Path(source_path)
    target = Path(target_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        make_qha_script_ase_compatible(source.read_text(encoding="utf-8")),
        encoding="utf-8",
    )
    return target
