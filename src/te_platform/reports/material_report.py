from __future__ import annotations

from datetime import UTC, datetime
from io import BytesIO
from typing import Any

import matplotlib

matplotlib.use("Agg")

from matplotlib import pyplot as plt  # noqa: E402
from matplotlib.backends.backend_pdf import PdfPages  # noqa: E402


REPORT_COLORS = ("#d84a3a", "#2864c7", "#15906f", "#d98624", "#7b57b2", "#5d6a76")


def _generated_at() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")


def _curve_points(detail: dict[str, Any]) -> tuple[list[float], list[float]]:
    curve = detail.get("precision_thermal_expansion") or {}
    points = curve.get("points") or []
    temperatures = [float(point["temperature_k"]) for point in points]
    alphas = [float(point["alpha_ppm_per_k"]) for point in points]
    if len(temperatures) < 2:
        raise ValueError("Material has no stored thermal-expansion curve")
    return temperatures, alphas


def build_material_curve_pdf(detail: dict[str, Any]) -> bytes:
    temperatures, alphas = _curve_points(detail)
    material = detail["material"]
    release = detail.get("dataset_release") or {}
    curve = detail.get("precision_thermal_expansion") or {}
    output = BytesIO()
    metadata = {
        "Title": f"Thermal expansion curve - {material['material_key']}",
        "Author": "Thermal Expansion Materials Platform",
        "Subject": "Stored QHA thermal expansion data",
        "Keywords": "QHA, thermal expansion, NTE, materials",
    }
    with PdfPages(output, metadata=metadata) as pdf:
        figure, axis = plt.subplots(figsize=(8.27, 5.83), constrained_layout=True)
        axis.plot(temperatures, alphas, color="#2864c7", linewidth=2.2)
        axis.axhline(0, color="#7d8994", linewidth=1, linestyle="--")
        axis.set_xlabel("Temperature T (K)")
        axis.set_ylabel("Volumetric thermal expansion alpha (ppm/K)")
        axis.grid(True, color="#e2e8ee", linewidth=0.8)
        axis.set_title(material["material_key"], fontsize=13, fontweight="bold")
        source_name = str(curve.get("source_path") or "stored QHA curve").replace("\\", "/").split("/")[-1]
        figure.suptitle(
            f"Dataset {release.get('version', '-')} | {source_name} | {len(temperatures)} points",
            fontsize=8.5,
            color="#556575",
        )
        figure.text(
            0.01,
            0.01,
            f"Generated {_generated_at()} | Values plotted in ppm/K; DAT download is provided in 1/K.",
            fontsize=7.5,
            color="#647586",
        )
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
        "Subject": "Material property and QHA curve comparison",
        "Keywords": "QHA, thermal expansion, comparison, NTE, materials",
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
            "Catalog CTE",
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
            curve = item.get("curve") or {}
            points = curve.get("points") or []
            if len(points) < 2:
                continue
            curve_axis.plot(
                [float(point["temperature_k"]) for point in points],
                [float(point["alpha_ppm_per_k"]) for point in points],
                label=item["material"]["material_key"],
                color=REPORT_COLORS[index % len(REPORT_COLORS)],
                linewidth=2,
            )
        curve_axis.axhline(0, color="#7d8994", linewidth=1, linestyle="--")
        curve_axis.set_xlabel("Temperature T (K)")
        curve_axis.set_ylabel("Volumetric thermal expansion alpha (ppm/K)")
        curve_axis.grid(True, color="#e2e8ee", linewidth=0.8)
        curve_axis.legend(fontsize=7.5, loc="best")
        figure.text(
            0.01,
            0.01,
            (
                f"Generated {_generated_at()} | Dataset release {comparison.get('release_slug', '-')} | "
                "Etilde = 160.21766208*abs(Ecoh)/(AAV*avg_cn)."
            ),
            fontsize=7.5,
            color="#647586",
        )
        pdf.savefig(figure)
        plt.close(figure)
    return output.getvalue()
