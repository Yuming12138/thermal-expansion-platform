from __future__ import annotations

from dataclasses import asdict, dataclass
from math import sqrt


MODEL_METADATA = {
    "linear_rom": {
        "label": "线性 ROM",
        "formula": "alpha_c=(1-f_NTE)*alpha_PTE+f_NTE*alpha_NTE",
        "assumptions": "两相自由应变按体积分数线性叠加，不考虑弹性约束、孔隙和界面效应。",
    },
    "turner": {
        "label": "Turner 模型",
        "formula": (
            "alpha_c=((1-f_NTE)*K_PTE*alpha_PTE+f_NTE*K_NTE*alpha_NTE)"
            "/((1-f_NTE)*K_PTE+f_NTE*K_NTE)"
        ),
        "assumptions": "各相承受一致静水压力，以体积模量加权；不显式描述形貌和界面。",
    },
    "kerner": {
        "label": "Kerner 模型",
        "formula": (
            "alpha_c=V_m*alpha_m+V_p*alpha_p+"
            "V_m*V_p*(alpha_p-alpha_m)*(K_p-K_m)/"
            "(V_m*K_m+V_p*K_p+3*K_m*K_p/(4*G_m))"
        ),
        "assumptions": (
            "各向同性连续基体中分散近球形颗粒，界面完全结合；"
            "基体相选择会改变结果，不考虑孔隙、团聚和界面反应。"
        ),
    },
}


@dataclass(frozen=True)
class CurveROMResult:
    model: str
    model_label: str
    formula: str
    assumptions: str
    matrix_phase: str | None
    nte_volume_fraction: float
    nte_mass_fraction: float | None
    effective_nte_thermal_weight: float
    rms_error_ppm_per_k: float
    mean_absolute_error_ppm_per_k: float
    mean_error_ppm_per_k: float
    max_absolute_error_ppm_per_k: float
    zte_tolerance_ppm_per_k: float
    zte_temperature_coverage_fraction: float
    zte_temperature_span_k: float | None
    zte_temperature_ranges_k: tuple[tuple[float, float], ...]
    mixed_alpha_ppm_per_k: tuple[float, ...]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _validate_curves(pte_alpha: list[float], nte_alpha: list[float]) -> None:
    if len(pte_alpha) < 2 or len(pte_alpha) != len(nte_alpha):
        raise ValueError("PTE and NTE curves must have the same length of at least two")


def _thermal_weight_to_volume_fraction(
    thermal_weight: float,
    *,
    model: str,
    pte_bulk_modulus_gpa: float | None,
    nte_bulk_modulus_gpa: float | None,
) -> float:
    if model == "linear_rom":
        return thermal_weight
    if model != "turner":
        raise ValueError(f"Unknown composite thermal-expansion model: {model}")
    if not pte_bulk_modulus_gpa or not nte_bulk_modulus_gpa:
        raise ValueError("Turner model requires positive bulk moduli for both phases")
    if pte_bulk_modulus_gpa <= 0 or nte_bulk_modulus_gpa <= 0:
        raise ValueError("Turner model requires positive bulk moduli for both phases")
    denominator = nte_bulk_modulus_gpa * (1.0 - thermal_weight) + (
        thermal_weight * pte_bulk_modulus_gpa
    )
    if denominator <= 0:
        return 0.0
    return thermal_weight * pte_bulk_modulus_gpa / denominator


