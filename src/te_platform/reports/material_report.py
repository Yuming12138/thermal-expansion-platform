from __future__ import annotations

from datetime import UTC, datetime
from io import BytesIO
import math
from typing import Any

import matplotlib

matplotlib.use("Agg")

from matplotlib import pyplot as plt  # noqa: E402
from matplotlib.backends.backend_pdf import PdfPages  # noqa: E402


REPORT_COLORS = ("#d84a3a", "#2864c7", "#15906f", "#d98624", "#7b57b2", "#5d6a76")


def _generated_at() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")


def _anisotropic_series(
    detail: dict[str, Any],
    *,
    require_curve: bool = True,
) -> dict[str, tuple[list[float], list[float]]]:
    """Return plotted series from the tensor-aware alpha(T) export.

    The current release stores Cartesian or crystallographic-axis components
    in ``anisotropic_thermal_expansion``.  A legacy scalar curve is accepted
    only as a compatibility fallback for older catalog fixtures; it is not
    used by the current web detail page or release data.
    """
    curves = detail.get("anisotropic_thermal_expansion") or {}
    for kind in ("cartesian", "directional"):
        curve = curves.get(kind) or {}
        points = curve.get("points") or []
        if len(points) < 2:
            continue
        component_keys = (
            ["alpha_xx", "alpha_yy", "alpha_zz"]
            if kind == "cartesian"
            else ["alpha_a", "alpha_b", "alpha_c"]
        )
        keys = component_keys + ["alpha_volume"]
        series: dict[str, tuple[list[float], list[float]]] = {}
        for key in keys:
            pairs: list[tuple[float, float]] = []
            for point in points:
                try:
                    temperature = float(point["T_K"])
                    alpha = float(point[key])
                except (KeyError, TypeError, ValueError):
                    continue
                if math.isfinite(temperature) and math.isfinite(alpha):
                    pairs.append((temperature, alpha))
            if len(pairs) >= 2:
                pairs.sort(key=lambda item: item[0])
                series[key] = ([item[0] for item in pairs], [item[1] for item in pairs])
        if series:
            return series

    # Comparison reports pass the legacy scalar curve under ``curve`` while
    # material detail responses expose it as ``precision_thermal_expansion``.
    # Accept both shapes so old catalogs without tensor-aware rows remain
    # downloadable and reportable.
    curve = detail.get("precision_thermal_expansion") or detail.get("curve") or {}
    points = curve.get("points") or []
    legacy = {
        "alpha_volume": (
            [float(point["temperature_k"]) for point in points],
            [float(point["alpha_ppm_per_k"]) for point in points],
        )
    }
    if len(legacy["alpha_volume"][0]) < 2:
        if not require_curve:
            return {}
        raise ValueError("Material has no stored anisotropic thermal-expansion curve")
    return legacy


def build_material_curve_pdf(detail: dict[str, Any]) -> bytes:
    series = _anisotropic_series(detail)
    material = detail["material"]
    release = detail.get("dataset_release") or {}
    output = BytesIO()
    metadata = {
        "Title": f"Thermal expansion curve - {material['material_key']}",
        "Author": "Thermal Expansion Materials Platform",
        "Subject": "Stored anisotropic thermal expansion data",
        "Keywords": "anisotropic thermal expansion, alpha_V, NTE, materials",
    }
    with PdfPages(output, metadata=metadata) as pdf:
        figure, axis = plt.subplots(figsize=(8.27, 5.83), constrained_layout=True)
        styles = {
            "alpha_xx": ("αxx", "#1d6b83", "--", 1.35),
            "alpha_yy": ("αyy", "#c45b32", "--", 1.35),
            "alpha_zz": ("αzz", "#6e8f3f", "--", 1.35),
            "alpha_a": ("αa", "#1d6b83", "--", 1.35),
            "alpha_b": ("αb", "#c45b32", "--", 1.35),
            "alpha_c": ("αc", "#6e8f3f", "--", 1.35),
            "alpha_volume": ("αV", "#7b57b2", "-", 2.2),
        }
        for key, (temperatures, alphas) in series.items():
            label, color, linestyle, linewidth = styles.get(
                key, (key, "#2864c7", "-", 1.6)
            )
            axis.plot(
                temperatures,
                alphas,
                color=color,
                linewidth=linewidth,
                linestyle=linestyle,
                label=label,
            )
        axis.axhline(0, color="#7d8994", linewidth=1, linestyle="--")
        axis.set_xlabel("Temperature T (K)")
        axis.set_ylabel("Thermal expansion α (ppm/K)")
        axis.grid(True, color="#e2e8ee", linewidth=0.8)
        axis.set_title(material["material_key"], fontsize=13, fontweight="bold")
        curve_source = next(iter((detail.get("anisotropic_thermal_expansion") or {}).values()), {})
        source_name = str(curve_source.get("source_path") or "stored anisotropic curve").replace("\\", "/").split("/")[-1]
        figure.suptitle(
            f"Dataset {release.get('version', '-')} | {source_name}",
            fontsize=8.5,
            color="#556575",
        )
        figure.text(
            0.01,
            0.01,
            f"Generated {_generated_at()} | Cartesian/directional components; values plotted in ppm/K.",
            fontsize=7.5,
            color="#647586",
        )
        axis.legend(fontsize=8, loc="best", frameon=False)
        pdf.savefig(figure)
        plt.close(figure)
    return output.getvalue()


