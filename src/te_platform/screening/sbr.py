from __future__ import annotations

from dataclasses import asdict, dataclass


FORMAL_BOUNDARY = 2.84
HIGH_PROBABILITY_NTE_BOUNDARY = 2.5


@dataclass(frozen=True)
class SBRResult:
    shear_modulus_gpa: float
    bonding_modulus_gpa: float
    xi: float
    classification: str
    formal_boundary: float
    high_probability_boundary: float
    margin_to_formal_boundary: float

    def to_dict(self) -> dict[str, float | str]:
        return asdict(self)


def classify_sbr(shear_modulus_gpa: float, bonding_modulus_gpa: float) -> SBRResult:
    if bonding_modulus_gpa <= 0:
        raise ValueError("Bonding modulus must be positive")
    if shear_modulus_gpa < 0:
        raise ValueError("Shear modulus cannot be negative")

    xi = shear_modulus_gpa / bonding_modulus_gpa
    if xi < HIGH_PROBABILITY_NTE_BOUNDARY:
        classification = "high_probability_nte"
    elif xi < FORMAL_BOUNDARY:
        classification = "nte"
    elif xi > FORMAL_BOUNDARY:
        classification = "pte"
    else:
        classification = "boundary"

    return SBRResult(
        shear_modulus_gpa=shear_modulus_gpa,
        bonding_modulus_gpa=bonding_modulus_gpa,
        xi=xi,
        classification=classification,
        formal_boundary=FORMAL_BOUNDARY,
        high_probability_boundary=HIGH_PROBABILITY_NTE_BOUNDARY,
        margin_to_formal_boundary=xi - FORMAL_BOUNDARY,
    )
