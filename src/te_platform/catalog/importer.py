from __future__ import annotations

import gzip
import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from te_platform.catalog.provenance import (
    canonical_json,
    sha256_file,
    sha256_json,
    sha256_text,
)
from te_platform.db.schema import connect_database, initialize_database


PROPERTY_UNITS = {
    "Material_Cost_USD_per_kg": "USD/kg",
    "Band_Gap_eV": "eV",
    "Pearson_Electronegativity_eV": "eV",
    "CBM_eV": "eV",
    "VBM_eV": "eV",
    "K_GPa": "GPa",
    "G_GPa": "GPa",
    "E_GPa": "GPa",
    "E_tilde_GPa": "GPa",
    "E_coh_eV_per_atom": "eV/atom",
    "TE_300K": "1/K",
    "T2": "K",
    "CTE_ppm": "ppm/K",
    "volume_shrinkage": "dimensionless",
    "volume_shrinkage_percent": "%",
    "TE_min": "1/K",
    "TE_min_K": "K",
    "alpha_integral_0_300K": "dimensionless",
    "alpha_integral_0_600K": "dimensionless",
    "alpha_integral_0_900K": "dimensionless",
}

MATERIAL_PATTERN = re.compile(r"^(?P<formula>.+)-(?P<external_id>mp-\d+)$")


@dataclass(frozen=True)
class ImportSummary:
    release_slug: str
    records: int
    unique_materials: int
    structures: int
    properties: int
    quality_flags: int
    database_path: str
    dataset_sha256: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _open_json(path: Path):
    if path.suffix.lower() == ".gz":
        return gzip.open(path, "rt", encoding="utf-8")
    return path.open("r", encoding="utf-8")


def _load_rows(path: Path) -> list[dict[str, Any]]:
    with _open_json(path) as handle:
        rows = json.load(handle)
    if not isinstance(rows, list):
        raise ValueError("Dataset root must be a JSON list")
    if not all(isinstance(row, dict) for row in rows):
        raise ValueError("Every dataset record must be a JSON object")
    return rows


def _validate_rows(rows: Iterable[dict[str, Any]]) -> None:
    seen: set[str] = set()
    for index, row in enumerate(rows):
        material_key = row.get("material_folder")
        if not isinstance(material_key, str) or not material_key.strip():
            raise ValueError(f"Record {index} has no material_folder")
        if material_key in seen:
            raise ValueError(f"Duplicate material_folder: {material_key}")
        seen.add(material_key)
        poscar = row.get("POSCAR")
        if not isinstance(poscar, str) or not poscar.strip():
            raise ValueError(f"Record {index} has no POSCAR: {material_key}")


def _split_material_key(material_key: str) -> tuple[str, str | None]:
    match = MATERIAL_PATTERN.match(material_key)
    if match is None:
        return material_key, None
    return match.group("formula"), match.group("external_id")


def _property_values(value: Any) -> tuple[float | None, str | None]:
    if isinstance(value, bool):
        return float(value), None
    if isinstance(value, (int, float)):
        return float(value), None
    if value is None:
        return None, None
    if isinstance(value, str):
        return None, value
    return None, canonical_json(value)


def _quality_flags(row: dict[str, Any]) -> list[tuple[str, str, str, Any]]:
    flags: list[tuple[str, str, str, Any]] = []
    bulk_modulus = row.get("K_GPa")
    if isinstance(bulk_modulus, (int, float)) and bulk_modulus <= 0:
        flags.append(
            (
                "nonpositive_bulk_modulus",
                "error",
                "K_GPa must be positive before mechanical or composite analysis",
                bulk_modulus,
            )
        )
    shear_modulus = row.get("G_GPa")
    if isinstance(shear_modulus, (int, float)) and shear_modulus < 0:
        flags.append(
            (
                "negative_shear_modulus",
                "error",
                "G_GPa cannot be negative",
                shear_modulus,
            )
        )
    bonding_modulus = row.get("E_tilde_GPa")
    if isinstance(bonding_modulus, (int, float)) and bonding_modulus <= 0:
        flags.append(
            (
                "nonpositive_bonding_modulus",
                "error",
                "E_tilde_GPa must be positive before SBR classification",
                bonding_modulus,
            )
        )
    porosity = row.get("porosity")
    if isinstance(porosity, (int, float)) and not 0 <= porosity <= 1:
        flags.append(
            (
                "porosity_out_of_unit_interval",
                "warning",
                "Porosity is outside the expected dimensionless interval [0, 1]",
                porosity,
            )
        )
    return flags