def mix_curve(
    pte_alpha: list[float],
    nte_alpha: list[float],
    nte_volume_fraction: float,
    *,
    model: str = "linear_rom",
    pte_bulk_modulus_gpa: float | None = None,
    nte_bulk_modulus_gpa: float | None = None,
    pte_shear_modulus_gpa: float | None = None,
    nte_shear_modulus_gpa: float | None = None,
    matrix_phase: str = "pte",
) -> tuple[float, ...]:
    _validate_curves(pte_alpha, nte_alpha)
    fraction = float(nte_volume_fraction)
    if not 0.0 <= fraction <= 1.0:
        raise ValueError("NTE volume fraction must be between 0 and 1")
    if model == "linear_rom":
        return tuple((1.0 - fraction) * p + fraction * n for p, n in zip(pte_alpha, nte_alpha))
    if model == "turner":
        if not pte_bulk_modulus_gpa or not nte_bulk_modulus_gpa:
            raise ValueError("Turner model requires positive bulk moduli for both phases")
        denominator = (
            (1.0 - fraction) * pte_bulk_modulus_gpa
            + fraction * nte_bulk_modulus_gpa
        )
        if denominator <= 0:
            raise ValueError("Turner model produced a non-positive effective bulk modulus")
        return tuple(
            (
                (1.0 - fraction) * pte_bulk_modulus_gpa * p
                + fraction * nte_bulk_modulus_gpa * n
            )
            / denominator
            for p, n in zip(pte_alpha, nte_alpha)
        )
    if model != "kerner":
        raise ValueError(f"Unknown composite thermal-expansion model: {model}")
    if matrix_phase not in {"pte", "nte"}:
        raise ValueError("Kerner matrix_phase must be 'pte' or 'nte'")
    if not pte_bulk_modulus_gpa or not nte_bulk_modulus_gpa:
        raise ValueError("Kerner model requires positive bulk moduli for both phases")
    if matrix_phase == "pte":
        matrix_fraction = 1.0 - fraction
        particle_fraction = fraction
        matrix_bulk = pte_bulk_modulus_gpa
        particle_bulk = nte_bulk_modulus_gpa
        matrix_shear = pte_shear_modulus_gpa
        matrix_alpha = pte_alpha
        particle_alpha = nte_alpha
    else:
        matrix_fraction = fraction
        particle_fraction = 1.0 - fraction
        matrix_bulk = nte_bulk_modulus_gpa
        particle_bulk = pte_bulk_modulus_gpa
        matrix_shear = nte_shear_modulus_gpa
        matrix_alpha = nte_alpha
        particle_alpha = pte_alpha
    if not matrix_shear or matrix_shear <= 0:
        raise ValueError("Kerner model requires a positive shear modulus for the selected matrix phase")
    denominator = (
        matrix_fraction * matrix_bulk
        + particle_fraction * particle_bulk
        + 3.0 * matrix_bulk * particle_bulk / (4.0 * matrix_shear)
    )
    if denominator <= 0:
        raise ValueError("Kerner model produced a non-positive constraint denominator")
    correction_factor = (
        matrix_fraction
        * particle_fraction
        * (particle_bulk - matrix_bulk)
        / denominator
    )
    return tuple(
        matrix_fraction * matrix_value
        + particle_fraction * particle_value
        + correction_factor * (particle_value - matrix_value)
        for matrix_value, particle_value in zip(matrix_alpha, particle_alpha)
    )


def _mass_fraction(
    volume_fraction: float,
    pte_density: float | None,
    nte_density: float | None,
) -> float | None:
    if pte_density is None and nte_density is None:
        return None
    if not pte_density or not nte_density or pte_density <= 0 or nte_density <= 0:
        raise ValueError("Both positive phase densities are required for mass fraction")
    denominator = volume_fraction * nte_density + (1.0 - volume_fraction) * pte_density
    return volume_fraction * nte_density / denominator


