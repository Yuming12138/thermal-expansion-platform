from __future__ import annotations

import heapq
import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from time import perf_counter
from typing import Any

import numpy as np
from pymatgen.core import Element

from te_platform.composites.curve_rom import optimize_curve_model
from te_platform.db.schema import connect_readonly_database


@dataclass(frozen=True)
class CurveRecord:
    material_key: str
    formula: str | None
    bulk_modulus_gpa: float | None
    shear_modulus_gpa: float | None
    density_g_cm3: float | None
    elements: frozenset[str]
    temperatures_k: tuple[float, ...]
    alpha_ppm_per_k: tuple[float, ...]


def _database_signature(database: str | Path) -> tuple[str, int, int]:
    path = Path(database).resolve()
    stat = path.stat()
    return str(path), stat.st_mtime_ns, stat.st_size


@lru_cache(maxsize=8)
def _release_records(
    database_path: str,
    database_mtime_ns: int,
    database_size: int,
    release_slug: str,
) -> tuple[CurveRecord, ...]:
    del database_mtime_ns, database_size
    with connect_readonly_database(database_path) as connection:
        rows = connection.execute(
            """SELECT m.material_key, m.formula, j.updated_at, c.points_json,
                MAX(CASE WHEN mp.name = 'K_GPa' THEN mp.numeric_value END) AS K_GPa,
                MAX(CASE WHEN mp.name = 'G_GPa' THEN mp.numeric_value END) AS G_GPa,
                (SELECT s.content FROM structures s
                 WHERE s.dataset_release_id = dr.id AND s.material_id = m.id
                 ORDER BY CASE WHEN UPPER(s.format) = 'POSCAR' THEN 0 ELSE 1 END, s.id
                 LIMIT 1) AS structure_content
            FROM dataset_releases dr
            JOIN dataset_memberships dm ON dm.dataset_release_id = dr.id
            JOIN materials m ON m.id = dm.material_id
            JOIN calculation_jobs j ON j.material_id = m.id AND j.status = 'SUCCEEDED'
            JOIN precision_thermal_expansion_curves c ON c.job_id = j.id
            LEFT JOIN material_properties mp
              ON mp.dataset_release_id = dr.id AND mp.material_id = m.id
            WHERE dr.slug = ?
            GROUP BY m.id, j.id, c.job_id
            ORDER BY m.material_key, j.updated_at DESC, j.id DESC""",
            (release_slug,),
        ).fetchall()
    records: list[CurveRecord] = []
    seen: set[str] = set()
    for row in rows:
        material_key = str(row["material_key"])
        if material_key in seen:
            continue
        points = json.loads(row["points_json"])
        if len(points) < 2:
            continue
        temperatures = tuple(float(point[0]) for point in points)
        alpha = tuple(float(point[1]) * 1_000_000.0 for point in points)
        if any(right <= left for left, right in zip(temperatures, temperatures[1:])):
            continue
        density_g_cm3, structure_elements = _poscar_metadata(row["structure_content"])
        records.append(
            CurveRecord(
                material_key=material_key,
                formula=row["formula"],
                bulk_modulus_gpa=(
                    float(row["K_GPa"]) if row["K_GPa"] is not None else None
                ),
                shear_modulus_gpa=(
                    float(row["G_GPa"]) if row["G_GPa"] is not None else None
                ),
                density_g_cm3=density_g_cm3,
                elements=structure_elements or frozenset(
                    re.findall(r"[A-Z][a-z]?", str(row["formula"] or ""))
                ),
                temperatures_k=temperatures,
                alpha_ppm_per_k=alpha,
            )
        )
        seen.add(material_key)
    return tuple(records)


