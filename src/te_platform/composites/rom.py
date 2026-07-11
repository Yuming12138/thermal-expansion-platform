from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class ROMResult:
    alpha_pte: float
    alpha_nte: float
    target_alpha: float
    nte_volume_fraction: float
    predicted_alpha: float
    absolute_error: float
    feasible_exact_solution: bool

    def to_dict(self) -> dict[str, float | bool]:
        return asdict(self)


def mix_alpha(alpha_pte: float, alpha_nte: float, nte_volume_fraction: float) -> float:
    if not 0.0 <= nte_volume_fraction <= 1.0:
        raise ValueError("NTE volume fraction must be between 0 and 1")
    return (1.0 - nte_volume_fraction) * alpha_pte + nte_volume_fraction * alpha_nte


def optimize_zte_fraction(
    alpha_pte: float,
    alpha_nte: float,
    target_alpha: float = 0.0,
) -> ROMResult:
    denominator = alpha_nte - alpha_pte
    if denominator == 0:
        fraction = 0.0
        exact = alpha_pte == target_alpha
    else:
        unconstrained = (target_alpha - alpha_pte) / denominator
        fraction = min(1.0, max(0.0, unconstrained))
        exact = 0.0 <= unconstrained <= 1.0

    predicted = mix_alpha(alpha_pte, alpha_nte, fraction)
    if abs(predicted - target_alpha) < 1e-12:
        predicted = target_alpha
    return ROMResult(
        alpha_pte=alpha_pte,
        alpha_nte=alpha_nte,
        target_alpha=target_alpha,
        nte_volume_fraction=fraction,
        predicted_alpha=predicted,
        absolute_error=abs(predicted - target_alpha),
        feasible_exact_solution=exact,
    )
