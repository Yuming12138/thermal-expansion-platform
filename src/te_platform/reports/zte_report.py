from __future__ import annotations

from datetime import UTC, datetime
from io import BytesIO
from typing import Any

import matplotlib

matplotlib.use("Agg")

from matplotlib import pyplot as plt  # noqa: E402
from matplotlib.backends.backend_pdf import PdfPages  # noqa: E402

from te_platform.reports.material_report import REPORT_COLORS


def _generated_at() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")


def _number(value: Any, digits: int = 2) -> str:
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return "-"


def _longest_span(design: dict[str, Any]) -> float:
    return max(
        (float(end) - float(start) for start, end in design.get("zte_temperature_ranges_k") or []),
        default=0.0,
    )


def _constraint_summary(parameters: dict[str, Any]) -> str:
    parts = []
    if parameters.get("required_elements"):
        parts.append("required elements=" + ",".join(parameters["required_elements"]))
    if parameters.get("excluded_elements"):
        parts.append("excluded elements=" + ",".join(parameters["excluded_elements"]))
    if parameters.get("require_mass_fraction"):
        parts.append("density required")
    if parameters.get("require_complete_mechanics"):
        parts.append("complete K/G required")
    for key, label in (
        ("max_density_ratio", "density ratio"),
        ("max_bulk_modulus_ratio", "K ratio"),
        ("max_shear_modulus_ratio", "G ratio"),
    ):
        if parameters.get(key) is not None:
            parts.append(f"{label}<={parameters[key]}")
    return " | ".join(parts) or "No additional engineering constraints"