def import_dataset(
    database_path: str | Path,
    dataset_path: str | Path,
    manifest_path: str | Path,
    *,
    replace: bool = False,
) -> ImportSummary:
    db_path = Path(database_path)
    data_path = Path(dataset_path)
    manifest_file = Path(manifest_path)

    with manifest_file.open("r", encoding="utf-8") as handle:
        manifest = json.load(handle)
    rows = _load_rows(data_path)
    _validate_rows(rows)

    expected_count = int(manifest["record_count"])
    if len(rows) != expected_count:
        raise ValueError(f"Manifest expects {expected_count} records, found {len(rows)}")

    release_slug = str(manifest["release_slug"])
    dataset_sha256 = sha256_file(data_path)
    expected_snapshot_hash = manifest.get("snapshot_sha256")
    if expected_snapshot_hash and expected_snapshot_hash != dataset_sha256:
        raise ValueError("Dataset snapshot SHA256 does not match manifest")

    initialize_database(db_path)
    property_count = 0
    structure_count = 0
    quality_flag_count = 0
    now = datetime.now(timezone.utc).isoformat()

    with connect_database(db_path) as connection:
        existing = connection.execute(
            "SELECT id FROM dataset_releases WHERE slug = ?", (release_slug,)
        ).fetchone()
        if existing is not None:
            if not replace:
                raise ValueError(
                    f"Dataset release already imported: {release_slug}; use --replace"
                )
            connection.execute("DELETE FROM dataset_releases WHERE id = ?", (existing["id"],))

        cursor = connection.execute(
            """
            INSERT INTO dataset_releases(
                slug, title, version, record_count, source_file_name,
                source_sha256, manifest_json, imported_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                release_slug,
                manifest["title"],
                manifest["version"],
                len(rows),
                data_path.name,
                dataset_sha256,
                canonical_json(manifest),
                now,
            ),
        )
        release_id = int(cursor.lastrowid)

        for ordinal, row in enumerate(rows):
            material_key = str(row["material_folder"])
            formula, external_id = _split_material_key(material_key)
            connection.execute(
                """
                INSERT INTO materials(material_key, formula, external_id)
                VALUES (?, ?, ?)
                ON CONFLICT(material_key) DO UPDATE SET
                    formula = excluded.formula,
                    external_id = excluded.external_id
                """,
                (material_key, formula, external_id),
            )
            material_row = connection.execute(
                "SELECT id FROM materials WHERE material_key = ?", (material_key,)
            ).fetchone()
            material_id = int(material_row["id"])

            connection.execute(
                """
                INSERT INTO dataset_memberships(
                    dataset_release_id, material_id, ordinal, source_record_sha256
                ) VALUES (?, ?, ?, ?)
                """,
                (release_id, material_id, ordinal, sha256_json(row)),
            )

            poscar = str(row["POSCAR"])
            connection.execute(
                """
                INSERT INTO structures(
                    dataset_release_id, material_id, format, content, content_sha256
                ) VALUES (?, ?, 'POSCAR', ?, ?)
                """,
                (release_id, material_id, poscar, sha256_text(poscar)),
            )
            structure_count += 1

            for name, value in row.items():
                if name in {"material_folder", "POSCAR"}:
                    continue
                numeric_value, text_value = _property_values(value)
                connection.execute(
                    """
                    INSERT INTO material_properties(
                        dataset_release_id, material_id, name,
                        numeric_value, text_value, unit
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        release_id,
                        material_id,
                        name,
                        numeric_value,
                        text_value,
                        PROPERTY_UNITS.get(name),
                    ),
                )
                property_count += 1

            for code, severity, message, observed_value in _quality_flags(row):
                connection.execute(
                    """
                    INSERT INTO data_quality_flags(
                        dataset_release_id, material_id, code, severity,
                        message, observed_value_json
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        release_id,
                        material_id,
                        code,
                        severity,
                        message,
                        canonical_json(observed_value),
                    ),
                )
                quality_flag_count += 1

    return ImportSummary(
        release_slug=release_slug,
        records=len(rows),
        unique_materials=len({row["material_folder"] for row in rows}),
        structures=structure_count,
        properties=property_count,
        quality_flags=quality_flag_count,
        database_path=str(db_path.resolve()),
        dataset_sha256=dataset_sha256,
    )