def _zte_intervals(
    temperatures_k: list[float] | None,
    errors: list[float],
    tolerance: float,
) -> tuple[float, float | None, tuple[tuple[float, float], ...]]:
    if not temperatures_k:
        coverage = sum(abs(error) <= tolerance for error in errors) / len(errors)
        return coverage, None, ()
    if len(temperatures_k) != len(errors):
        raise ValueError("temperatures_k must have the same length as the curves")
    if any(right <= left for left, right in zip(temperatures_k, temperatures_k[1:])):
        raise ValueError("temperatures_k must be strictly increasing")
    total_span = temperatures_k[-1] - temperatures_k[0]
    if total_span <= 0:
        return float(abs(errors[0]) <= tolerance), 0.0, ()

    intervals: list[tuple[float, float]] = []
    covered_span = 0.0
    for left_t, right_t, left_error, right_error in zip(
        temperatures_k,
        temperatures_k[1:],
        errors,
        errors[1:],
    ):
        fractions = [0.0, 1.0]
        if right_error != left_error:
            for boundary in (-tolerance, tolerance):
                crossing = (boundary - left_error) / (right_error - left_error)
                if 0.0 < crossing < 1.0:
                    fractions.append(crossing)
        fractions = sorted(set(fractions))
        for start_fraction, end_fraction in zip(fractions, fractions[1:]):
            middle_fraction = (start_fraction + end_fraction) / 2.0
            middle_error = left_error + middle_fraction * (right_error - left_error)
            if abs(middle_error) > tolerance:
                continue
            start_t = left_t + start_fraction * (right_t - left_t)
            end_t = left_t + end_fraction * (right_t - left_t)
            covered_span += end_t - start_t
            if intervals and abs(intervals[-1][1] - start_t) < 1e-9:
                intervals[-1] = (intervals[-1][0], end_t)
            else:
                intervals.append((start_t, end_t))
    return covered_span / total_span, covered_span, tuple(intervals)


def _curve_mse(curve: tuple[float, ...], target_alpha: float) -> float:
    return sum((value - target_alpha) ** 2 for value in curve) / len(curve)


def _optimize_fraction_numerically(
    pte_alpha: list[float],
    nte_alpha: list[float],
    target_alpha: float,
    *,
    model: str,
    pte_bulk_modulus_gpa: float | None,
    nte_bulk_modulus_gpa: float | None,
    pte_shear_modulus_gpa: float | None,
    nte_shear_modulus_gpa: float | None,
    matrix_phase: str,
) -> float:
    def objective(fraction: float) -> float:
        return _curve_mse(
            mix_curve(
                pte_alpha,
                nte_alpha,
                fraction,
                model=model,
                pte_bulk_modulus_gpa=pte_bulk_modulus_gpa,
                nte_bulk_modulus_gpa=nte_bulk_modulus_gpa,
                pte_shear_modulus_gpa=pte_shear_modulus_gpa,
                nte_shear_modulus_gpa=nte_shear_modulus_gpa,
                matrix_phase=matrix_phase,
            ),
            target_alpha,
        )

    divisions = 2000
    coarse = [(index / divisions, objective(index / divisions)) for index in range(divisions + 1)]
    best_index = min(range(len(coarse)), key=lambda index: coarse[index][1])
    left = coarse[max(0, best_index - 1)][0]
    right = coarse[min(divisions, best_index + 1)][0]
    golden_ratio = (sqrt(5.0) - 1.0) / 2.0
    x1 = right - golden_ratio * (right - left)
    x2 = left + golden_ratio * (right - left)
    y1 = objective(x1)
    y2 = objective(x2)
    for _ in range(60):
        if y1 <= y2:
            right = x2
            x2, y2 = x1, y1
            x1 = right - golden_ratio * (right - left)
            y1 = objective(x1)
        else:
            left = x1
            x1, y1 = x2, y2
            x2 = left + golden_ratio * (right - left)
            y2 = objective(x2)
    candidates = [coarse[best_index][0], left, right, (left + right) / 2.0]
    return min(candidates, key=objective)


