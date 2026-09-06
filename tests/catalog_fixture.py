"""Shared fixture helpers for building a disposable catalog database.

The repository ships the full 6701-record NTE snapshot in Git LFS
(``datasets/releases/nte_candidates_6701_v1_1``), so the API test suite can
exercise real data without the maintainer's ``var/releases/catalog-v1.sqlite``
or the original research directories.  The PTE reference release and most
historical QHA curves are *not* in the repository; tests that need a curve use
the synthetic one injected here for the ``BaCrSi4O10`` material.

The fixture only writes inside the provided temporary path; it never touches
``var/``.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from te_platform.catalog.importer import ImportSummary, import_dataset
from te_platform.db.schema import connect_database
from te_platform.jobs.repository import import_historical_thermal_expansion_curve

REPO_ROOT = Path(__file__).resolve().parents[1]

NTE_SNAPSHOT = (
    REPO_ROOT
    / "datasets"
    / "releases"
    / "nte_candidates_6701_v1_1"
    / "nte_candidates_6701.json.gz"
)
NTE_MANIFEST = REPO_ROOT / "datasets" / "manifests" / "nte_candidates_6701_v1_1.json"

CURVED_MATERIAL_KEY_PREFIX = "BaCrSi4O10"
PTE_MATERIAL_KEY = "Ag(AuF4)2-mp-18125"
PTE_RELEASE_SLUG = "pte-reference-185-v1"

# Synthetic legacy-style volumetric alpha(T) in 1/K.  Monotonic temperatures,
# |alpha| < 1, and the 300 K sign selects the material's composite role.
NTE_CURVE: tuple[tuple[float, float], ...] = (
    (0.0, 0.0),
    (150.0, -4.0e-6),
    (300.0, -1.0e-5),
    (600.0, -1.8e-5),
    (990.0, -2.6e-5),
)
PTE_CURVE: tuple[tuple[float, float], ...] = (
    (0.0, 0.0),
    (150.0, 3.0e-6),
    (300.0, 8.0e-6),
    (600.0, 1.5e-5),
    (990.0, 2.2e-5),
)


def build_catalog_database(target: Path) -> ImportSummary:
    """Import the released NTE snapshot and attach one synthetic QHA curve."""
    summary = import_dataset(target, NTE_SNAPSHOT, NTE_MANIFEST)

    with connect_database(target) as connection:
        _register_pte_placeholder(connection)
        _inject_synthetic_curve(connection, summary.release_slug)

    return summary


def _register_pte_placeholder(connection: sqlite3.Connection) -> None:
    """Register a minimal PTE release so app startup validation passes.

    The real 185-record PTE reference set comes from the maintainer's research
    directories and is not redistributable.  The fixture adds one shared
    material after registration so composite endpoints can be exercised.
    """
    connection.execute(
        """INSERT INTO dataset_releases
           (slug, title, version, record_count, source_file_name, source_sha256,
            manifest_json, imported_at)
           VALUES (?, ?, ?, 0, ?, ?, ?, ?)""",
        (
            "pte-reference-185-v1",
            "PTE 参考材料（测试占位，无记录）",
            "1.0.0",
            "synthetic://tests/pte-placeholder.json",
            "0" * 64,
            "{}",
            "1970-01-01T00:00:00Z",
        ),
    )


def _inject_synthetic_curve(connection: sqlite3.Connection, nte_release_slug: str) -> None:
    nte_material_id = _find_material_id(connection, CURVED_MATERIAL_KEY_PREFIX)
    pte_material_id = _find_material_id(connection, PTE_MATERIAL_KEY)
    import_historical_thermal_expansion_curve(
        connection,
        material_id=nte_material_id,
        source_path="synthetic://tests/bacrsi4o10-qha/thermal_expansion.dat",
        thermal_expansion_curve=NTE_CURVE,
        alpha_300k_per_k=-1.0e-5,
    )
    import_historical_thermal_expansion_curve(
        connection,
        material_id=pte_material_id,
        source_path="synthetic://tests/agau4f2-qha/thermal_expansion.dat",
        thermal_expansion_curve=PTE_CURVE,
        alpha_300k_per_k=8.0e-6,
    )
    # 把 PTE 角色材料同时挂到 PTE release 上，composite 端点才能按角色取到它。
    connection.execute(
        """INSERT INTO dataset_memberships
           (dataset_release_id, material_id, ordinal, source_record_sha256)
           SELECT id, ?, 0, ?
           FROM dataset_releases WHERE slug = ?""",
        (pte_material_id, "0" * 64, PTE_RELEASE_SLUG),
    )
    # The PTE fixture reuses one material from the NTE snapshot.  Mirror its
    # release-scoped structure/properties so composite detail and download
    # endpoints exercise the same contract as a real PTE release instead of
    # returning an empty placeholder record.
    connection.execute(
        """
        INSERT INTO structures(
            dataset_release_id, material_id, format, content,
            content_sha256
        )
        SELECT pte.id, s.material_id, s.format, s.content, s.content_sha256
        FROM structures s
        JOIN dataset_releases nte ON nte.id = s.dataset_release_id
        JOIN dataset_releases pte ON pte.slug = ?
        WHERE nte.slug = ? AND s.material_id = ?
        """,
        (PTE_RELEASE_SLUG, nte_release_slug, pte_material_id),
    )
    connection.execute(
        """
        INSERT INTO material_properties(
            dataset_release_id, material_id, name, numeric_value,
            text_value, unit
        )
        SELECT pte.id, mp.material_id, mp.name, mp.numeric_value,
               mp.text_value, mp.unit
        FROM material_properties mp
        JOIN dataset_releases nte ON nte.id = mp.dataset_release_id
        JOIN dataset_releases pte ON pte.slug = ?
        WHERE nte.slug = ? AND mp.material_id = ?
        """,
        (PTE_RELEASE_SLUG, nte_release_slug, pte_material_id),
    )
    connection.execute(
        "UPDATE dataset_releases SET record_count = 1 WHERE slug = ?",
        (PTE_RELEASE_SLUG,),
    )


def _find_material_id(connection: sqlite3.Connection, key_prefix: str) -> int:
    row = connection.execute(
        """SELECT m.id
           FROM materials m
           JOIN dataset_memberships dm ON dm.material_id = m.id
           WHERE m.material_key LIKE ?
           ORDER BY m.material_key
           LIMIT 1""",
        (key_prefix + "%",),
    ).fetchone()
    if row is None:
        raise ValueError(
            f"Fixture material with key prefix {key_prefix!r} "
            "was not found in the imported snapshot"
        )
    return int(row["id"])
