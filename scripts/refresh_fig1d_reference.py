"""Regenerate the Fig. 1d landscape data from the NTE/PTE Dataset Portal.

The portal page (http://10.10.58.87:8104/) embeds its full registry as
`window.REGISTRY_DATA` in the served HTML. This script:

1. Extracts that JSON from a locally downloaded copy of the page
   (var/_fig1d_probe.html).
2. Keeps only the 324 `workspace.included` materials (the portal's Fig. 1d
   chart uses `chartRows = filtered.filter(included)`; 18 non-cubic OOD
   materials are excluded from both the plot and the downloadable CSV).
3. Writes two artifacts into src/te_platform/web/:

   * fig1d-reference.json  — the plotting data consumed by drawLandscape()
     (material_key, x_gpa, g_gpa, classification, source, year, plus
     formula/xi/domain for a richer hover tooltip).

   * fig1d_points.csv      — the full "download plot data" export, matching
     the portal's 30-column schema exactly.

The axis limits and gradient are preserved byte-for-byte; only the threshold
(boundary_c) and the point set change.
"""
from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROBE = ROOT / "var" / "_fig1d_probe.html"
TARGET_JSON = ROOT / "src" / "te_platform" / "web" / "fig1d-reference.json"
TARGET_CSV = ROOT / "src" / "te_platform" / "web" / "fig1d_points.csv"

# The literal marker that opens the embedded registry payload.
MARKER = "REGISTRY_DATA="
# "This work" is the platform's own calculation; the legacy file called it "our".
SOURCE_MAP = {"This work": "our"}

# The portal's fig1d_points.csv schema, mapped to REGISTRY_DATA fields.
CSV_COLUMNS = [
    ("release_id", lambda m: m["release_id"]),
    ("material_id", lambda m: m["material_id"]),
    ("si_no", lambda m: m["identity"]["si_no"]),
    ("formula", lambda m: m["identity"]["formula"]),
    ("G_GPa", lambda m: m["mechanical"]["G_plot_GPa"]),
    ("E_tilde_GPa", lambda m: m["mechanical"]["E_tilde_GPa"]),
    ("xi_G_over_Etilde", lambda m: m["mechanical"]["xi_G_over_Etilde"]),
    ("thermal_expansion_class", lambda m: m["figure"]["class_for_fig1d"]),
    ("selected_class_100K", lambda m: m["thermal_expansion"]["selected_class_100K"]),
    ("source", lambda m: m["literature"]["selected_source"]),
    ("source_raw", lambda m: m["literature"]["selected_source_raw"]),
    ("source_group_s2", lambda m: m["literature"]["source_group_s2"]),
    ("method", lambda m: m["thermal_expansion"]["method_for_table_s2"]),
    ("year", lambda m: m["literature"]["selected_year"]),
    ("reference_id", lambda m: m["literature"]["selected_reference_id"]),
    ("crystal_system", lambda m: m["structure"]["crystal_system_100K"]),
    ("crystal_system_100K", lambda m: m["structure"]["crystal_system_100K"]),
    ("phase_crystal_system_100K", lambda m: m["structure"]["phase_crystal_system_100K"]),
    ("calculated_crystal_system", lambda m: m["structure"]["crystal_system"]),
    ("symmetry_subset", lambda m: m["structure"]["symmetry_subset"]),
    ("strict_cubic_100K", lambda m: m["structure"]["strict_cubic_100K"]),
    ("figure_domain_100K", lambda m: m["figure"]["figure_domain_100K"]),
    ("phase_status_100K", lambda m: m["structure"]["phase_status_100K"]),
    ("provisional", lambda m: m["thermal_expansion"]["provisional"]),
    ("label_candidate", lambda m: m["figure"]["label_candidate"]),
    ("label_text", lambda m: m["figure"]["label_text"]),
    ("mechanical_run_id", lambda m: m["mechanical"]["selected_run_id"]),
    ("thermal_run_id", lambda m: m["thermal_expansion"]["selected_run_id"]),
    ("feature_run_id", lambda m: m["features"]["selected_run_id"]),
    ("feature_stale", lambda m: m["features"]["stale"]),
]


