"""Build the 3665-material tensor-aware release catalog.

The research export is intentionally kept outside the web repository.  This
builder joins it by MP id, embeds POSCAR/elastic tensors and stores the full
Cartesian and directional alpha(T) tables in SQLite.  It also keeps the
historical scalar curve interface alive by deriving a volumetric curve from
AGV2 ``alpha_volume`` and by retaining the scalar QHA curve for cubic records.

The default paths are deliberately empty: a release must be built with
explicit source arguments so that a stale neighbouring dataset cannot be
silently selected.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import shutil
import sqlite3
from contextlib import closing
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any, Iterable

from te_platform.catalog.provenance import canonical_json, sha256_file, sha256_json, sha256_text
from te_platform.db.schema import initialize_database


MP_PATTERN = re.compile(r"(?P<formula>.+)-(?P<external_id>mp-\d+)$", re.IGNORECASE)
CURVE_COLUMNS = {
    "cartesian": {
        "T_K": "K",
        "alpha_xx": "ppm/K",
        "alpha_yy": "ppm/K",
        "alpha_zz": "ppm/K",
        "alpha_yz_eng": "ppm/K",
        "alpha_xz_eng": "ppm/K",
        "alpha_xy_eng": "ppm/K",
        "alpha_volume": "ppm/K",
    },
    "directional": {
        "T_K": "K",
        "alpha_a": "ppm/K",
        "alpha_b": "ppm/K",
        "alpha_c": "ppm/K",
        "alpha_volume": "ppm/K",
        "F_ani": "dimensionless",
    },
}


@dataclass(frozen=True)
class InventoryRow:
    material_key: str
    external_id: str
    formula: str
    method: str
    source_kind: str
    poscar_path: str
    elastic_tensor_path: str
    volumetric_path: str
    cartesian_path: str
    directional_path: str
    volumetric_source_path: str
    cartesian_source_path: str
    directional_source_path: str
    volumetric_sha256: str
    cartesian_sha256: str
    directional_sha256: str
    volumetric_points: int
    cartesian_points: int
    directional_points: int
    temperature_min_k: float
    temperature_max_k: float
    recalc_adopted: bool
    recalc_status: str


def _sha256(path: Path) -> str:
    return sha256_file(path)


def _parse_material_key(material_key: str) -> tuple[str, str]:
    match = MP_PATTERN.fullmatch(material_key.strip())
    if match is None:
        raise ValueError(f"material_folder has no trailing MP id: {material_key}")
    return match.group("formula"), match.group("external_id").lower()


def _read_selection(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise ValueError(f"Selection CSV is empty: {path}")
    keys = [str(row.get("material_folder", "")).strip() for row in rows]
    if any(not key for key in keys) or len(set(keys)) != len(keys):
        raise ValueError("selection material_folder values must be non-empty and unique")
    if len(rows) != 3665:
        raise ValueError(f"Expected the final 3665-row selection, found {len(rows)}")
    return rows


def _read_table(path: Path, expected_kind: str) -> tuple[list[str], list[dict[str, float]]]:
    if not path.is_file():
        raise ValueError(f"Missing {expected_kind} curve: {path}")
    header: list[str] | None = None
    rows: list[dict[str, float]] = []
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#"):
            candidate = line.lstrip("#").strip().split()
            if candidate and candidate[0] in {"T_K", "temperature_K"}:
                header = candidate
            continue
        values = line.split()
        if header is None:
            # QHA scalar files have no header and are handled by the dedicated
            # parser below; AGV Cartesian/directional files always do.
            raise ValueError(f"{expected_kind} curve has no header: {path}")
        if len(values) != len(header):
            raise ValueError(f"{expected_kind} curve row has {len(values)} columns, expected {len(header)}: {path}")
        try:
            numeric = [float(value) for value in values]
        except ValueError as error:
            raise ValueError(f"{expected_kind} curve contains a non-numeric row: {path}") from error
        if not all(math.isfinite(value) for value in numeric):
            raise ValueError(f"{expected_kind} curve contains NaN or infinity: {path}")
        rows.append(dict(zip(header, numeric)))
    if header is None or len(rows) < 2:
        raise ValueError(f"{expected_kind} curve has fewer than two data rows: {path}")
    if tuple(header) != tuple(CURVE_COLUMNS[expected_kind]):
        raise ValueError(
            f"Unexpected {expected_kind} columns in {path}: {header}; "
            f"expected {list(CURVE_COLUMNS[expected_kind])}"
        )
    temperatures = [row["T_K"] for row in rows]
    if any(right <= left for left, right in zip(temperatures, temperatures[1:])):
        raise ValueError(f"{expected_kind} temperatures are not strictly increasing: {path}")
    return header, rows


def _read_scalar_qha(path: Path) -> tuple[list[tuple[float, float]], float, float]:
    if not path.is_file():
        raise ValueError(f"Missing scalar QHA curve: {path}")
    points: list[tuple[float, float]] = []
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        values = raw.split()
        if len(values) < 2:
            continue
        try:
            temperature, alpha = float(values[0]), float(values[1])
        except ValueError:
            continue
        if math.isfinite(temperature) and math.isfinite(alpha):
            points.append((temperature, alpha))
    if len(points) < 2 or any(right[0] <= left[0] for left, right in zip(points, points[1:])):
        raise ValueError(f"Invalid scalar QHA curve: {path}")
    return points, points[0][0], points[-1][0]


def _interpolate(points: list[tuple[float, float]], target: float) -> float | None:
    if target < points[0][0] or target > points[-1][0]:
        return None
    for left, right in zip(points, points[1:]):
        if left[0] <= target <= right[0]:
            if right[0] == left[0]:
                return left[1]
            fraction = (target - left[0]) / (right[0] - left[0])
            return left[1] + fraction * (right[1] - left[1])
    return points[-1][1]


def _logical_curve_path(slug: str, material_key: str, filename: str) -> str:
    # Material keys are already restricted to formula + MP id.  Keep this
    # logical path portable; no local drive or research checkout is embedded.
    return f"catalog://{slug}/{material_key}/{filename}"


def _choose_anisotropic_source(
    material_key: str,
    anisotropic_root: Path,
    recalc_audit: dict[str, dict[str, Any]],
) -> tuple[Path, bool, str]:
    _, external_id = _parse_material_key(material_key)
    original = anisotropic_root / external_id
    selected = original
    adopted = False
    status = "not_audited"
    audit = recalc_audit.get(external_id)
    if audit is not None:
        status = str(audit.get("status", "unknown"))
        # The final 3665 selection adopted only recalculations which remained
        # NTE at 100 K.  Use both files from that exact result directory; for
        # a non-NTE recalculation the original curve remains authoritative.
        if status == "NTE_100K":
            candidate = Path(str(audit.get("path", ""))).parent
            if (candidate / "thermal_expansion_cartesian.dat").is_file() and (
                candidate / "thermal_expansion_directional.dat"
            ).is_file():
                selected = candidate
                adopted = True
    return selected, adopted, status


def _copy_pte_release(source_db: Path, target: sqlite3.Connection) -> int:
    """Copy the old catalog's 185-material PTE release into a fresh database."""
    source = sqlite3.connect(source_db)
    source.row_factory = sqlite3.Row
    try:
        release = source.execute(
            "SELECT * FROM dataset_releases WHERE slug = 'pte-reference-185-v1'"
        ).fetchone()
        if release is None:
            raise ValueError("Reference catalog has no pte-reference-185-v1 release")
        now = datetime.now(UTC).isoformat()
        cursor = target.execute(
            """INSERT INTO dataset_releases
            (slug,title,version,record_count,source_file_name,source_sha256,manifest_json,imported_at)
            VALUES (?,?,?,?,?,?,?,?)""",
            (
                release["slug"], release["title"], release["version"], release["record_count"],
                release["source_file_name"], release["source_sha256"], release["manifest_json"], now,
            ),
        )
        release_id = int(cursor.lastrowid)
        memberships = source.execute(
            "SELECT * FROM dataset_memberships WHERE dataset_release_id = ? ORDER BY ordinal",
            (release["id"],),
        ).fetchall()
        material_map: dict[int, int] = {}
        for membership in memberships:
            old_material = source.execute(
                "SELECT * FROM materials WHERE id = ?", (membership["material_id"],)
            ).fetchone()
            target.execute(
                """INSERT INTO materials(material_key,formula,external_id)
                VALUES (?,?,?) ON CONFLICT(material_key) DO UPDATE SET
                formula=excluded.formula, external_id=excluded.external_id""",
                (old_material["material_key"], old_material["formula"], old_material["external_id"]),
            )
            new_material = target.execute(
                "SELECT id FROM materials WHERE material_key = ?", (old_material["material_key"],)
            ).fetchone()
            new_id = int(new_material[0])
            material_map[int(membership["material_id"])] = new_id
            target.execute(
                "INSERT INTO dataset_memberships VALUES (?,?,?,?)",
                (release_id, new_id, membership["ordinal"], membership["source_record_sha256"]),
            )
            structures = source.execute(
                "SELECT format,content,content_sha256 FROM structures WHERE dataset_release_id=? AND material_id=?",
                (release["id"], membership["material_id"]),
            ).fetchall()
            target.executemany(
                "INSERT INTO structures(dataset_release_id,material_id,format,content,content_sha256) VALUES (?,?,?,?,?)",
                [(release_id, new_id, row["format"], row["content"], row["content_sha256"]) for row in structures],
            )
            properties = source.execute(
                "SELECT name,numeric_value,text_value,unit FROM material_properties WHERE dataset_release_id=? AND material_id=?",
                (release["id"], membership["material_id"]),
            ).fetchall()
            target.executemany(
                "INSERT INTO material_properties VALUES (?,?,?,?,?,?)",
                [(release_id, new_id, row["name"], row["numeric_value"], row["text_value"], row["unit"]) for row in properties],
            )
            flags = source.execute(
                "SELECT code,severity,message,observed_value_json FROM data_quality_flags WHERE dataset_release_id=? AND material_id=?",
                (release["id"], membership["material_id"]),
            ).fetchall()
            target.executemany(
                "INSERT INTO data_quality_flags VALUES (?,?,?,?,?,?)",
                [(release_id, new_id, row["code"], row["severity"], row["message"], row["observed_value_json"]) for row in flags],
            )
        jobs = source.execute(
            """SELECT j.* FROM calculation_jobs j JOIN dataset_memberships dm
            ON dm.material_id=j.material_id WHERE dm.dataset_release_id=?
            AND j.workflow='historical_qha_thermal_expansion'""",
            (release["id"],),
        ).fetchall()
        for job in jobs:
            new_id = material_map[int(job["material_id"])]
            target.execute(
                """INSERT INTO calculation_jobs
                (id,material_id,workflow,model_name,status,parameters_json,result_json,error_message,created_at,updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (job["id"], new_id, job["workflow"], job["model_name"], job["status"], job["parameters_json"],
                 job["result_json"], job["error_message"], job["created_at"], job["updated_at"]),
            )
            curve = source.execute(
                "SELECT * FROM precision_thermal_expansion_curves WHERE job_id=?", (job["id"],)
            ).fetchone()
            if curve is not None:
                target.execute(
                    "INSERT INTO precision_thermal_expansion_curves VALUES (?,?,?,?,?)",
                    (curve["job_id"], curve["points_json"], curve["unit"], curve["source_path"], curve["parsed_at"]),
                )
        return len(memberships)
    finally:
        source.close()


def _insert_property(
    target: sqlite3.Connection,
    release_id: int,
    material_id: int,
    name: str,
    value: Any,
    unit: str | None = None,
) -> None:
    if isinstance(value, bool):
        numeric, text = float(value), None
    elif isinstance(value, (int, float)):
        numeric, text = float(value), None
    elif value is None or value == "":
        numeric, text = None, None
    else:
        numeric, text = None, str(value)
    target.execute(
        """INSERT INTO material_properties
        (dataset_release_id,material_id,name,numeric_value,text_value,unit)
        VALUES (?,?,?,?,?,?)""",
        (release_id, material_id, name, numeric, text, unit),
    )


def _insert_anisotropic_curve(
    target: sqlite3.Connection,
    release_id: int,
    material_id: int,
    curve_kind: str,
    header: list[str],
    rows: list[dict[str, float]],
    source_path: str,
    source_hash: str,
    method: str,
    parsed_at: str,
) -> None:
    points = [{key: float(value) for key, value in row.items()} for row in rows]
    units = CURVE_COLUMNS[curve_kind]
    target.execute(
        """INSERT INTO anisotropic_thermal_expansion_curves
        (dataset_release_id,material_id,curve_kind,points_json,columns_json,column_units_json,
         unit,method,source_path,source_sha256,temperature_min_k,temperature_max_k,point_count,parsed_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            release_id, material_id, curve_kind, canonical_json(points), canonical_json(header),
            canonical_json(units), "ppm/K", method, source_path, source_hash,
            rows[0]["T_K"], rows[-1]["T_K"], len(rows), parsed_at,
        ),
    )


