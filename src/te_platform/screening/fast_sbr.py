from __future__ import annotations

from dataclasses import asdict, dataclass

from te_platform.screening.sbr import (
    FORMAL_BOUNDARY,
    HIGH_PROBABILITY_NTE_BOUNDARY,
    SBRResult,
    classify_sbr,
)


EV_PER_A3_TO_GPA = 160.21766208
DEFAULT_ALIGNN_G_MAE_GPA = 9.476007


@dataclass(frozen=True)
class BondingModulusResult:
    cohesive_energy_ev_per_atom: float
    volume_per_atom_a3: float
    average_coordination_number: float
    cohesive_energy_density_gpa: float
    bonding_modulus_gpa: float

    def to_dict(self) -> dict[str, float]:
        return asdict(self)


@dataclass(frozen=True)
class FastSBRResult:
    predicted_shear_modulus_gpa: float
    shear_model_mae_gpa: float
    bonding: BondingModulusResult
    sbr: SBRResult
    xi_lower_mae: float
    xi_upper_mae: float
    decision_quality: str
    recommended_next_step: str

    def to_dict(self) -> dict[str, object]:
        result = asdict(self)
        result["bonding"] = self.bonding.to_dict()
        result["sbr"] = self.sbr.to_dict()
        return result


def calculate_bonding_modulus(
    cohesive_energy_ev_per_atom: float,
    cell_volume_a3: float,
    atom_count: int,
    average_coordination_number: float,
) -> BondingModulusResult:
    if cell_volume_a3 <= 0:
        raise ValueError("Cell volume must be positive")
    if atom_count <= 0:
        raise ValueError("Atom count must be positive")
    if average_coordination_number <= 0:
        raise ValueError("Average coordination number must be positive")

    volume_per_atom = cell_volume_a3 / atom_count
    return calculate_bonding_modulus_from_atomic_volume(
        cohesive_energy_ev_per_atom,
        volume_per_atom,
        average_coordination_number,
    )


def calculate_bonding_modulus_from_atomic_volume(
    cohesive_energy_ev_per_atom: float,
    volume_per_atom_a3: float,
    average_coordination_number: float,
) -> BondingModulusResult:
    """Return the paper-defined bonding modulus E_tilde = U_V / n.

    U_V is the volumetric cohesive-energy density in GPa, obtained from the
    cohesive energy per atom divided by the average atomic volume.
    """
    if volume_per_atom_a3 <= 0:
        raise ValueError("Volume per atom must be positive")
    if average_coordination_number <= 0:
        raise ValueError("Average coordination number must be positive")

    cohesive_energy_density = (
        abs(cohesive_energy_ev_per_atom) / volume_per_atom_a3 * EV_PER_A3_TO_GPA
    )
    bonding_modulus = cohesive_energy_density / average_coordination_number
    return BondingModulusResult(
        cohesive_energy_ev_per_atom=cohesive_energy_ev_per_atom,
        volume_per_atom_a3=volume_per_atom_a3,
        average_coordination_number=average_coordination_number,
        cohesive_energy_density_gpa=cohesive_energy_density,
        bonding_modulus_gpa=bonding_modulus,
    )


def fast_screen_sbr(
    predicted_shear_modulus_gpa: float,
    cohesive_energy_ev_per_atom: float,
    cell_volume_a3: float,
    atom_count: int,
    average_coordination_number: float,
    *,
    shear_model_mae_gpa: float = DEFAULT_ALIGNN_G_MAE_GPA,
) -> FastSBRResult:
    if shear_model_mae_gpa < 0:
        raise ValueError("Shear model MAE cannot be negative")

    bonding = calculate_bonding_modulus(
        cohesive_energy_ev_per_atom,
        cell_volume_a3,
        atom_count,
        average_coordination_number,
    )
    sbr = classify_sbr(predicted_shear_modulus_gpa, bonding.bonding_modulus_gpa)
    xi_error = shear_model_mae_gpa / bonding.bonding_modulus_gpa
    xi_lower = max(0.0, sbr.xi - xi_error)
    xi_upper = sbr.xi + xi_error

    if xi_upper < HIGH_PROBABILITY_NTE_BOUNDARY:
        quality = "robust_high_probability_nte"
        next_step = "Optional QHA validation"
    elif xi_upper < FORMAL_BOUNDARY:
        quality = "likely_nte"
        next_step = "QHA validation recommended"
    elif xi_lower > FORMAL_BOUNDARY:
        quality = "likely_pte"
        next_step = "Full elastic tensor is optional unless high confidence is required"
    else:
        quality = "boundary_review"
        next_step = "Calculate the full elastic tensor and QHA before making a final decision"

    return FastSBRResult(
        predicted_shear_modulus_gpa=predicted_shear_modulus_gpa,
        shear_model_mae_gpa=shear_model_mae_gpa,
        bonding=bonding,
        sbr=sbr,
        xi_lower_mae=xi_lower,
        xi_upper_mae=xi_upper,
        decision_quality=quality,
        recommended_next_step=next_step,
    )