def _effective_nte_weight(
    fraction: float,
    *,
    model: str,
    pte_bulk_modulus_gpa: float | None,
    nte_bulk_modulus_gpa: float | None,
    pte_shear_modulus_gpa: float | None,
    nte_shear_modulus_gpa: float | None,
    matrix_phase: str,
) -> float:
    if model == "linear_rom":
        return fraction
    if model == "turner":
        denominator = (
            (1.0 - fraction) * float(pte_bulk_modulus_gpa)
            + fraction * float(nte_bulk_modulus_gpa)
        )
        return fraction * float(nte_bulk_modulus_gpa) / denominator
    basis = mix_curve(
        [0.0, 0.0],
        [1.0, 1.0],
        fraction,
        model=model,
        pte_bulk_modulus_gpa=pte_bulk_modulus_gpa,
        nte_bulk_modulus_gpa=nte_bulk_modulus_gpa,
        pte_shear_modulus_gpa=pte_shear_modulus_gpa,
        nte_shear_modulus_gpa=nte_shear_modulus_gpa,
        matrix_phase=matrix_phase,
    )
    return basis[0]


def optimize_curve_model(
    pte_alpha: list[float],
    nte_alpha: list[float],
    target_alpha: float = 0.0,
    *,
    model: str = "linear_rom",
    temperatures_k: list[float] | None = None,
    pte_density: float | None = None,
    nte_density: float | None = None,
    pte_bulk_modulus_gpa: float | None = None,
    nte_bulk_modulus_gpa: float | None = None,
    pte_shear_modulus_gpa: float | None = None,
    nte_shear_modulus_gpa: float | None = None,
    matrix_phase: str = "pte",
    zte_tolerance_ppm_per_k: float = 5.0,
) -> CurveROMResult:
    _validate_curves(pte_alpha, nte_alpha)
    if model not in MODEL_METADATA:
        raise ValueError(f"Unknown composite thermal-expansion model: {model}")
    if zte_tolerance_ppm_per_k <= 0:
        raise ValueError("ZTE tolerance must be positive")

    if model == "kerner":
        fraction = _optimize_fraction_numerically(
            pte_alpha,
            nte_alpha,
            target_alpha,
            model=model,
            pte_bulk_modulus_gpa=pte_bulk_modulus_gpa,
            nte_bulk_modulus_gpa=nte_bulk_modulus_gpa,
            pte_shear_modulus_gpa=pte_shear_modulus_gpa,
            nte_shear_modulus_gpa=nte_shear_modulus_gpa,
            matrix_phase=matrix_phase,
        )
        thermal_weight = _effective_nte_weight(
            fraction,
            model=model,
            pte_bulk_modulus_gpa=pte_bulk_modulus_gpa,
            nte_bulk_modulus_gpa=nte_bulk_modulus_gpa,
            pte_shear_modulus_gpa=pte_shear_modulus_gpa,
            nte_shear_modulus_gpa=nte_shear_modulus_gpa,
            matrix_phase=matrix_phase,
        )
    else:
        delta = [n - p for p, n in zip(pte_alpha, nte_alpha)]
        offset = [p - target_alpha for p in pte_alpha]
        denominator = sum(value * value for value in delta)
        thermal_weight = (
            0.0
            if denominator == 0
            else -sum(a * b for a, b in zip(offset, delta)) / denominator
        )
        thermal_weight = min(1.0, max(0.0, thermal_weight))
        fraction = _thermal_weight_to_volume_fraction(
            thermal_weight,
            model=model,
            pte_bulk_modulus_gpa=pte_bulk_modulus_gpa,
            nte_bulk_modulus_gpa=nte_bulk_modulus_gpa,
        )
    mixed = mix_curve(
        pte_alpha,
        nte_alpha,
        fraction,
        model=model,
        pte_bulk_modulus_gpa=pte_bulk_modulus_gpa,
        nte_bulk_modulus_gpa=nte_bulk_modulus_gpa,
        pte_shear_modulus_gpa=pte_shear_modulus_gpa,
        nte_shear_modulus_gpa=nte_shear_modulus_gpa,
        matrix_phase=matrix_phase,
    )
    errors = [value - target_alpha for value in mixed]
    coverage, temperature_span, ranges = _zte_intervals(
        temperatures_k,
        errors,
        zte_tolerance_ppm_per_k,
    )
    metadata = MODEL_METADATA[model]
    model_label = metadata["label"]
    result_matrix_phase = None
    if model == "kerner":
        result_matrix_phase = matrix_phase
        model_label = f"{model_label}（{matrix_phase.upper()}基体）"
    return CurveROMResult(
        model=model,
        model_label=model_label,
        formula=metadata["formula"],
        assumptions=metadata["assumptions"],
        matrix_phase=result_matrix_phase,
        nte_volume_fraction=fraction,
        nte_mass_fraction=_mass_fraction(fraction, pte_density, nte_density),
        effective_nte_thermal_weight=thermal_weight,
        rms_error_ppm_per_k=sqrt(sum(value * value for value in errors) / len(errors)),
        mean_absolute_error_ppm_per_k=sum(abs(value) for value in errors) / len(errors),
        mean_error_ppm_per_k=sum(errors) / len(errors),
        max_absolute_error_ppm_per_k=max(abs(value) for value in errors),
        zte_tolerance_ppm_per_k=zte_tolerance_ppm_per_k,
        zte_temperature_coverage_fraction=coverage,
        zte_temperature_span_k=temperature_span,
        zte_temperature_ranges_k=ranges,
        mixed_alpha_ppm_per_k=mixed,
    )


