from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path


GRADIENT_STOPS = [
    [0.000, "#316698", 0.100],
    [0.083, "#326798", 0.115],
    [0.148, "#386b9b", 0.161],
    [0.206, "#4272a0", 0.239],
    [0.261, "#4f7ba7", 0.348],
    [0.314, "#6188af", 0.490],
    [0.364, "#7697ba", 0.664],
    [0.413, "#8fa9c6", 0.867],
    [0.440, "#a0b5cf", 1.000],
    [0.467, "#a6b8ce", 1.000],
    [0.504, "#b8c0cd", 1.000],
    [0.548, "#d6cfca", 1.000],
    [0.587, "#f8dfc8", 1.000],
    [0.616, "#eac1aa", 0.811],
    [0.646, "#dfa791", 0.645],
    [0.678, "#d5907a", 0.498],
    [0.713, "#cc7d67", 0.374],
    [0.750, "#c56e57", 0.274],
    [0.791, "#c0614b", 0.196],
    [0.839, "#bc5943", 0.141],
    [0.897, "#ba543e", 0.110],
    [1.000, "#ba533d", 0.100],
]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _float(row: dict[str, str], name: str) -> float | None:
    try:
        value = float(row.get(name, ""))
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def _points(path: Path, classification: str) -> list[dict[str, object]]:
    points: list[dict[str, object]] = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            shear = _float(row, "G_GPa")
            cohesive = _float(row, "E_coh_eV_per_atom")
            atomic_volume = _float(row, "AAV")
            coordination = _float(row, "avg_cn")
            if (
                shear is None
                or cohesive is None
                or atomic_volume is None
                or coordination is None
                or shear <= 0
                or atomic_volume <= 0
                or coordination <= 0
            ):
                continue
            descriptor = 160.217 * abs(cohesive) / (atomic_volume * coordination)
            if not math.isfinite(descriptor) or descriptor <= 0:
                continue
            year = _float(row, "year")
            points.append(
                {
                    "material_key": row.get("material_folder", ""),
                    "x_gpa": round(descriptor, 8),
                    "g_gpa": round(shear, 8),
                    "classification": classification,
                    "source": row.get("source", "our"),
                    "year": int(year) if year is not None else None,
                }
            )
    return points


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the versioned Fig. 1d web reference data")
    parser.add_argument("--nte-csv", type=Path, required=True)
    parser.add_argument("--pte-csv", type=Path, required=True)
    parser.add_argument("--source-svg", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    for path in (args.nte_csv, args.pte_csv, args.source_svg):
        if not path.is_file():
            raise ValueError(f"Source file does not exist: {path}")
    points = _points(args.nte_csv, "NTE") + _points(args.pte_csv, "PTE")
    payload = {
        "title": "Fig. 1d G–Ẽ thermal-expansion landscape",
        "descriptor_formula": "160.217*abs(E_coh_eV_per_atom)/(AAV*avg_cn)",
        "axis": {
            "x_min": 4.038073314103544,
            "x_max": 60.623589519042696,
            "y_min": 0.9876930987970358,
            "y_max": 659.2901857657129,
            "boundary_c": 2.84151,
        },
        "gradient": {
            "start": [0.5817, 1.1877],
            "end": [0.4183, -0.1877],
            "stops": GRADIENT_STOPS,
        },
        "provenance": {
            "nte_csv": args.nte_csv.name,
            "nte_sha256": _sha256(args.nte_csv),
            "pte_csv": args.pte_csv.name,
            "pte_sha256": _sha256(args.pte_csv),
            "source_svg": args.source_svg.name,
            "source_svg_sha256": _sha256(args.source_svg),
        },
        "points": points,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    print(json.dumps({"output": str(args.output.resolve()), "points": len(points)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