def load_registry() -> dict:
    html = PROBE.read_text(encoding="utf-8", errors="replace")
    eq = html.index(MARKER)
    start = eq + len(MARKER)
    end = html.index("</script>", start)
    raw = html[start:end].rstrip().rstrip(";")
    return json.loads(raw)


def included_materials(registry: dict) -> list[dict]:
    """Only the 324 workspace.included materials (portal chartRows filter)."""
    return [m for m in registry["materials"] if m.get("workspace", {}).get("included")]


def build_points(materials: list[dict]) -> list[dict]:
    points = []
    for m in materials:
        ident = m["identity"]
        mech = m["mechanical"]
        te = m["thermal_expansion"]
        lit = m["literature"]
        src = lit.get("selected_source") or lit.get("selected_source_raw") or ""
        src = SOURCE_MAP.get(src, src)
        points.append({
            "material_key": ident["material_folder"],
            "formula": ident.get("formula_original") or ident.get("formula"),
            "x_gpa": round(mech["E_tilde_GPa"], 8),
            "g_gpa": round(mech["G_plot_GPa"], 6),
            "xi_g_over_e": mech.get("xi_G_over_Etilde"),
            "classification": te["selected_class_100K"],
            "source": src,
            "year": lit.get("selected_year"),
            "figure_domain_100K": m["figure"].get("figure_domain_100K"),
        })
    return points


def fmt(v) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "True" if v else "False"
    return str(v)


def build_csv(materials: list[dict]) -> list[list[str]]:
    header = [name for name, _ in CSV_COLUMNS]
    rows = [header]
    for m in materials:
        rows.append([fmt(fn(m)) for _, fn in CSV_COLUMNS])
    return rows


def main() -> None:
    registry = load_registry()
    meta = registry["metadata"]
    materials = included_materials(registry)
    points = build_points(materials)
    csv_rows = build_csv(materials)

    print("canonical_material_count:", meta.get("canonical_material_count"))
    print("included materials:", len(materials))
    print("points produced:", len(points))
    print("classification:", dict(Counter(p["classification"] for p in points)))
    print("source:", dict(Counter(p["source"] for p in points)))
    print("year nulls:", sum(1 for p in points if p["year"] is None))
    print("threshold:", meta["policy"]["fig1d_cubic_threshold"],
          "rule:", meta["policy"]["fig1d_cubic_threshold_rule"])

    old = json.loads(TARGET_JSON.read_text(encoding="utf-8"))

    new_axis = dict(old["axis"])
    new_axis["boundary_c"] = meta["policy"]["fig1d_cubic_threshold"]

    new = dict(old)
    new["axis"] = new_axis
    new["points"] = points
    new["provenance"] = {
        "source": "NTE/PTE Dataset Portal (http://10.10.58.87:8104/) Fig. 1d",
        "release_id": meta.get("release_id"),
        "base_release_id": meta.get("base_release_id"),
        "built_at_utc": meta.get("built_at_utc"),
        "canonical_material_count": meta.get("canonical_material_count"),
        "included_material_count": len(materials),
        "excluded_material_count": meta.get("excluded_material_count"),
        "fig1d_geometry": meta["policy"].get("fig1d_geometry"),
        "fig1d_cubic_threshold": meta["policy"]["fig1d_cubic_threshold"],
        "fig1d_cubic_threshold_rule": meta["policy"]["fig1d_cubic_threshold_rule"],
    }

    TARGET_JSON.write_text(json.dumps(new, ensure_ascii=False), encoding="utf-8")

    with TARGET_CSV.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.writer(fh, lineterminator="\r\n")
        writer.writerows(csv_rows)

    print("wrote:", TARGET_JSON)
    print("wrote:", TARGET_CSV, f"({len(csv_rows) - 1} data rows)")


if __name__ == "__main__":
    main()