def _poscar_metadata(content: str | None) -> tuple[float | None, frozenset[str]]:
    if not content:
        return None, frozenset()
    try:
        lines = [line.strip() for line in str(content).splitlines() if line.strip()]
        if len(lines) < 7:
            return None
        scale = float(lines[1].split()[0])
        lattice = np.asarray(
            [[float(value) for value in lines[index].split()[:3]] for index in range(2, 5)],
            dtype=float,
        )
        raw_volume = abs(float(np.linalg.det(lattice)))
        if raw_volume <= 0:
            return None, frozenset()
        volume_a3 = -scale if scale < 0 else raw_volume * scale**3
        species = lines[5].split()
        counts = [int(value) for value in lines[6].split()]
        if len(species) != len(counts) or not all(Element.is_valid_symbol(symbol) for symbol in species):
            return None, frozenset()
        mass_amu = sum(float(Element(symbol).atomic_mass) * count for symbol, count in zip(species, counts))
        return mass_amu * 1.66053906660 / volume_a3, frozenset(species)
    except (IndexError, TypeError, ValueError):
        return None, frozenset()


def _normalize_elements(values: tuple[str, ...] | list[str] | None, field_name: str) -> frozenset[str]:
    normalized = frozenset(str(value).strip().capitalize() for value in (values or ()) if str(value).strip())
    invalid = sorted(symbol for symbol in normalized if not Element.is_valid_symbol(symbol))
    if invalid:
        raise ValueError(f"{field_name} contains invalid element symbols: {', '.join(invalid)}")
    return normalized


def _ratio_mask(reference: float | None, values: np.ndarray, maximum_ratio: float | None) -> np.ndarray:
    if maximum_ratio is None:
        return np.ones(values.shape, dtype=bool)
    if reference is None or not np.isfinite(reference) or reference <= 0:
        return np.zeros(values.shape, dtype=bool)
    valid = np.isfinite(values) & (values > 0)
    ratios = np.full(values.shape, np.inf, dtype=float)
    ratios[valid] = np.maximum(reference / values[valid], values[valid] / reference)
    return ratios <= maximum_ratio + 1e-12


def _symmetric_ratio(first: float | None, second: float | None) -> float | None:
    if first is None or second is None:
        return None
    if not np.isfinite(first) or not np.isfinite(second) or first <= 0 or second <= 0:
        return None
    return max(first / second, second / first)


def _matches_query(record: CurveRecord, query: str) -> bool:
    if not query:
        return True
    needle = query.casefold()
    return needle in record.material_key.casefold() or needle in (record.formula or "").casefold()


def _eligible_records(
    database: str | Path,
    release_slug: str,
    temperatures_k: np.ndarray,
    *,
    role: str,
    query: str,
    model: str,
    matrix_phase: str,
) -> tuple[list[CurveRecord], np.ndarray]:
    database_path, mtime_ns, size = _database_signature(database)
    records = _release_records(database_path, mtime_ns, size, release_slug)
    selected: list[CurveRecord] = []
    curves: list[np.ndarray] = []
    start = float(temperatures_k[0])
    end = float(temperatures_k[-1])
    for record in records:
        if not _matches_query(record, query):
            continue
        if record.temperatures_k[0] > start or record.temperatures_k[-1] < end:
            continue
        if model in {"turner", "kerner"} and not (
            record.bulk_modulus_gpa and record.bulk_modulus_gpa > 0
        ):
            continue
        if model == "kerner" and matrix_phase == role:
            if not (record.shear_modulus_gpa and record.shear_modulus_gpa > 0):
                continue
        selected.append(record)
        curves.append(
            np.interp(
                temperatures_k,
                np.asarray(record.temperatures_k, dtype=float),
                np.asarray(record.alpha_ppm_per_k, dtype=float),
            )
        )
    if not curves:
        return selected, np.empty((0, len(temperatures_k)), dtype=float)
    return selected, np.vstack(curves)