def optimize_curve_rom(
    pte_alpha: list[float],
    nte_alpha: list[float],
    target_alpha: float = 0.0,
    *,
    temperatures_k: list[float] | None = None,
    pte_density: float | None = None,
    nte_density: float | None = None,
    zte_tolerance_ppm_per_k: float = 5.0,
) -> CurveROMResult:
    return optimize_curve_model(
        pte_alpha,
        nte_alpha,
        target_alpha,
        model="linear_rom",
        temperatures_k=temperatures_k,
        pte_density=pte_density,
        nte_density=nte_density,
        zte_tolerance_ppm_per_k=zte_tolerance_ppm_per_k,
    )


def optimize_curve_turner(
    pte_alpha: list[float],
    nte_alpha: list[float],
    target_alpha: float = 0.0,
    *,
    temperatures_k: list[float] | None = None,
    pte_density: float | None = None,
    nte_density: float | None = None,
    pte_bulk_modulus_gpa: float,
    nte_bulk_modulus_gpa: float,
    zte_tolerance_ppm_per_k: float = 5.0,
) -> CurveROMResult:
    return optimize_curve_model(
        pte_alpha,
        nte_alpha,
        target_alpha,
        model="turner",
        temperatures_k=temperatures_k,
        pte_density=pte_density,
        nte_density=nte_density,
        pte_bulk_modulus_gpa=pte_bulk_modulus_gpa,
        nte_bulk_modulus_gpa=nte_bulk_modulus_gpa,
        zte_tolerance_ppm_per_k=zte_tolerance_ppm_per_k,
    )


def optimize_curve_kerner(
    pte_alpha: list[float],
    nte_alpha: list[float],
    target_alpha: float = 0.0,
    *,
    temperatures_k: list[float] | None = None,
    pte_density: float | None = None,
    nte_density: float | None = None,
    pte_bulk_modulus_gpa: float,
    nte_bulk_modulus_gpa: float,
    pte_shear_modulus_gpa: float,
    nte_shear_modulus_gpa: float,
    matrix_phase: str = "pte",
    zte_tolerance_ppm_per_k: float = 5.0,
) -> CurveROMResult:
    return optimize_curve_model(
        pte_alpha,
        nte_alpha,
        target_alpha,
        model="kerner",
        temperatures_k=temperatures_k,
        pte_density=pte_density,
        nte_density=nte_density,
        pte_bulk_modulus_gpa=pte_bulk_modulus_gpa,
        nte_bulk_modulus_gpa=nte_bulk_modulus_gpa,
        pte_shear_modulus_gpa=pte_shear_modulus_gpa,
        nte_shear_modulus_gpa=nte_shear_modulus_gpa,
        matrix_phase=matrix_phase,
        zte_tolerance_ppm_per_k=zte_tolerance_ppm_per_k,
    )
