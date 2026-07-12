from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np


@dataclass(frozen=True)
class ElasticResults:
    elastic_tensor_gpa: tuple[tuple[float, ...], ...]
    elastic_min_eigenvalue_gpa: float
    elastic_positive_definite: bool
    bulk_modulus_voigt_gpa: float
    bulk_modulus_reuss_gpa: float
    bulk_modulus_hill_gpa: float
    shear_modulus_voigt_gpa: float
    shear_modulus_reuss_gpa: float
    shear_modulus_hill_gpa: float
    quality_warnings: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class QhaResults:
    thermal_expansion_curve: tuple[tuple[float, float], ...]
    thermal_expansion_source_path: str
    alpha_300k_per_k: float | None
    alpha_300k_ppm_per_k: float | None
    quality_warnings: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class PrecisionResults:
    elastic_tensor_gpa: tuple[tuple[float, ...], ...]
    elastic_min_eigenvalue_gpa: float
    elastic_positive_definite: bool
    bulk_modulus_voigt_gpa: float
    bulk_modulus_reuss_gpa: float
    bulk_modulus_hill_gpa: float
    shear_modulus_voigt_gpa: float
    shear_modulus_reuss_gpa: float
    shear_modulus_hill_gpa: float
    thermal_expansion_curve: tuple[tuple[float, float], ...]
    thermal_expansion_source_path: str
    alpha_300k_per_k: float | None
    alpha_300k_ppm_per_k: float | None
    quality_warnings: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _parse_elastic_tensor(path: Path) -> np.ndarray:
    rows: list[list[float]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        values = line.split()
        if len(values) != 6:
            continue
        try:
            row = [float(value) for value in values]
        except ValueError:
            continue
        rows.append(row)
        if len(rows) == 6:
            break
    if len(rows) != 6:
        raise ValueError(f"ELASTIC_TENSOR does not contain a 6x6 numeric tensor: {path}")
    tensor = np.asarray(rows, dtype=float)
    if not np.all(np.isfinite(tensor)):
        raise ValueError("Elastic tensor contains NaN or infinity")
    return tensor


def parse_thermal_expansion_file(path: str | Path) -> tuple[tuple[float, float], ...]:
    """Read one QHA ``thermal_expansion.dat`` into ordered (T, alpha) points."""
    path = Path(path)
    points: list[tuple[float, float]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        values = line.split()
        if len(values) < 2:
            continue
        try:
            temperature, alpha = float(values[0]), float(values[1])
        except ValueError:
            continue
        if math.isfinite(temperature) and math.isfinite(alpha):
            points.append((temperature, alpha))
    if len(points) < 2:
        raise ValueError(f"thermal_expansion.dat has fewer than two valid rows: {path}")
    if any(right[0] <= left[0] for left, right in zip(points, points[1:])):
        raise ValueError("Thermal-expansion temperatures must be strictly increasing")
    return tuple(points)


def interpolate_alpha(points: tuple[tuple[float, float], ...], target: float) -> float | None:
    if target < points[0][0] or target > points[-1][0]:
        return None
    for (left_t, left_alpha), (right_t, right_alpha) in zip(points, points[1:]):
        if left_t <= target <= right_t:
            if target == left_t:
                return left_alpha
            fraction = (target - left_t) / (right_t - left_t)
            return left_alpha + fraction * (right_alpha - left_alpha)
    return points[-1][1] if target == points[-1][0] else None


def parse_elastic_results(work_directory: str | Path) -> ElasticResults:
    root = Path(work_directory)
    tensor_path = root / "elastic" / "ELASTIC_TENSOR"
    if not tensor_path.is_file():
        raise ValueError("Elastic result directory must contain elastic/ELASTIC_TENSOR")
    tensor = _parse_elastic_tensor(tensor_path)
    symmetric_tensor = (tensor + tensor.T) / 2.0
    eigenvalues = np.linalg.eigvalsh(symmetric_tensor)
    try:
        compliance = np.linalg.inv(symmetric_tensor)
    except np.linalg.LinAlgError as error:
        raise ValueError("Elastic tensor is singular and cannot be inverted") from error

    c11, c22, c33 = (symmetric_tensor[index, index] for index in range(3))
    c12, c13, c23 = symmetric_tensor[0, 1], symmetric_tensor[0, 2], symmetric_tensor[1, 2]
    c44, c55, c66 = (symmetric_tensor[index, index] for index in range(3, 6))
    bulk_voigt = (c11 + c22 + c33 + 2 * (c12 + c13 + c23)) / 9.0
    shear_voigt = (c11 + c22 + c33 - c12 - c13 - c23 + 3 * (c44 + c55 + c66)) / 15.0

    s11, s22, s33 = (compliance[index, index] for index in range(3))
    s12, s13, s23 = compliance[0, 1], compliance[0, 2], compliance[1, 2]
    s44, s55, s66 = (compliance[index, index] for index in range(3, 6))
    bulk_denominator = s11 + s22 + s33 + 2 * (s12 + s13 + s23)
    shear_denominator = 4 * (s11 + s22 + s33) - 4 * (s12 + s13 + s23) + 3 * (s44 + s55 + s66)
    if bulk_denominator == 0 or shear_denominator == 0:
        raise ValueError("Elastic tensor produces an undefined Reuss modulus")
    bulk_reuss = 1.0 / bulk_denominator
    shear_reuss = 15.0 / shear_denominator

    warnings: list[str] = []
    if not np.allclose(tensor, tensor.T, rtol=0, atol=1e-3):
        warnings.append("Elastic tensor is not symmetric within 1e-3 GPa")
    if float(np.min(eigenvalues)) <= 0:
        warnings.append("Elastic tensor is not positive definite")
    bm_log = root / "elastic" / "BM_SS.log"
    if bm_log.is_file() and re.search(
        r"unstrained structure has non-zero elastic energy",
        bm_log.read_text(encoding="utf-8", errors="replace"),
        flags=re.IGNORECASE,
    ):
        warnings.append("VASPKIT reports non-zero unstrained elastic energy; re-optimization is recommended")

    return ElasticResults(
        elastic_tensor_gpa=tuple(tuple(float(value) for value in row) for row in tensor),
        elastic_min_eigenvalue_gpa=float(np.min(eigenvalues)),
        elastic_positive_definite=bool(float(np.min(eigenvalues)) > 0),
        bulk_modulus_voigt_gpa=float(bulk_voigt),
        bulk_modulus_reuss_gpa=float(bulk_reuss),
        bulk_modulus_hill_gpa=float((bulk_voigt + bulk_reuss) / 2.0),
        shear_modulus_voigt_gpa=float(shear_voigt),
        shear_modulus_reuss_gpa=float(shear_reuss),
        shear_modulus_hill_gpa=float((shear_voigt + shear_reuss) / 2.0),
        quality_warnings=tuple(warnings),
    )


def parse_qha_results(work_directory: str | Path) -> QhaResults:
    root = Path(work_directory)
    thermal_path = root / "thermal_properties" / "thermal_expansion.dat"
    if not thermal_path.is_file():
        thermal_path = root / "qha_calculation" / "thermal_properties" / "thermal_expansion.dat"
    if not thermal_path.is_file():
        raise ValueError("QHA result directory must contain thermal_expansion.dat")
    points = parse_thermal_expansion_file(thermal_path)
    alpha_300 = interpolate_alpha(points, 300.0)
    warnings: list[str] = []
    qha_log = root / "qha_calc.log"
    if qha_log.is_file() and re.search(
        r"imaginary (phonon )?frequencies|has imaginary phonon|虚频",
        qha_log.read_text(encoding="utf-8", errors="replace"),
        flags=re.IGNORECASE,
    ):
        warnings.append(
            "Imaginary phonon frequencies were detected during QHA; treat alpha(T) as a qualitative result"
        )
    return QhaResults(
        thermal_expansion_curve=points,
        thermal_expansion_source_path=str(thermal_path.resolve()),
        alpha_300k_per_k=alpha_300,
        alpha_300k_ppm_per_k=alpha_300 * 1_000_000 if alpha_300 is not None else None,
        quality_warnings=tuple(warnings),
    )


def parse_precision_results(work_directory: str | Path) -> PrecisionResults:
    elastic = parse_elastic_results(work_directory)
    qha = parse_qha_results(work_directory)
    return PrecisionResults(
        elastic_tensor_gpa=elastic.elastic_tensor_gpa,
        elastic_min_eigenvalue_gpa=elastic.elastic_min_eigenvalue_gpa,
        elastic_positive_definite=elastic.elastic_positive_definite,
        bulk_modulus_voigt_gpa=elastic.bulk_modulus_voigt_gpa,
        bulk_modulus_reuss_gpa=elastic.bulk_modulus_reuss_gpa,
        bulk_modulus_hill_gpa=elastic.bulk_modulus_hill_gpa,
        shear_modulus_voigt_gpa=elastic.shear_modulus_voigt_gpa,
        shear_modulus_reuss_gpa=elastic.shear_modulus_reuss_gpa,
        shear_modulus_hill_gpa=elastic.shear_modulus_hill_gpa,
        thermal_expansion_curve=qha.thermal_expansion_curve,
        thermal_expansion_source_path=qha.thermal_expansion_source_path,
        alpha_300k_per_k=qha.alpha_300k_per_k,
        alpha_300k_ppm_per_k=qha.alpha_300k_ppm_per_k,
        quality_warnings=tuple(dict.fromkeys((*elastic.quality_warnings, *qha.quality_warnings))),
    )