def _volume_fractions(
    thermal_weights: np.ndarray,
    *,
    model: str,
    matrix_phase: str,
    pte_bulk_modulus_gpa: float | None,
    pte_shear_modulus_gpa: float | None,
    nte_bulk_moduli_gpa: np.ndarray,
    nte_shear_moduli_gpa: np.ndarray,
) -> np.ndarray:
    weights = np.clip(np.asarray(thermal_weights, dtype=float), 0.0, 1.0)
    if model == "linear_rom":
        return weights
    pte_bulk = float(pte_bulk_modulus_gpa)
    if model == "turner":
        denominator = nte_bulk_moduli_gpa * (1.0 - weights) + weights * pte_bulk
        return np.divide(
            weights * pte_bulk,
            denominator,
            out=np.zeros_like(weights),
            where=denominator > 0,
        )
    if model != "kerner":
        raise ValueError(f"Unknown composite thermal-expansion model: {model}")
    if matrix_phase == "pte":
        pte_shear = float(pte_shear_modulus_gpa)
        constraint = 3.0 * pte_bulk * nte_bulk_moduli_gpa / (4.0 * pte_shear)
        denominator = (
            nte_bulk_moduli_gpa
            + constraint
            - weights * (nte_bulk_moduli_gpa - pte_bulk)
        )
        fractions = np.divide(
            weights * (pte_bulk + constraint),
            denominator,
            out=np.zeros_like(weights),
            where=denominator > 0,
        )
        return np.clip(fractions, 0.0, 1.0)
    if matrix_phase != "nte":
        raise ValueError("Kerner matrix_phase must be 'pte' or 'nte'")
    particle_weights = 1.0 - weights
    constraint = 3.0 * nte_bulk_moduli_gpa * pte_bulk / (4.0 * nte_shear_moduli_gpa)
    denominator = (
        pte_bulk
        + constraint
        - particle_weights * (pte_bulk - nte_bulk_moduli_gpa)
    )
    particle_fractions = np.divide(
        particle_weights * (nte_bulk_moduli_gpa + constraint),
        denominator,
        out=np.zeros_like(weights),
        where=denominator > 0,
    )
    return np.clip(1.0 - particle_fractions, 0.0, 1.0)


def _continuous_band_metrics(
    errors: np.ndarray,
    temperatures_k: np.ndarray,
    tolerance: float,
) -> tuple[np.ndarray, np.ndarray]:
    pair_count = errors.shape[0]
    covered_span = np.zeros(pair_count, dtype=float)
    longest_span = np.zeros(pair_count, dtype=float)
    current_span = np.zeros(pair_count, dtype=float)
    for index in range(errors.shape[1] - 1):
        left = errors[:, index]
        right = errors[:, index + 1]
        slope = right - left
        interval = float(temperatures_k[index + 1] - temperatures_k[index])
        flat = np.abs(slope) < 1e-14
        start = np.zeros(pair_count, dtype=float)
        end = np.zeros(pair_count, dtype=float)
        inside_flat = flat & (np.abs(left) <= tolerance)
        end[inside_flat] = 1.0
        changing = ~flat
        if np.any(changing):
            crossing_a = (-tolerance - left[changing]) / slope[changing]
            crossing_b = (tolerance - left[changing]) / slope[changing]
            start[changing] = np.maximum(0.0, np.minimum(crossing_a, crossing_b))
            end[changing] = np.minimum(1.0, np.maximum(crossing_a, crossing_b))
        width = np.maximum(0.0, end - start)
        segment_span = width * interval
        covered_span += segment_span
        has_coverage = width > 0
        continues_from_left = start <= 1e-12
        run_span = np.where(
            has_coverage & continues_from_left,
            current_span + segment_span,
            np.where(has_coverage, segment_span, 0.0),
        )
        longest_span = np.maximum(longest_span, run_span)
        continues_to_right = end >= 1.0 - 1e-12
        current_span = np.where(has_coverage & continues_to_right, run_span, 0.0)
    total_span = float(temperatures_k[-1] - temperatures_k[0])
    return covered_span / total_span, longest_span


