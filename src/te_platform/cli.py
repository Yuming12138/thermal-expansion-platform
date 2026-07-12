from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Sequence

from te_platform.catalog.importer import import_dataset
from te_platform.catalog.qha_curve_importer import import_historical_qha_curves
from te_platform.catalog.release_catalog import build_release_catalog
from te_platform.catalog.pte_importer import import_pte_reference
from te_platform.catalog.queries import material_detail, search_materials
from te_platform.composites.rom import optimize_zte_fraction
from te_platform.config import (
    DEFAULT_DATASET_PATH,
    DEFAULT_MANIFEST_PATH,
    DEFAULT_RELEASE_SLUG,
    catalog_database_path,
    database_path,
)
from te_platform.db.schema import connect_readonly_database, initialize_database
from te_platform.screening.fast_sbr import fast_screen_sbr
from te_platform.screening.sbr import classify_sbr


def _json_output(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


def _database_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--db", type=Path, default=database_path())


def _catalog_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--db", type=Path, default=catalog_database_path())


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tep")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_db = subparsers.add_parser("init-db", help="Initialize the platform database")
    _database_argument(init_db)

    importer = subparsers.add_parser("import-dataset", help="Import a versioned dataset")
    _database_argument(importer)
    importer.add_argument("--dataset", type=Path, default=DEFAULT_DATASET_PATH)
    importer.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST_PATH)
    importer.add_argument("--replace", action="store_true")

    qha_importer = subparsers.add_parser(
        "import-qha-curves", help="Import complete thermal_expansion.dat curves from QHA result roots"
    )
    _database_argument(qha_importer)
    qha_importer.add_argument("roots", type=Path, nargs="+")

    pte_importer = subparsers.add_parser(
        "import-pte-reference", help="Import a curated PTE release with complete QHA curves"
    )
    _database_argument(pte_importer)
    pte_importer.add_argument("--source-root", type=Path, required=True)
    pte_importer.add_argument("--summary-csv", type=Path, required=True)
    pte_importer.add_argument("--replace", action="store_true")

    release_catalog = subparsers.add_parser(
        "build-release-catalog", help="Build a sanitized standalone catalog database"
    )
    release_catalog.add_argument("--source-db", type=Path, default=catalog_database_path())
    release_catalog.add_argument("--output", type=Path, required=True)
    release_catalog.add_argument("--replace", action="store_true")

    stats = subparsers.add_parser("dataset-stats", help="Show imported dataset statistics")
    _catalog_argument(stats)
    stats.add_argument("--release", default=DEFAULT_RELEASE_SLUG)

    search = subparsers.add_parser("search-materials", help="Search the material catalog")
    _catalog_argument(search)
    search.add_argument("--release", default=DEFAULT_RELEASE_SLUG)
    search.add_argument("--query", default="")
    search.add_argument("--limit", type=int, default=20)

    detail = subparsers.add_parser("material-detail", help="Show material properties")
    _catalog_argument(detail)
    detail.add_argument("material_key")
    detail.add_argument("--release", default=DEFAULT_RELEASE_SLUG)

    sbr = subparsers.add_parser("classify-sbr", help="Classify thermal expansion by SBR")
    sbr.add_argument("--g", type=float, required=True, help="Shear modulus in GPa")
    sbr.add_argument(
        "--e-tilde", type=float, required=True, help="Bonding modulus in GPa"
    )

    fast_sbr = subparsers.add_parser(
        "fast-screen", help="Combine ALIGNN G with fast bonding descriptors"
    )
    fast_sbr.add_argument("--g-pred", type=float, required=True)
    fast_sbr.add_argument("--e-coh", type=float, required=True)
    fast_sbr.add_argument("--cell-volume", type=float, required=True)
    fast_sbr.add_argument("--atom-count", type=int, required=True)
    fast_sbr.add_argument("--avg-cn", type=float, required=True)
    fast_sbr.add_argument("--g-mae", type=float, default=9.476007)

    rom = subparsers.add_parser("optimize-zte", help="Optimize two-phase ROM fraction")
    rom.add_argument("--alpha-pte", type=float, required=True)
    rom.add_argument("--alpha-nte", type=float, required=True)
    rom.add_argument("--target", type=float, default=0.0)
    return parser


