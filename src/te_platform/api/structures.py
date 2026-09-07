from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class StructureSymmetry:
    """Crystallographic routing facts used by the precision workflow.

    ``is_cubic`` is deliberately tri-state.  A failed crystallographic parse
    must not silently route a non-cubic upload through scalar QHA.
    """

    crystal_system: str | None = None
    space_group_symbol: str | None = None
    space_group_number: int | None = None
    is_cubic: bool | None = None
    source: str = "unresolved"

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class StructureInspection:
    format: str
    atom_count: int | None
    cell_volume_a3: float | None
    elements: tuple[str, ...]
    warnings: tuple[str, ...]
    symmetry: StructureSymmetry = StructureSymmetry()

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


def _metric_symmetry_from_inspection(inspection: StructureInspection, text: str) -> StructureSymmetry:
    """Best-effort fallback for truncated uploads used in smoke tests.

    Real uploads are parsed by pymatgen below.  The metric fallback only
    claims cubic when all three lengths and angles are unambiguously cubic;
    otherwise it returns ``None`` so the caller can refuse unsafe routing.
    """
    try:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if inspection.format == "poscar" and len(lines) >= 5:
            scale = abs(float(lines[1]))
            vectors = [[float(value) for value in lines[index].split()[:3]] for index in range(2, 5)]
            lengths = [sum(value * value for value in vector) ** 0.5 * scale for vector in vectors]
            dot = lambda left, right: sum(a * b for a, b in zip(left, right))
            angles = []
            for left, right in ((vectors[1], vectors[2]), (vectors[0], vectors[2]), (vectors[0], vectors[1])):
                denom = (dot(left, left) * dot(right, right)) ** 0.5
                angles.append(90.0 if denom == 0 else math.degrees(math.acos(max(-1.0, min(1.0, dot(left, right) / denom)))))
        elif inspection.format == "cif":
            a = _cif_number(text, "_cell_length_a")
            b = _cif_number(text, "_cell_length_b")
            c = _cif_number(text, "_cell_length_c")
            alpha = _cif_number(text, "_cell_angle_alpha")
            beta = _cif_number(text, "_cell_angle_beta")
            gamma = _cif_number(text, "_cell_angle_gamma")
            if None in (a, b, c, alpha, beta, gamma):
                return StructureSymmetry(source="metric_fallback_unresolved")
            lengths = [float(a), float(b), float(c)]
            angles = [float(alpha), float(beta), float(gamma)]
        else:
            return StructureSymmetry(source="metric_fallback_unresolved")
        equal_lengths = max(lengths) - min(lengths) <= max(1e-3, 1e-3 * max(lengths))
        right_angles = max(abs(angle - 90.0) for angle in angles) <= 1e-2
        if equal_lengths and right_angles:
            return StructureSymmetry(
                crystal_system="cubic",
                is_cubic=True,
                source="lattice_metric_fallback",
            )
    except (ArithmeticError, IndexError, TypeError, ValueError):
        pass
    return StructureSymmetry(source="metric_fallback_unresolved")


def analyze_structure_symmetry(filename: str, content: bytes, inspection: StructureInspection | None = None) -> StructureSymmetry:
    """Return the space-group based symmetry used for QHA/AGV2 routing."""
    current = inspection or inspect_structure(filename, content)
    try:
        from pymatgen.core import Structure
        from pymatgen.symmetry.analyzer import SpacegroupAnalyzer

        text = content.decode("utf-8", errors="replace")
        fmt = "cif" if current.format == "cif" else "poscar"
        structure = Structure.from_str(text, fmt=fmt)
        analyzer = SpacegroupAnalyzer(structure, symprec=0.1, angle_tolerance=5.0)
        crystal_system = analyzer.get_crystal_system()
        return StructureSymmetry(
            crystal_system=crystal_system,
            space_group_symbol=analyzer.get_space_group_symbol(),
            space_group_number=int(analyzer.get_space_group_number()),
            is_cubic=crystal_system == "cubic",
            source="pymatgen.SpacegroupAnalyzer",
        )
    except Exception:
        return _metric_symmetry_from_inspection(current, content.decode("utf-8", errors="replace"))


def inspect_structure(filename: str, content: bytes) -> StructureInspection:
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        text = content.decode("utf-8-sig", errors="replace")
    suffix = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    inspection = inspect_cif(text) if suffix == "cif" or "_cell_length_a" in text else inspect_poscar(text)
    return StructureInspection(
        format=inspection.format,
        atom_count=inspection.atom_count,
        cell_volume_a3=inspection.cell_volume_a3,
        elements=inspection.elements,
        warnings=inspection.warnings,
        symmetry=analyze_structure_symmetry(filename, content, inspection),
    )
