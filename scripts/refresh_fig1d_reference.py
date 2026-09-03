"""Regenerate fig1d-reference.json from the NTE/PTE Dataset Portal REGISTRY_DATA.

The portal page (http://10.10.58.87:8104/) embeds its full registry as
`window.REGISTRY_DATA` in the served HTML. This script:

1. Extracts that JSON from a locally downloaded copy of the page
   (var/_fig1d_probe.html).
2. Maps each canonical material to the platform's fig1d point schema:
       material_key = identity.material_folder
       x_gpa        = mechanical.E_tilde_GPa     (bonding modulus, GPa)
       g_gpa        = mechanical.G_plot_GPa      (shear modulus, GPa)
       classification = thermal_expansion.selected_class_100K  (NTE/PTE)
       source       = literature.selected_source ("This work" -> "our")
       year         = literature.selected_year
3. Updates axis.boundary_c to metadata.policy.fig1d_cubic_threshold.
4. Preserves title, descriptor_formula, axis limits, and gradient unchanged.

Precision is rounded to match the legacy file (x: 8 dp, g: 6 dp).
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROBE = ROOT / "var" / "_fig1d_probe.html"
TARGET = ROOT / "src" / "te_platform" / "web" / "fig1d-reference.json"

# The literal marker that opens the embedded registry payload.
MARKER = "REGISTRY_DATA="
# "This work" is the platform's own calculation; the legacy file called it "our".
SOURCE_MAP = {"This work": "our"}


def load_registry() -> dict:
    html = PROBE.read_text(encoding="utf-8", errors="replace")
    eq = html.index(MARKER)
    start = eq + len(MARKER)
    end = html.index("</script>", start)
    raw = html[start:end].rstrip().rstrip(";")
    return json.loads(raw)


def build_points(registry: dict) -> list[dict]:
    points = []
    for m in registry["materials"]:
        ident = m["identity"]
        mech = m["mechanical"]
        te = m["thermal_expansion"]
        lit = m["literature"]
        src = lit.get("selected_source") or lit.get("selected_source_raw") or ""
        src = SOURCE_MAP.get(src, src)
        points.append({
            "material_key": ident["material_folder"],
            "x_gpa": round(mech["E_tilde_GPa"], 8),
            "g_gpa": round(mech["G_plot_GPa"], 6),
            "classification": te["selected_class_100K"],
            "source": src,
            "year": lit.get("selected_year"),
        })
    return points


def main() -> None:
    registry = load_registry()
    meta = registry["metadata"]
    points = build_points(registry)

    print("canonical_material_count:", meta.get("canonical_material_count"))
    print("points produced:", len(points))
    print("classification:", dict(Counter(p["classification"] for p in points)))
    print("source:", dict(Counter(p["source"] for p in points)))
    print("year nulls:", sum(1 for p in points if p["year"] is None))
    print("threshold:", meta["policy"]["fig1d_cubic_threshold"],
          "rule:", meta["policy"]["fig1d_cubic_threshold_rule"])

    old = json.loads(TARGET.read_text(encoding="utf-8"))

    # Preserve axis limits and gradient; only swap the threshold.
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
        "excluded_material_count": meta.get("excluded_material_count"),
        "fig1d_geometry": meta["policy"].get("fig1d_geometry"),
        "fig1d_cubic_threshold": meta["policy"]["fig1d_cubic_threshold"],
        "fig1d_cubic_threshold_rule": meta["policy"]["fig1d_cubic_threshold_rule"],
    }

    TARGET.write_text(json.dumps(new, ensure_ascii=False), encoding="utf-8")
    print("wrote:", TARGET)


if __name__ == "__main__":
    main()
