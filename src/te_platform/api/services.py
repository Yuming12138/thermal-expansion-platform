from __future__ import annotations

from pathlib import Path

from te_platform.catalog.importer import import_dataset
from te_platform.catalog.queries import dataset_summary
from te_platform.config import DEFAULT_DATASET_PATH, DEFAULT_MANIFEST_PATH, DEFAULT_RELEASE_SLUG
from te_platform.db.schema import connect_database, initialize_database


def ensure_active_database(database_path: str | Path) -> None:
    path = Path(database_path)
    initialize_database(path)
    with connect_database(path) as connection:
        present = connection.execute(
            "SELECT 1 FROM dataset_releases WHERE slug = ?",
            (DEFAULT_RELEASE_SLUG,),
        ).fetchone()
    if present is None:
        import_dataset(path, DEFAULT_DATASET_PATH, DEFAULT_MANIFEST_PATH)


def active_dataset_summary(database_path: str | Path) -> dict[str, object]:
    ensure_active_database(database_path)
    return dataset_summary(database_path, DEFAULT_RELEASE_SLUG)
