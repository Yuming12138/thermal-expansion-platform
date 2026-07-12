from __future__ import annotations

import csv
import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from te_platform.catalog.importer import PROPERTY_UNITS
from te_platform.catalog.provenance import canonical_json, sha256_file, sha256_json, sha256_text
from te_platform.config import DEFAULT_PTE_RELEASE_SLUG
from te_platform.db.schema import connect_database, initialize_database
from te_platform.jobs.repository import import_historical_thermal_expansion_curve
from te_platform.precision.results import interpolate_alpha, parse_thermal_expansion_file


@dataclass(frozen=True)
class PteImportSummary:
    release_slug: str
    materials: int
    structures: int
    properties: int
    curves: int
    database_path: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _property_values(value: str) -> tuple[float | None, str | None]:
    stripped = value.strip()
    if not stripped:
        return None, None
    try:
        return float(stripped), None
    except ValueError:
        return None, stripped


def _formula(material_key: str) -> str:
    without_ordinal = re.sub(r"^\d+\.", "", material_key)
    return re.sub(r"[-_]mp-\d+$", "", without_ordinal, flags=re.IGNORECASE)


def import_pte_reference(
    database_path: str | Path,
    source_root: str | Path,
    summary_csv: str | Path,
    *,
    release_slug: str = DEFAULT_PTE_RELEASE_SLUG,
    replace: bool = False,
) -> PteImportSummary:
    database = Path(database_path)
    root = Path(source_root)
    csv_path = Path(summary_csv)
    if not root.is_dir() or not csv_path.is_file():
        raise ValueError("PTE source root and summary CSV must exist")
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise ValueError("PTE summary CSV contains no records")
    keys = [str(row.get("material_folder", "")).strip() for row in rows]
    if any(not key for key in keys) or len(set(keys)) != len(keys):
        raise ValueError("PTE summary material_folder values must be non-empty and unique")

    initialize_database(database)
    now = datetime.now(UTC).isoformat()
    structure_count = property_count = curve_count = 0
    manifest = {
        "release_slug": release_slug,
        "title": "PTE reference materials with complete QHA curves",
        "version": "1.0.0",
        "record_count": len(rows),
        "summary_csv": csv_path.name,
        "summary_sha256": sha256_file(csv_path),
        "source_root": str(root.resolve()),
    }
    with connect_database(database) as connection:
        existing = connection.execute(
            "SELECT id FROM dataset_releases WHERE slug = ?", (release_slug,)
        ).fetchone()
        if existing is not None:
            if not replace:
                raise ValueError(f"Dataset release already imported: {release_slug}; use --replace")
            connection.execute("DELETE FROM dataset_releases WHERE id = ?", (existing["id"],))
        cursor = connection.execute(
            """INSERT INTO dataset_releases
            (slug, title, version, record_count, source_file_name, source_sha256,
             manifest_json, imported_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                release_slug,
                manifest["title"],
                manifest["version"],
                len(rows),
                csv_path.name,
                manifest["summary_sha256"],
                canonical_json(manifest),
                now,
            ),
        )
        release_id = int(cursor.lastrowid)
        for ordinal, (row, material_key) in enumerate(zip(rows, keys)):
            material_dir = root / material_key
            poscar_path = material_dir / "POSCAR"
            curve_path = material_dir / "thermal_expansion.dat"
            if not poscar_path.is_file() or not curve_path.is_file():
                raise ValueError(f"PTE material lacks POSCAR or thermal_expansion.dat: {material_key}")
            curve = parse_thermal_expansion_file(curve_path)
            alpha_300 = interpolate_alpha(curve, 300.0)
            if alpha_300 is None or alpha_300 <= 0:
                raise ValueError(f"PTE material has no positive alpha at 300 K: {material_key}")
            connection.execute(
                """INSERT INTO materials(material_key, formula, external_id)
                VALUES (?, ?, NULL)
                ON CONFLICT(material_key) DO UPDATE SET formula = excluded.formula""",
                (material_key, _formula(material_key)),
            )
            material = connection.execute(
                "SELECT id FROM materials WHERE material_key = ?", (material_key,)
            ).fetchone()
            material_id = int(material["id"])
            source_record = {**row, "curve_sha256": sha256_file(curve_path)}
            connection.execute(
                """INSERT INTO dataset_memberships
                (dataset_release_id, material_id, ordinal, source_record_sha256)
                VALUES (?, ?, ?, ?)""",
                (release_id, material_id, ordinal, sha256_json(source_record)),
            )
            poscar = poscar_path.read_text(encoding="utf-8", errors="replace")
            connection.execute(
                """INSERT INTO structures
                (dataset_release_id, material_id, format, content, content_sha256)
                VALUES (?, ?, 'POSCAR', ?, ?)""",
                (release_id, material_id, poscar, sha256_text(poscar)),
            )
            structure_count += 1
            properties = {**row, "thermal_expansion_class": "PTE", "alpha_300k_ppm": alpha_300 * 1_000_000}
            for name, value in properties.items():
                if name == "material_folder":
                    continue
                numeric_value, text_value = _property_values(str(value))
                connection.execute(
                    """INSERT INTO material_properties
                    (dataset_release_id, material_id, name, numeric_value, text_value, unit)
                    VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        release_id,
                        material_id,
                        name,
                        numeric_value,
                        text_value,
                        "ppm/K" if name == "alpha_300k_ppm" else PROPERTY_UNITS.get(name),
                    ),
                )
                property_count += 1
            import_historical_thermal_expansion_curve(
                connection,
                material_id=material_id,
                source_path=str(curve_path.resolve()),
                thermal_expansion_curve=curve,
                alpha_300k_per_k=alpha_300,
            )
            curve_count += 1

    return PteImportSummary(
        release_slug=release_slug,
        materials=len(rows),
        structures=structure_count,
        properties=property_count,
        curves=curve_count,
        database_path=str(database.resolve()),
    )
