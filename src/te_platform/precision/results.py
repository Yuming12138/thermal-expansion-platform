from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np


@dataclass(frozen=True)
class PrecisionResults:
    elastic_tensor_gpa: tuple[tuple[float, ...], ...]
    elastic_min_eigenvalue_gpa: float
    elastic_positive_definite: bool
    thermal_expansion_curve: tuple[tuple[float, float], ...]
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


def _parse_thermal_expansion(path: Path) -> tuple[tuple[float, float], ...]:
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


def _interpolate_alpha(points: tuple[tuple[float, float], ...], target: float) -> float | None:
    if target < points[0][0] or target > points[-1][0]:
        return None
    for (left_t, left_alpha), (right_t, right_alpha) in zip(points, points[1:]):
        if left_t <= target <= right_t:
            if target == left_t:
                return left_alpha
            fraction = (target - left_t) / (right_t - left_t)
            return left_alpha + fraction * (right_alpha - left_alpha)
    return points[-1][1] if target == points[-1][0] else None


def parse_precision_results(work_directory: str | Path) -> PrecisionResults:
    root = Path(work_directory)
    tensor_path = root / "elastic" / "ELASTIC_TENSOR"
    thermal_path = root / "thermal_properties" / "thermal_expansion.dat"
    if not thermal_path.is_file():
        thermal_path = root / "qha_calculation" / "thermal_properties" / "thermal_expansion.dat"
    if not tensor_path.is_file() or not thermal_path.is_file():
        raise ValueError("Precision result directory must contain elastic/ELASTIC_TENSOR and thermal_expansion.dat")
    tensor = _parse_elastic_tensor(tensor_path)
    symmetric_tensor = (tensor + tensor.T) / 2.0
    eigenvalues = np.linalg.eigvalsh(symmetric_tensor)
    points = _parse_thermal_expansion(thermal_path)
    alpha_300 = _interpolate_alpha(points, 300.0)
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
    return PrecisionResults(
        elastic_tensor_gpa=tuple(tuple(float(value) for value in row) for row in tensor),
        elastic_min_eigenvalue_gpa=float(np.min(eigenvalues)),
        elastic_positive_definite=bool(float(np.min(eigenvalues)) > 0),
        thermal_expansion_curve=points,
        alpha_300k_per_k=alpha_300,
        alpha_300k_ppm_per_k=alpha_300 * 1_000_000 if alpha_300 is not None else None,
        quality_warnings=tuple(warnings),
    )