def screen_material_pairs(
    database: str | Path,
    *,
    pte_release_slug: str,
    nte_release_slug: str,
    temperature_min_k: float = 300.0,
    temperature_max_k: float = 800.0,
    temperature_step_k: float = 10.0,
    target_alpha_ppm_per_k: float = 0.0,
    zte_tolerance_ppm_per_k: float = 5.0,
    model: str = "linear_rom",
    matrix_phase: str = "pte",
    pte_query: str = "",
    nte_query: str = "",
    nte_volume_fraction_min: float = 0.0,
    nte_volume_fraction_max: float = 1.0,
    require_matrix_majority: bool = False,
    required_elements: tuple[str, ...] | list[str] | None = None,
    excluded_elements: tuple[str, ...] | list[str] | None = None,
    require_mass_fraction: bool = False,
    require_complete_mechanics: bool = False,
    max_density_ratio: float | None = None,
    max_bulk_modulus_ratio: float | None = None,
    max_shear_modulus_ratio: float | None = None,
    limit: int = 30,
) -> dict[str, Any]:
    started = perf_counter()
    if temperature_max_k <= temperature_min_k:
        raise ValueError("temperature_max_k must be greater than temperature_min_k")
    if temperature_step_k <= 0:
        raise ValueError("temperature_step_k must be positive")
    if zte_tolerance_ppm_per_k <= 0:
        raise ValueError("zte_tolerance_ppm_per_k must be positive")
    if model not in {"linear_rom", "turner", "kerner"}:
        raise ValueError("model must be linear_rom, turner, or kerner")
    if matrix_phase not in {"pte", "nte"}:
        raise ValueError("matrix_phase must be pte or nte")
    if not 0 <= nte_volume_fraction_min <= nte_volume_fraction_max <= 1:
        raise ValueError("NTE volume-fraction limits must satisfy 0 <= min <= max <= 1")
    if not 1 <= limit <= 100:
        raise ValueError("limit must be between 1 and 100")
    for value, name in (
        (max_density_ratio, "max_density_ratio"),
        (max_bulk_modulus_ratio, "max_bulk_modulus_ratio"),
        (max_shear_modulus_ratio, "max_shear_modulus_ratio"),
    ):
        if value is not None and value < 1:
            raise ValueError(f"{name} must be at least 1")
    required_element_set = _normalize_elements(required_elements, "required_elements")
    excluded_element_set = _normalize_elements(excluded_elements, "excluded_elements")
    if required_element_set & excluded_element_set:
        overlap = ", ".join(sorted(required_element_set & excluded_element_set))
        raise ValueError(f"required_elements and excluded_elements overlap: {overlap}")
    estimated_grid_points = int(
        np.ceil((temperature_max_k - temperature_min_k) / temperature_step_k)
    ) + 1
    if estimated_grid_points > 201:
        raise ValueError(
            "全库筛选一次最多支持201个温度采样点，请增大温区步长"
        )

    temperatures = np.arange(
        temperature_min_k,
        temperature_max_k + temperature_step_k * 0.5,
        temperature_step_k,
        dtype=float,
    )
    if temperatures[-1] < temperature_max_k - 1e-9:
        temperatures = np.append(temperatures, temperature_max_k)
    else:
        temperatures[-1] = temperature_max_k
    pte_records, pte_curves = _eligible_records(
        database,
        pte_release_slug,
        temperatures,
        role="pte",
        query=pte_query.strip(),
        model=model,
        matrix_phase=matrix_phase,
    )
    nte_records, nte_curves = _eligible_records(
        database,
        nte_release_slug,
        temperatures,
        role="nte",
        query=nte_query.strip(),
        model=model,
        matrix_phase=matrix_phase,
    )
    if not pte_records or not nte_records:
        return {
            "model": model,
            "matrix_phase": matrix_phase if model == "kerner" else None,
            "temperature_min_k": temperature_min_k,
            "temperature_max_k": temperature_max_k,
            "temperature_step_k": temperature_step_k,
            "target_alpha_ppm_per_k": target_alpha_ppm_per_k,
            "zte_tolerance_ppm_per_k": zte_tolerance_ppm_per_k,
            "required_elements": sorted(required_element_set),
            "excluded_elements": sorted(excluded_element_set),
            "require_mass_fraction": require_mass_fraction,
            "require_complete_mechanics": require_complete_mechanics,
            "max_density_ratio": max_density_ratio,
            "max_bulk_modulus_ratio": max_bulk_modulus_ratio,
            "max_shear_modulus_ratio": max_shear_modulus_ratio,
            "eligible_pte_count": len(pte_records),
            "eligible_nte_count": len(nte_records),
            "evaluated_pair_count": 0,
            "engineering_eligible_pair_count": 0,
            "matched_pair_count": 0,
            "ranking_is_complete": True,
            "elapsed_seconds": perf_counter() - started,
            "results": [],
        }

    nte_bulk = np.asarray([record.bulk_modulus_gpa or np.nan for record in nte_records])
    nte_shear = np.asarray([record.shear_modulus_gpa or np.nan for record in nte_records])
    nte_density = np.asarray([record.density_g_cm3 or np.nan for record in nte_records])
    # A global top-N pair must also be within the top N of its own PTE block.
    # Keeping more than N locally and globally preserves the requested complete ranking
    # without materializing metrics for all 1.2 million pairs at once.
    candidate_pool_size = max(1000, limit * 30)
    local_keep = max(100, limit * 5)
    heap: list[
        tuple[tuple[float, float, float, float, float, float, float], int, dict[str, Any]]
    ] = []
    serial = 0
    matched_pair_count = 0
    engineering_eligible_pair_count = 0
    engineering_rejection_counts = {
        "elements": 0,
        "density": 0,
        "bulk_modulus": 0,
        "shear_modulus": 0,
        "mechanics_completeness": 0,
    }
    target = float(target_alpha_ppm_per_k)
    for pte_index, (pte_record, pte_curve) in enumerate(zip(pte_records, pte_curves)):
        delta = nte_curves - pte_curve
        denominator = np.einsum("ij,ij->i", delta, delta)
        offset = pte_curve - target
        numerator = -np.einsum("ij,j->i", delta, offset)
        weights = np.divide(
            numerator,
            denominator,
            out=np.zeros_like(numerator),
            where=denominator > 1e-20,
        )
        weights = np.clip(weights, 0.0, 1.0)
        fractions = _volume_fractions(
            weights,
            model=model,
            matrix_phase=matrix_phase,
            pte_bulk_modulus_gpa=pte_record.bulk_modulus_gpa,
            pte_shear_modulus_gpa=pte_record.shear_modulus_gpa,
            nte_bulk_moduli_gpa=nte_bulk,
            nte_shear_moduli_gpa=nte_shear,
        )
        engineering_valid = np.ones(len(nte_records), dtype=bool)
        if excluded_element_set:
            element_mask = np.asarray(
                [not bool(excluded_element_set & (pte_record.elements | record.elements)) for record in nte_records],
                dtype=bool,
            )
            engineering_rejection_counts["elements"] += int(np.count_nonzero(engineering_valid & ~element_mask))
            engineering_valid &= element_mask
        if required_element_set:
            element_mask = np.asarray(
                [required_element_set.issubset(pte_record.elements | record.elements) for record in nte_records],
                dtype=bool,
            )
            engineering_rejection_counts["elements"] += int(np.count_nonzero(engineering_valid & ~element_mask))
            engineering_valid &= element_mask
        density_mask = _ratio_mask(pte_record.density_g_cm3, nte_density, max_density_ratio)
        if require_mass_fraction:
            density_mask &= np.isfinite(nte_density) & (nte_density > 0)
            if not pte_record.density_g_cm3 or pte_record.density_g_cm3 <= 0:
                density_mask[:] = False
        engineering_rejection_counts["density"] += int(np.count_nonzero(engineering_valid & ~density_mask))
        engineering_valid &= density_mask
        bulk_mask = _ratio_mask(pte_record.bulk_modulus_gpa, nte_bulk, max_bulk_modulus_ratio)
        engineering_rejection_counts["bulk_modulus"] += int(np.count_nonzero(engineering_valid & ~bulk_mask))
        engineering_valid &= bulk_mask
        shear_mask = _ratio_mask(pte_record.shear_modulus_gpa, nte_shear, max_shear_modulus_ratio)
        engineering_rejection_counts["shear_modulus"] += int(np.count_nonzero(engineering_valid & ~shear_mask))
        engineering_valid &= shear_mask
        if require_complete_mechanics:
            mechanics_mask = (
                np.isfinite(nte_bulk) & (nte_bulk > 0) & np.isfinite(nte_shear) & (nte_shear > 0)
            )
            if not (
                pte_record.bulk_modulus_gpa and pte_record.bulk_modulus_gpa > 0
                and pte_record.shear_modulus_gpa and pte_record.shear_modulus_gpa > 0
            ):
                mechanics_mask[:] = False
            engineering_rejection_counts["mechanics_completeness"] += int(
                np.count_nonzero(engineering_valid & ~mechanics_mask)
            )
            engineering_valid &= mechanics_mask
        engineering_eligible_pair_count += int(np.count_nonzero(engineering_valid))
        valid = engineering_valid & (
            (fractions >= nte_volume_fraction_min - 1e-12)
            & (fractions <= nte_volume_fraction_max + 1e-12)
        )
        if model == "kerner" and require_matrix_majority:
            matrix_fraction = 1.0 - fractions if matrix_phase == "pte" else fractions
            valid &= matrix_fraction >= 0.5 - 1e-12
        valid_indices = np.flatnonzero(valid)
        matched_pair_count += int(valid_indices.size)
        if valid_indices.size == 0:
            continue
        mixed = pte_curve + weights[:, None] * delta
        errors = mixed - target
        rms = np.sqrt(np.mean(errors * errors, axis=1))
        max_error = np.max(np.abs(errors), axis=1)
        coverage, longest = _continuous_band_metrics(
            errors,
            temperatures,
            zte_tolerance_ppm_per_k,
        )
        ordering = valid_indices[
            np.lexsort(
                (
                    valid_indices,
                    fractions[valid_indices],
                    max_error[valid_indices],
                    rms[valid_indices],
                    -longest[valid_indices],
                    -coverage[valid_indices],
                )
            )[: min(local_keep, valid_indices.size)]
        ]
        for nte_index in ordering.tolist():
            score = (
                float(coverage[nte_index]),
                float(longest[nte_index]),
                -float(rms[nte_index]),
                -float(max_error[nte_index]),
                -float(fractions[nte_index]),
                -float(pte_index),
                -float(nte_index),
            )
            candidate = {
                "pte_index": pte_index,
                "nte_index": nte_index,
                "thermal_weight": float(weights[nte_index]),
                "nte_volume_fraction": float(fractions[nte_index]),
            }
            item = (score, serial, candidate)
            serial += 1
            if len(heap) < candidate_pool_size:
                heapq.heappush(heap, item)
            elif score > heap[0][0]:
                heapq.heapreplace(heap, item)

    candidates = [item[2] for item in sorted(heap, key=lambda item: item[0], reverse=True)]
    refined: list[dict[str, Any]] = []
    for candidate in candidates:
        pte_index = candidate["pte_index"]
        nte_index = candidate["nte_index"]
        pte_record = pte_records[pte_index]
        nte_record = nte_records[nte_index]
        result = optimize_curve_model(
            pte_curves[pte_index].tolist(),
            nte_curves[nte_index].tolist(),
            target,
            model=model,
            temperatures_k=temperatures.tolist(),
            pte_bulk_modulus_gpa=pte_record.bulk_modulus_gpa,
            nte_bulk_modulus_gpa=nte_record.bulk_modulus_gpa,
            pte_shear_modulus_gpa=pte_record.shear_modulus_gpa,
            nte_shear_modulus_gpa=nte_record.shear_modulus_gpa,
            pte_density=pte_record.density_g_cm3,
            nte_density=nte_record.density_g_cm3,
            matrix_phase=matrix_phase,
            zte_tolerance_ppm_per_k=zte_tolerance_ppm_per_k,
        )
        longest_span = max(
            (end - start for start, end in result.zte_temperature_ranges_k),
            default=0.0,
        )
        matrix_fraction = None
        model_applicable = True
        if model == "kerner":
            matrix_fraction = (
                1.0 - result.nte_volume_fraction
                if matrix_phase == "pte"
                else result.nte_volume_fraction
            )
            model_applicable = matrix_fraction >= 0.5
        refined.append(
            {
                "pte_material_key": pte_record.material_key,
                "pte_formula": pte_record.formula,
                "nte_material_key": nte_record.material_key,
                "nte_formula": nte_record.formula,
                "model": model,
                "model_label": result.model_label,
                "matrix_phase": result.matrix_phase,
                "matrix_volume_fraction": matrix_fraction,
                "model_applicable": model_applicable,
                "nte_volume_fraction": result.nte_volume_fraction,
                "nte_mass_fraction": result.nte_mass_fraction,
                "effective_nte_thermal_weight": result.effective_nte_thermal_weight,
                "rms_error_ppm_per_k": result.rms_error_ppm_per_k,
                "max_absolute_error_ppm_per_k": result.max_absolute_error_ppm_per_k,
                "zte_temperature_coverage_fraction": result.zte_temperature_coverage_fraction,
                "longest_zte_temperature_span_k": longest_span,
                "zte_temperature_ranges_k": result.zte_temperature_ranges_k,
                "pte_bulk_modulus_gpa": pte_record.bulk_modulus_gpa,
                "pte_shear_modulus_gpa": pte_record.shear_modulus_gpa,
                "nte_bulk_modulus_gpa": nte_record.bulk_modulus_gpa,
                "nte_shear_modulus_gpa": nte_record.shear_modulus_gpa,
                "pte_density_g_cm3": pte_record.density_g_cm3,
                "nte_density_g_cm3": nte_record.density_g_cm3,
                "density_ratio": _symmetric_ratio(
                    pte_record.density_g_cm3, nte_record.density_g_cm3
                ),
                "bulk_modulus_ratio": _symmetric_ratio(
                    pte_record.bulk_modulus_gpa, nte_record.bulk_modulus_gpa
                ),
                "shear_modulus_ratio": _symmetric_ratio(
                    pte_record.shear_modulus_gpa, nte_record.shear_modulus_gpa
                ),
            }
        )
    refined.sort(
        key=lambda item: (
            -round(item["zte_temperature_coverage_fraction"], 12),
            -round(item["longest_zte_temperature_span_k"], 12),
            round(item["rms_error_ppm_per_k"], 12),
            round(item["max_absolute_error_ppm_per_k"], 12),
            item["nte_volume_fraction"],
            item["pte_material_key"],
            item["nte_material_key"],
        )
    )
    results = refined[:limit]
    for rank, item in enumerate(results, start=1):
        item["rank"] = rank
    return {
        "model": model,
        "matrix_phase": matrix_phase if model == "kerner" else None,
        "temperature_min_k": temperature_min_k,
        "temperature_max_k": temperature_max_k,
        "temperature_step_k": temperature_step_k,
        "target_alpha_ppm_per_k": target_alpha_ppm_per_k,
        "zte_tolerance_ppm_per_k": zte_tolerance_ppm_per_k,
        "nte_volume_fraction_min": nte_volume_fraction_min,
        "nte_volume_fraction_max": nte_volume_fraction_max,
        "require_matrix_majority": require_matrix_majority,
        "required_elements": sorted(required_element_set),
        "excluded_elements": sorted(excluded_element_set),
        "require_mass_fraction": require_mass_fraction,
        "require_complete_mechanics": require_complete_mechanics,
        "max_density_ratio": max_density_ratio,
        "max_bulk_modulus_ratio": max_bulk_modulus_ratio,
        "max_shear_modulus_ratio": max_shear_modulus_ratio,
        "eligible_pte_count": len(pte_records),
        "eligible_nte_count": len(nte_records),
        "evaluated_pair_count": len(pte_records) * len(nte_records),
        "engineering_eligible_pair_count": engineering_eligible_pair_count,
        "engineering_rejection_counts": engineering_rejection_counts,
        "matched_pair_count": matched_pair_count,
        "candidate_pool_size": len(candidates),
        "ranking_is_complete": True,
        "elapsed_seconds": perf_counter() - started,
        "results": results,
    }
