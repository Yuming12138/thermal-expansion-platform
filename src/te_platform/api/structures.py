from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class StructureInspection:
    format: str
    atom_count: int | None
    cell_volume_a3: float | None
    elements: tuple[str, ...]
    warnings: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _determinant_3x3(matrix: list[list[float]]) -> float:
    return (
        matrix[0][0] * (matrix[1][1] * matrix[2][2] - matrix[1][2] * matrix[2][1])
        - matrix[0][1] * (matrix[1][0] * matrix[2][2] - matrix[1][2] * matrix[2][0])
        + matrix[0][2] * (matrix[1][0] * matrix[2][1] - matrix[1][1] * matrix[2][0])
    )


def inspect_poscar(text: str) -> StructureInspection:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) < 7:
        raise ValueError("POSCAR requires at least seven non-empty lines")
    try:
        scale = float(lines[1])
        lattice = [[float(value) for value in lines[index].split()[:3]] for index in range(2, 5)]
    except (IndexError, ValueError) as error:
        raise ValueError("POSCAR lattice or scale factor is invalid") from error
    if any(len(row) != 3 for row in lattice):
        raise ValueError("POSCAR lattice must have three vector components")

    species_line = lines[5].split()
    if all(token.replace("-", "", 1).isdigit() for token in species_line):
        elements: tuple[str, ...] = ()
        counts_line = species_line
    else:
        elements = tuple(species_line)
        counts_line = lines[6].split()
    try:
        counts = [int(float(value)) for value in counts_line]
    except ValueError as error:
        raise ValueError("POSCAR atom counts are invalid") from error
    if not counts or any(count <= 0 for count in counts):
        raise ValueError("POSCAR atom counts must be positive")
    if elements and len(elements) != len(counts):
        raise ValueError("POSCAR species and atom count lengths differ")

    volume = abs(_determinant_3x3(lattice)) * abs(scale) ** 3
    if volume <= 0:
        raise ValueError("POSCAR cell volume must be positive")
    warnings = () if elements else ("VASP4-style POSCAR has no explicit element symbols",)
    return StructureInspection(
        format="poscar",
        atom_count=sum(counts),
        cell_volume_a3=volume,
        elements=elements,
        warnings=warnings,
    )


def _cif_number(text: str, key: str) -> float | None:
    match = re.search(rf"^{re.escape(key)}\s+([-+0-9.]+)", text, re.MULTILINE)
    return float(match.group(1)) if match else None


def inspect_cif(text: str) -> StructureInspection:
    a = _cif_number(text, "_cell_length_a")
    b = _cif_number(text, "_cell_length_b")
    c = _cif_number(text, "_cell_length_c")
    alpha = _cif_number(text, "_cell_angle_alpha")
    beta = _cif_number(text, "_cell_angle_beta")
    gamma = _cif_number(text, "_cell_angle_gamma")
    warnings: list[str] = []
    volume = None
    if None not in (a, b, c, alpha, beta, gamma):
        assert a is not None and b is not None and c is not None
        assert alpha is not None and beta is not None and gamma is not None
        alpha_rad, beta_rad, gamma_rad = map(math.radians, (alpha, beta, gamma))
        factor = 1 + 2 * math.cos(alpha_rad) * math.cos(beta_rad) * math.cos(gamma_rad)
        factor -= math.cos(alpha_rad) ** 2 + math.cos(beta_rad) ** 2 + math.cos(gamma_rad) ** 2
        volume = a * b * c * math.sqrt(max(0.0, factor))
    else:
        warnings.append("CIF cell parameters are incomplete")

    element_matches = re.findall(r"^\s*([A-Z][a-z]?)\S*\s+[-+0-9.]", text, re.MULTILINE)
    elements = tuple(sorted(set(element_matches)))
    warnings.append("CIF atom count requires the full crystallographic parser in the prediction worker")
    return StructureInspection(
        format="cif",
        atom_count=None,
        cell_volume_a3=volume,
        elements=elements,
        warnings=tuple(warnings),
    )


def inspect_structure(filename: str, content: bytes) -> StructureInspection:
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        text = content.decode("utf-8-sig", errors="replace")
    suffix = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    if suffix == "cif" or "_cell_length_a" in text:
        return inspect_cif(text)
    return inspect_poscar(text)
