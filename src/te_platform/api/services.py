from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from te_platform.catalog.installer import install_catalog_from_public_bundle
from te_platform.catalog.queries import dataset_summary
from te_platform.config import DEFAULT_PTE_RELEASE_SLUG, DEFAULT_RELEASE_SLUG
from te_platform.db.schema import connect_readonly_database, initialize_database


def _normalize_required_release_slugs(
    release_slugs: Iterable[str] | None,
) -> tuple[str, ...]:
    raw_slugs = (
        (DEFAULT_RELEASE_SLUG, DEFAULT_PTE_RELEASE_SLUG)
        if release_slugs is None
        else release_slugs
    )
    required = tuple(
        dict.fromkeys(
            str(slug).strip()
            for slug in raw_slugs
            if str(slug).strip()
        )
    )
    if not required:
        raise ValueError("At least one catalog release slug is required")
    return required


def ensure_catalog_database(
    database_path: str | Path,
    *,
    allow_download: bool = False,
    bundle_url: str | None = None,
    checksum_url: str | None = None,
    required_release_slugs: Iterable[str] | None = None,
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
    required = _normalize_required_release_slugs(required_release_slugs)
    placeholders = ",".join("?" for _ in required)
    with connect_readonly_database(path) as connection:
        slugs = {
            row["slug"]
            for row in connection.execute(
                f"SELECT slug FROM dataset_releases WHERE slug IN ({placeholders})",
                required,
            )
        }
    missing = set(required) - slugs
    if missing:
        raise RuntimeError(f"Catalog database lacks required releases: {sorted(missing)}")


def ensure_workspace_database(database_path: str | Path) -> None:
    initialize_database(database_path)


def active_dataset_summary(
    database_path: str | Path,
    release_slug: str | None = None,
    *,
    required_release_slugs: Iterable[str] | None = None,
) -> dict[str, object]:
    required = _normalize_required_release_slugs(required_release_slugs)
    requested_slug = str(release_slug).strip() if release_slug is not None else ""
    active_slug = requested_slug or (required[0] if required else DEFAULT_RELEASE_SLUG)
    ensure_catalog_database(
        database_path,
        required_release_slugs=required,
    )
    return dataset_summary(database_path, active_slug)