def _dataset_stats(db_path: Path, release_slug: str) -> dict[str, Any]:
    with connect_readonly_database(db_path) as connection:
        release = connection.execute(
            """
            SELECT id, slug, title, version, record_count, source_file_name,
                   source_sha256, imported_at
            FROM dataset_releases
            WHERE slug = ?
            """,
            (release_slug,),
        ).fetchone()
        if release is None:
            raise ValueError(f"Dataset release is not imported: {release_slug}")
        counts = connection.execute(
            """
            SELECT
                COUNT(DISTINCT dm.material_id) AS materials,
                COUNT(DISTINCT s.id) AS structures,
                COUNT(DISTINCT mp.name) AS property_fields,
                COUNT(mp.name) AS property_values
            FROM dataset_memberships dm
            LEFT JOIN structures s
              ON s.dataset_release_id = dm.dataset_release_id
             AND s.material_id = dm.material_id
            LEFT JOIN material_properties mp
              ON mp.dataset_release_id = dm.dataset_release_id
             AND mp.material_id = dm.material_id
            WHERE dm.dataset_release_id = ?
            """,
            (release["id"],),
        ).fetchone()
        quality_flags = connection.execute(
            """
            SELECT code, severity, COUNT(*) AS count
            FROM data_quality_flags
            WHERE dataset_release_id = ?
            GROUP BY code, severity
            ORDER BY severity, code
            """,
            (release["id"],),
        ).fetchall()
        return {
            "release": dict(release),
            "counts": dict(counts),
            "quality_flags": [dict(row) for row in quality_flags],
            "database_path": str(db_path.resolve()),
        }


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.command == "init-db":
        initialize_database(args.db)
        _json_output({"database_path": str(args.db.resolve()), "initialized": True})
        return 0
    if args.command == "import-dataset":
        summary = import_dataset(
            args.db,
            args.dataset,
            args.manifest,
            replace=args.replace,
        )
        _json_output(summary.to_dict())
        return 0
    if args.command == "import-qha-curves":
        _json_output(import_historical_qha_curves(args.db, args.roots).to_dict())
        return 0
    if args.command == "import-pte-reference":
        _json_output(
            import_pte_reference(
                args.db,
                args.source_root,
                args.summary_csv,
                replace=args.replace,
            ).to_dict()
        )
        return 0
    if args.command == "build-release-catalog":
        _json_output(
            build_release_catalog(
                args.source_db,
                args.output,
                replace=args.replace,
            ).to_dict()
        )
        return 0
    if args.command == "dataset-stats":
        _json_output(_dataset_stats(args.db, args.release))
        return 0
    if args.command == "search-materials":
        _json_output(search_materials(args.db, args.release, args.query, args.limit))
        return 0
    if args.command == "material-detail":
        _json_output(material_detail(args.db, args.release, args.material_key))
        return 0
    if args.command == "classify-sbr":
        _json_output(classify_sbr(args.g, args.e_tilde).to_dict())
        return 0
    if args.command == "fast-screen":
        _json_output(
            fast_screen_sbr(
                args.g_pred,
                args.e_coh,
                args.cell_volume,
                args.atom_count,
                args.avg_cn,
                shear_model_mae_gpa=args.g_mae,
            ).to_dict()
        )
        return 0
    if args.command == "optimize-zte":
        _json_output(
            optimize_zte_fraction(
                args.alpha_pte,
                args.alpha_nte,
                args.target,
            ).to_dict()
        )
        return 0
    raise AssertionError(f"Unhandled command: {args.command}")