def _insert_job_and_scalar_curve(
    target: sqlite3.Connection,
    material_id: int,
    method: str,
    model_name: str,
    source_path: str,
    points_si: list[tuple[float, float]],
    quality_warnings: list[str],
    created_at: str,
) -> None:
    job_id = f"catalog-{method.lower()}-{material_id}"
    alpha_300 = _interpolate(points_si, 300.0)
    result = {
        "thermal_expansion_curve": [[float(t), float(a)] for t, a in points_si],
        "thermal_expansion_source_path": source_path,
        "alpha_300k_per_k": alpha_300,
        "alpha_300k_ppm_per_k": alpha_300 * 1_000_000 if alpha_300 is not None else None,
        "quality_warnings": quality_warnings,
        "thermal_expansion_method": method,
    }
    parameters = {
        "source_path": source_path,
        "thermal_expansion_method": method,
        "stored_unit": "1/K",
    }
    target.execute(
        """INSERT INTO calculation_jobs
        (id,material_id,workflow,model_name,status,parameters_json,result_json,error_message,created_at,updated_at)
        VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (
            job_id, material_id, f"historical_{method.lower()}_thermal_expansion", model_name,
            "SUCCEEDED", canonical_json(parameters), canonical_json(result), None, created_at, created_at,
        ),
    )
    target.execute(
        "INSERT INTO precision_thermal_expansion_curves VALUES (?,?,?,?,?)",
        (job_id, canonical_json([[float(t), float(a)] for t, a in points_si]), "1/K", source_path, created_at),
    )


def build_catalog(args: argparse.Namespace) -> dict[str, Any]:
    selection_csv = Path(args.selection_csv).resolve()
    anisotropic_root = Path(args.anisotropic_root).resolve()
    isotropic_root = Path(args.isotropic_root).resolve()
    output = Path(args.output).resolve()
    reference_catalog = Path(args.reference_catalog).resolve()
    recalc_audit_path = Path(args.recalc_audit).resolve() if args.recalc_audit else None
    for path in (selection_csv, anisotropic_root, isotropic_root, reference_catalog):
        if not path.exists():
            raise ValueError(f"Required source does not exist: {path}")
    selected = _read_selection(selection_csv)
    recalc_audit = json.loads(recalc_audit_path.read_text(encoding="utf-8")) if recalc_audit_path else {}
    if not isinstance(recalc_audit, dict):
        raise ValueError("Recalculation audit must be a JSON object")

    output.parent.mkdir(parents=True, exist_ok=True)
    temp_db = output.with_name(output.name + ".building")
    if temp_db.exists():
        temp_db.unlink()
    initialize_database(temp_db)
    now = datetime.now(UTC).isoformat()
    slug = args.release_slug
    inventories: list[InventoryRow] = []
    method_counts: dict[str, int] = {"AGV2": 0, "QHA": 0}
    recalc_count = 0
    # ``sqlite3.Connection`` is a transaction context manager, not a close
    # context manager.  Use ``closing`` so Windows releases the file handle
    # before the atomic rename below.
    with closing(sqlite3.connect(temp_db)) as target:
        target.row_factory = sqlite3.Row
        selection_hash = _sha256(selection_csv)
        manifest = {
            "release_slug": slug,
            "title": "3665 H-free NTE materials with AGV2 tensor-aware and cubic QHA thermal-expansion curves",
            "version": "2.0.0",
            "record_count": len(selected),
            "selection_csv": selection_csv.name,
            "selection_sha256": selection_hash,
            "source_note": "Final 3665-row selection; MP-id matching only; selected CTE remains the release screening field.",
            "curve_contract": {
                "AGV2": "Cartesian and directional files are stored in ppm/K; volumetric alpha_volume is mirrored into the legacy scalar 1/K curve.",
                "QHA": "Scalar thermal_expansion.dat is stored in 1/K; isotropic Cartesian/directional curves are derived with alpha_linear=alpha_volume/3 and F_ani=0.",
            },
            "recalculation_rule": "Use the accepted recalculation directory only when audit status is NTE_100K; retain original AGV2 curve for non-NTE recalculations.",
            "structure_source": "anisotropic_materials or isotropic_cubic_materials, matched by external MP id",
            "provenance": {"recalc_audit": recalc_audit_path.name if recalc_audit_path else None},
        }
        cursor = target.execute(
            """INSERT INTO dataset_releases
            (slug,title,version,record_count,source_file_name,source_sha256,manifest_json,imported_at)
            VALUES (?,?,?,?,?,?,?,?)""",
            (slug, manifest["title"], manifest["version"], len(selected), selection_csv.name, selection_hash, canonical_json(manifest), now),
        )
        release_id = int(cursor.lastrowid)
        for ordinal, row in enumerate(selected):
            material_key = str(row["material_folder"]).strip()
            formula_from_key, external_id = _parse_material_key(material_key)
            formula = str(row.get("formula") or row.get("formula_guess") or formula_from_key).strip() or formula_from_key
            anis_dir = anisotropic_root / external_id
            iso_dir = isotropic_root / external_id
            if (anis_dir / "POSCAR").is_file():
                method = "AGV2"
                structure_dir = anis_dir
                curve_dir, recalc_adopted, recalc_status = _choose_anisotropic_source(material_key, anisotropic_root, recalc_audit)
                cart_path = curve_dir / "thermal_expansion_cartesian.dat"
                directional_path = curve_dir / "thermal_expansion_directional.dat"
                cart_header, cart_rows = _read_table(cart_path, "cartesian")
                directional_header, directional_rows = _read_table(directional_path, "directional")
                if len(cart_rows) != len(directional_rows) or cart_rows[0]["T_K"] != directional_rows[0]["T_K"]:
                    raise ValueError(f"Cartesian/directional temperature grids disagree: {material_key}")
                volume_points = [(r["T_K"], r["alpha_volume"] * 1e-6) for r in cart_rows]
                volume_source = cart_path
                method_counts[method] += 1
                if recalc_adopted:
                    recalc_count += 1
                source_kind = "recalculated_agv2" if recalc_adopted else "original_agv2"
                cart_source = cart_path
                directional_source = directional_path
                curve_min, curve_max = cart_rows[0]["T_K"], cart_rows[-1]["T_K"]
            elif (iso_dir / "POSCAR").is_file():
                method = "QHA"
                structure_dir = iso_dir
                recalc_adopted = False
                recalc_status = "not_applicable"
                scalar_path = iso_dir / "thermal_expansion.dat"
                scalar_points, curve_min, curve_max = _read_scalar_qha(scalar_path)
                volume_points = scalar_points
                volume_source = scalar_path
                # Derive a tensor-aware representation for an isotropic cubic
                # material; it is explicit and marked as derived below.
                cart_rows = []
                directional_rows = []
                cart_header = list(CURVE_COLUMNS["cartesian"])
                directional_header = list(CURVE_COLUMNS["directional"])
                for temperature, alpha_volume_si in scalar_points:
                    volume_ppm = alpha_volume_si * 1e6
                    linear_ppm = volume_ppm / 3.0
                    cart_rows.append({
                        "T_K": temperature, "alpha_xx": linear_ppm, "alpha_yy": linear_ppm,
                        "alpha_zz": linear_ppm, "alpha_yz_eng": 0.0, "alpha_xz_eng": 0.0,
                        "alpha_xy_eng": 0.0, "alpha_volume": volume_ppm,
                    })
                    directional_rows.append({
                        "T_K": temperature, "alpha_a": linear_ppm, "alpha_b": linear_ppm,
                        "alpha_c": linear_ppm, "alpha_volume": volume_ppm, "F_ani": 0.0,
                    })
                method_counts[method] += 1
                source_kind = "derived_isotropic_qha"
                cart_source = scalar_path
                directional_source = scalar_path
                recalc_status = "not_applicable"
            else:
                raise ValueError(f"No POSCAR source for selected MP id {external_id}: {material_key}")

            poscar_path = structure_dir / "POSCAR"
            tensor_path = structure_dir / "ELASTIC_TENSOR"
            if not tensor_path.is_file():
                raise ValueError(f"Missing ELASTIC_TENSOR: {tensor_path}")
            target.execute(
                "INSERT INTO materials(material_key,formula,external_id) VALUES (?,?,?) ON CONFLICT(material_key) DO UPDATE SET formula=excluded.formula, external_id=excluded.external_id",
                (material_key, formula, external_id),
            )
            material_id = int(target.execute("SELECT id FROM materials WHERE material_key=?", (material_key,)).fetchone()[0])
            target.execute(
                "INSERT INTO dataset_memberships VALUES (?,?,?,?)",
                (release_id, material_id, ordinal, sha256_json(row)),
            )
            poscar = poscar_path.read_text(encoding="utf-8", errors="replace")
            tensor = tensor_path.read_text(encoding="utf-8", errors="replace")
            target.executemany(
                "INSERT INTO structures(dataset_release_id,material_id,format,content,content_sha256) VALUES (?,?,?,?,?)",
                [(release_id, material_id, "POSCAR", poscar, sha256_text(poscar)),
                 (release_id, material_id, "ELASTIC_TENSOR", tensor, sha256_text(tensor))],
            )
            for name, value in row.items():
                if name in {"material_folder", "formula"}:
                    continue
                _insert_property(target, release_id, material_id, name, value)
            extra = {
                "thermal_expansion_method": method,
                "thermal_expansion_source_kind": source_kind,
                "thermal_expansion_curve_kinds": "cartesian,directional,volumetric",
                "thermal_expansion_curve_unit": "ppm/K (tensor files); 1/K (legacy scalar curve)",
                "recalculation_adopted": recalc_adopted,
                "recalculation_status": recalc_status,
                "formula_resolved": formula,
            }
            for name, value in extra.items():
                _insert_property(target, release_id, material_id, name, value)
            logical_cart = _logical_curve_path(slug, material_key, "thermal_expansion_cartesian.dat")
            logical_directional = _logical_curve_path(slug, material_key, "thermal_expansion_directional.dat")
            logical_volume = _logical_curve_path(slug, material_key, "thermal_expansion.dat")
            _insert_anisotropic_curve(target, release_id, material_id, "cartesian", cart_header, cart_rows, logical_cart, _sha256(cart_source), method, now)
            _insert_anisotropic_curve(target, release_id, material_id, "directional", directional_header, directional_rows, logical_directional, _sha256(directional_source), method, now)
            _insert_job_and_scalar_curve(
                target, material_id, method, "AGV2" if method == "AGV2" else "QHA", logical_volume,
                volume_points, ["isotropic_tensor_derived" ] if method == "QHA" else [], now,
            )
            inventories.append(
                InventoryRow(
                    material_key=material_key, external_id=external_id, formula=formula, method=method,
                    source_kind=source_kind, poscar_path=str(poscar_path), elastic_tensor_path=str(tensor_path),
                    volumetric_path=str(volume_source), cartesian_path=str(cart_source), directional_path=str(directional_source),
                    volumetric_source_path=logical_volume, cartesian_source_path=logical_cart, directional_source_path=logical_directional,
                    volumetric_sha256=_sha256(volume_source), cartesian_sha256=_sha256(cart_source), directional_sha256=_sha256(directional_source),
                    volumetric_points=len(volume_points), cartesian_points=len(cart_rows), directional_points=len(directional_rows),
                    temperature_min_k=float(curve_min), temperature_max_k=float(curve_max), recalc_adopted=recalc_adopted, recalc_status=recalc_status,
                )
            )
        copied_pte = _copy_pte_release(reference_catalog, target)
        target.execute("INSERT OR REPLACE INTO schema_metadata(key,value) VALUES (?,?)", ("catalog_version", "2"))
        target.execute("INSERT OR REPLACE INTO schema_metadata(key,value) VALUES (?,?)", ("catalog_scope", "3665 H-free NTE materials with tensor-aware AGV2/QHA curves plus the reference PTE release"))
        target.execute("PRAGMA foreign_keys=ON")
        if target.execute("PRAGMA foreign_key_check").fetchall():
            raise ValueError("Foreign-key check failed while building release")
        if target.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("SQLite integrity check failed while building release")
        target.commit()
        target.execute("VACUUM")
    temp_db.replace(output)

    inventory_path = output.with_suffix(output.suffix + ".inventory.csv")
    with inventory_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(asdict(inventories[0])))
        writer.writeheader()
        writer.writerows(asdict(item) for item in inventories)
    selection_copy = output.with_suffix(output.suffix + ".selection.csv")
    shutil.copy2(selection_csv, selection_copy)
    manifest_path = output.with_suffix(output.suffix + ".manifest.json")
    source_counts = {
        "AGV2": method_counts["AGV2"], "QHA": method_counts["QHA"],
        "recalculated_adopted": recalc_count, "PTE_reference": copied_pte,
        "cartesian_curves": len(inventories), "directional_curves": len(inventories),
        "volumetric_curves": len(inventories),
    }
    release_manifest = {
        "catalog_version": "2",
        "database_file": output.name,
        "database_sha256": _sha256(output),
        "file_bytes": output.stat().st_size,
        "release_slug": slug,
        "counts": source_counts,
        "selection_csv": selection_copy.name,
        "inventory_csv": inventory_path.name,
        "source_contract": manifest,
        "created_at": now,
    }
    manifest_path.write_text(json.dumps(release_manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    provenance_path = output.with_suffix(output.suffix + ".provenance.json")
    provenance_path.write_text(json.dumps({
        "release": release_manifest,
        "research_sources": {
            "selection_csv": str(selection_csv),
            "anisotropic_root": str(anisotropic_root),
            "isotropic_root": str(isotropic_root),
            "recalculation_audit": str(recalc_audit_path) if recalc_audit_path else None,
            "reference_catalog": str(reference_catalog),
        },
        "matching": "external_id MP id parsed from material_folder; formula is not used as a join key",
        "notes": [
            "The selected CTE_ppm property is retained as the release screening statistic; the stored alpha(T) curves are the full source curves.",
            "For AGV2, alpha_volume from Cartesian is mirrored into the legacy scalar curve in 1/K.",
            "For cubic QHA, Cartesian/directional representations are explicit isotropic derivations and are flagged in material_properties.",
        ],
    }, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {
        "database": str(output), "manifest": str(manifest_path), "inventory": str(inventory_path),
        "provenance": str(provenance_path), "records": len(inventories), "counts": source_counts,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selection-csv", required=True)
    parser.add_argument("--anisotropic-root", required=True)
    parser.add_argument("--isotropic-root", required=True)
    parser.add_argument("--reference-catalog", required=True)
    parser.add_argument("--recalc-audit")
    parser.add_argument("--output", required=True)
    parser.add_argument("--release-slug", default="nte-candidates-3665-agv2-v2")
    args = parser.parse_args()
    print(json.dumps(build_catalog(args), ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
