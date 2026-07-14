from __future__ import annotations

from pathlib import Path

from te_platform.catalog.installer import install_catalog_from_public_bundle
from te_platform.catalog.queries import dataset_summary
from te_platform.config import DEFAULT_PTE_RELEASE_SLUG, DEFAULT_RELEASE_SLUG
from te_platform.db.schema import connect_readonly_database, initialize_database


def ensure_catalog_database(
    database_path: str | Path,
    *,
    allow_download: bool = False,
    bundle_url: str | None = None,
    checksum_url: str | None = None,
) -> None:
    path = Path(database_path)
    if not path.is_file():
        if allow_download:
            try:
                print(
                    "[TEP] Catalog database is missing; downloading and verifying the public catalog bundle...",
                    flush=True,
                )
                install_catalog_from_public_bundle(
                    path,
                    bundle_url=bundle_url,
                    checksum_url=checksum_url,
                )
                print(f"[TEP] Catalog installed at {path}", flush=True)
            except Exception as error:
                raise RuntimeError(
                    f"Catalog database is missing and automatic installation failed: {error}. "
                    "Download the public portable release or set TEP_CATALOG_BUNDLE_URL."
                ) from error
        else:
            raise RuntimeError(
                f"Catalog database is missing: {path}. Build or install catalog-v1.sqlite first."
            )
    with connect_readonly_database(path) as connection:
        slugs = {
            row["slug"]
            for row in connection.execute(
                "SELECT slug FROM dataset_releases WHERE slug IN (?,?)",
                (DEFAULT_RELEASE_SLUG, DEFAULT_PTE_RELEASE_SLUG),
            )
        }
    missing = {DEFAULT_RELEASE_SLUG, DEFAULT_PTE_RELEASE_SLUG} - slugs
    if missing:
        raise RuntimeError(f"Catalog database lacks required releases: {sorted(missing)}")


def ensure_workspace_database(database_path: str | Path) -> None:
    initialize_database(database_path)


def active_dataset_summary(database_path: str | Path) -> dict[str, object]:
    ensure_catalog_database(database_path)
    return dataset_summary(database_path, DEFAULT_RELEASE_SLUG)
