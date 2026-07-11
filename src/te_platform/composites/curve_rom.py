from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class CurveROMResult:
    nte_volume_fraction: float
    nte_mass_fraction: float | None
    rms_error_ppm_per_k: float
    max_absolute_error_ppm_per_k: float
    mixed_alpha_ppm_per_k: tuple[float, ...]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def optimize_curve_rom(
    pte_alpha: list[float],
    nte_alpha: list[float],
    target_alpha: float = 0.0,
    *,
    pte_density: float | None = None,
    nte_density: float | None = None,
) -> CurveROMResult:
    if len(pte_alpha) < 2 or len(pte_alpha) != len(nte_alpha):
        raise ValueError("PTE and NTE curves must have the same length of at least two")
    delta = [n - p for p, n in zip(pte_alpha, nte_alpha)]
    offset = [p - target_alpha for p in pte_alpha]
    denominator = sum(value * value for value in delta)
    fraction = 0.0 if denominator == 0 else -sum(a * b for a, b in zip(offset, delta)) / denominator
    fraction = min(1.0, max(0.0, fraction))
    mixed = tuple((1.0 - fraction) * p + fraction * n for p, n in zip(pte_alpha, nte_alpha))
    errors = [value - target_alpha for value in mixed]
    mass_fraction = None
    if pte_density is not None or nte_density is not None:
        if not pte_density or not nte_density or pte_density <= 0 or nte_density <= 0:
            raise ValueError("Both positive phase densities are required for mass fraction")
        mass_fraction = fraction * nte_density / (fraction * nte_density + (1.0 - fraction) * pte_density)
    return CurveROMResult(
        nte_volume_fraction=fraction,
        nte_mass_fraction=mass_fraction,
        rms_error_ppm_per_k=(sum(value * value for value in errors) / len(errors)) ** 0.5,
        max_absolute_error_ppm_per_k=max(abs(value) for value in errors),
        mixed_alpha_ppm_per_k=mixed,
    )