def build_zte_screening_report_pdf(payload: dict[str, Any]) -> bytes:
    designs = payload.get("designs") or []
    ranked_results = payload.get("ranked_results") or []
    parameters = payload.get("screening_parameters") or {}
    project_name = str(payload.get("project_name") or "ZTE screening report")
    if not 1 <= len(designs) <= 6:
        raise ValueError("ZTE screening PDF requires between 1 and 6 selected pairs")
    output = BytesIO()
    metadata = {
        "Title": project_name,
        "Author": "Thermal Expansion Materials Platform",
        "Subject": "Full-catalog ZTE pair screening and candidate comparison",
        "Keywords": "ZTE, thermal expansion, composite, screening, ROM, Turner, Kerner",
    }
    display_title = project_name if project_name.isascii() else "ZTE screening report"
    with PdfPages(output, metadata=metadata) as pdf:
        figure = plt.figure(figsize=(11.69, 8.27), constrained_layout=True)
        grid = figure.add_gridspec(2, 2, height_ratios=(1.0, 1.8))
        table_axis = figure.add_subplot(grid[0, :])
        curve_axis = figure.add_subplot(grid[1, 0])
        pareto_axis = figure.add_subplot(grid[1, 1])
        table_axis.axis("off")
        rows = []
        single_model_results = designs[0].get("model_results") if len(designs) == 1 else None
        if single_model_results:
            for model_name, model_result in single_model_results.items():
                mass_fraction = model_result.get("nte_mass_fraction")
                rows.append(
                    [
                        str(model_result.get("model_label") or model_name),
                        str((designs[0].get("pte_material") or {}).get("formula") or "-"),
                        str((designs[0].get("nte_material") or {}).get("formula") or "-"),
                        _number(float(model_result["nte_volume_fraction"]) * 100),
                        (_number(float(mass_fraction) * 100) if mass_fraction is not None else "-"),
                        _number(float(model_result["zte_temperature_coverage_fraction"]) * 100, 1),
                        _number(model_result.get("rms_error_ppm_per_k")),
                        _number(_longest_span(model_result)),
                    ]
                )
            table_labels = ["Model", "PTE", "NTE", "NTE vol.%", "NTE mass.%", "Coverage %", "RMS", "Longest K"]
        else:
            for index, design in enumerate(designs):
                mass_fraction = design.get("nte_mass_fraction")
                rows.append(
                    [
                        str(design.get("rank") or index + 1),
                        str((design.get("pte_material") or {}).get("formula") or "-"),
                        str((design.get("nte_material") or {}).get("material_key") or "-"),
                        _number(float(design["nte_volume_fraction"]) * 100),
                        (_number(float(mass_fraction) * 100) if mass_fraction is not None else "-"),
                        _number(float(design["zte_temperature_coverage_fraction"]) * 100, 1),
                        _number(design.get("rms_error_ppm_per_k")),
                        _number(_longest_span(design)),
                    ]
                )
            table_labels = ["Rank", "PTE", "NTE", "NTE vol.%", "NTE mass.%", "Coverage %", "RMS", "Longest K"]
        table = table_axis.table(
            cellText=rows,
            colLabels=table_labels,
            cellLoc="center",
            colLoc="center",
            loc="center",
        )
        table.auto_set_font_size(False)
        table.set_fontsize(7.4)
        table.scale(1, 1.35)
        for (row_index, _), cell in table.get_celld().items():
            cell.set_edgecolor("#d8e0e7")
            if row_index == 0:
                cell.set_facecolor("#eaf3f6")
                cell.set_text_props(weight="bold", color="#27475a")
        table_axis.set_title(
            f"{display_title} | {parameters.get('model', '-')} | "
            f"{parameters.get('temperature_min_k', '-')}–{parameters.get('temperature_max_k', '-')} K",
            fontsize=13,
            fontweight="bold",
            pad=12,
        )

        target = float(parameters.get("target_alpha_ppm_per_k", 0.0))
        tolerance = float(parameters.get("zte_tolerance_ppm_per_k", 5.0))
        target_points = parameters.get("target_curve_points") or []
        target_temperatures = []
        target_values = []
        if designs:
            target_temperatures = [
                float(value) for value in designs[0].get("target_temperatures_k", [])
            ]
            target_values = [
                float(value) for value in designs[0].get("target_alpha_curve_ppm_per_k", [])
            ]
        if len(target_temperatures) != len(target_values) or len(target_temperatures) < 2:
            target_temperatures = [
                float(parameters.get("temperature_min_k", 300)),
                float(parameters.get("temperature_max_k", 800)),
            ]
            target_values = [target, target]
        if single_model_results:
            design = designs[0]
            temperatures = [float(value) for value in design["temperatures_k"]]
            curve_axis.plot(
                temperatures,
                [float(value) for value in design["pte_alpha_ppm_per_k"]],
                color="#d84a3a",
                linewidth=1.1,
                linestyle="--",
                label="PTE source curve",
            )
            curve_axis.plot(
                temperatures,
                [float(value) for value in design["nte_alpha_ppm_per_k"]],
                color="#2864c7",
                linewidth=1.1,
                linestyle="--",
                label="NTE source curve",
            )
            for index, (model_name, model_result) in enumerate(single_model_results.items()):
                curve_axis.plot(
                    temperatures,
                    [float(value) for value in model_result["mixed_alpha_ppm_per_k"]],
                    color=REPORT_COLORS[index % len(REPORT_COLORS)],
                    linewidth=1.8,
                    label=str(model_result.get("model_label") or model_name),
                )
        else:
            for index, design in enumerate(designs):
                curve_axis.plot(
                    [float(value) for value in design["temperatures_k"]],
                    [float(value) for value in design["mixed_alpha_ppm_per_k"]],
                    color=REPORT_COLORS[index % len(REPORT_COLORS)],
                    linewidth=1.8,
                    label=(
                        f"{(design.get('pte_material') or {}).get('formula', '-')} + "
                        f"{(design.get('nte_material') or {}).get('material_key', '-')}"
                    ),
                )
        curve_axis.fill_between(
            target_temperatures,
            [value - tolerance for value in target_values],
            [value + tolerance for value in target_values],
            color="#16836a",
            alpha=0.12,
        )
        curve_axis.plot(
            target_temperatures,
            target_values,
            color="#16836a",
            linewidth=1.2,
            linestyle="--",
            label="Target alpha(T)",
        )
        curve_axis.set_xlabel("Temperature T (K)")
        curve_axis.set_ylabel("Composite alpha (ppm/K)")
        curve_axis.set_title("Selected composite curves")
        curve_axis.grid(True, color="#e2e8ee", linewidth=0.7)
        curve_axis.legend(fontsize=6.4, loc="best")

        if ranked_results:
            fractions = [float(item["nte_volume_fraction"]) * 100 for item in ranked_results]
            rms = [float(item["rms_error_ppm_per_k"]) for item in ranked_results]
            coverage = [float(item["zte_temperature_coverage_fraction"]) * 100 for item in ranked_results]
            scatter = pareto_axis.scatter(
                fractions,
                rms,
                c=coverage,
                cmap="viridis",
                s=32,
                alpha=0.78,
                edgecolors="none",
            )
            figure.colorbar(scatter, ax=pareto_axis, label="Target coverage (%)")
        for index, design in enumerate(designs):
            pareto_axis.scatter(
                [float(design["nte_volume_fraction"]) * 100],
                [float(design["rms_error_ppm_per_k"])],
                marker="*",
                s=120,
                color=REPORT_COLORS[index % len(REPORT_COLORS)],
                edgecolors="#1e3444",
                linewidths=0.6,
                zorder=5,
            )
        pareto_axis.set_xlabel("NTE volume fraction (%)")
        pareto_axis.set_ylabel("RMS error (ppm/K)")
        pareto_axis.set_title("Screening Pareto landscape")
        pareto_axis.grid(True, color="#e2e8ee", linewidth=0.7)
        figure.text(
            0.01,
            0.025,
            _constraint_summary(parameters),
            fontsize=6.8,
            color="#647586",
        )
        figure.text(
            0.01,
            0.008,
            (
                f"Generated {_generated_at()} | target="
                f"{'piecewise alpha(T), ' + str(len(target_points)) + ' points' if target_points else f'{target:g} ppm/K'}"
                f" | tolerance=±{tolerance:g} ppm/K | "
                "Ranking: coverage, longest continuous span, RMS, maximum error."
            ),
            fontsize=7.2,
            color="#647586",
        )
        pdf.savefig(figure)
        plt.close(figure)
    return output.getvalue()