def _metric_text(value: Any, digits: int = 3) -> str:
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return "-"


def build_comparison_report_pdf(
    comparison: dict[str, Any],
    *,
    project_name: str = "Material comparison",
) -> bytes:
    materials = comparison.get("materials") or []
    if not 2 <= len(materials) <= 6:
        raise ValueError("Comparison PDF requires between 2 and 6 materials")
    temperature = float(comparison["temperature_k"])
    display_title = project_name if project_name.isascii() else "Material comparison report"
    output = BytesIO()
    metadata = {
        "Title": project_name,
        "Author": "Thermal Expansion Materials Platform",
        "Subject": "Material property and anisotropic thermal expansion comparison",
        "Keywords": "anisotropic thermal expansion, comparison, NTE, materials",
    }
    with PdfPages(output, metadata=metadata) as pdf:
        figure = plt.figure(figsize=(11.69, 8.27), constrained_layout=True)
        grid = figure.add_gridspec(2, 1, height_ratios=(1.15, 1.85))
        table_axis = figure.add_subplot(grid[0])
        curve_axis = figure.add_subplot(grid[1])
        table_axis.axis("off")
        columns = [
            "Material",
            "G (GPa)",
            "Etilde (GPa)",
            "xi",
            "Catalog αV",
            f"alpha({temperature:g} K)",
        ]
        rows = []
        for item in materials:
            metrics = item["metrics"]
            rows.append(
                [
                    item["material"]["material_key"],
                    _metric_text(metrics.get("G_GPa")),
                    _metric_text(metrics.get("E_tilde_GPa")),
                    _metric_text(metrics.get("xi")),
                    _metric_text(metrics.get("CTE_ppm")),
                    _metric_text(metrics.get("alpha_at_temperature_ppm_per_k")),
                ]
            )
        table = table_axis.table(
            cellText=rows,
            colLabels=columns,
            cellLoc="center",
            colLoc="center",
            loc="center",
        )
        table.auto_set_font_size(False)
        table.set_fontsize(8)
        table.scale(1, 1.45)
        for (row_index, _), cell in table.get_celld().items():
            cell.set_edgecolor("#d8e0e7")
            if row_index == 0:
                cell.set_facecolor("#eaf3f6")
                cell.set_text_props(weight="bold", color="#27475a")
        table_axis.set_title(display_title, fontsize=15, fontweight="bold", pad=16)
        for index, item in enumerate(materials):
            # A comparison can include catalog records without a stored
            # temperature-dependent curve.  Keep those rows in the report
            # table and simply omit their line from the plot.
            curve_data = _anisotropic_series(item, require_curve=False)
            volume = curve_data.get("alpha_volume")
            if volume:
                curve_axis.plot(
                    volume[0],
                    volume[1],
                    label=item["material"]["material_key"],
                    color=REPORT_COLORS[index % len(REPORT_COLORS)],
                    linewidth=2,
                )
            for key, component in curve_data.items():
                if key == "alpha_volume":
                    continue
                curve_axis.plot(
                    component[0],
                    component[1],
                    color=REPORT_COLORS[index % len(REPORT_COLORS)],
                    linewidth=0.9,
                    linestyle="--",
                    alpha=0.42,
                )
        curve_axis.axhline(0, color="#7d8994", linewidth=1, linestyle="--")
        curve_axis.set_xlabel("Temperature T (K)")
        curve_axis.set_ylabel("Thermal expansion α (ppm/K)")
        curve_axis.grid(True, color="#e2e8ee", linewidth=0.8)
        handles, labels = curve_axis.get_legend_handles_labels()
        if labels:
            curve_axis.legend(handles, labels, fontsize=7.5, loc="best")
        figure.text(
            0.01,
            0.01,
            (
                f"Generated {_generated_at()} | Dataset release {comparison.get('release_slug', '-')} | "
                "Solid lines: αV from the anisotropic Cartesian/directional export; dashed lines: axial components."
            ),
            fontsize=7.5,
            color="#647586",
        )
        pdf.savefig(figure)
        plt.close(figure)
    return output.getvalue()
