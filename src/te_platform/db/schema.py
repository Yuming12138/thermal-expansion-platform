from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


SCHEMA_VERSION = 2

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS schema_metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS dataset_releases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    slug TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    version TEXT NOT NULL,
    record_count INTEGER NOT NULL,
    source_file_name TEXT NOT NULL,
    source_sha256 TEXT NOT NULL,
    manifest_json TEXT NOT NULL,
    imported_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS materials (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    material_key TEXT NOT NULL UNIQUE,
    formula TEXT,
    external_id TEXT
);

CREATE TABLE IF NOT EXISTS dataset_memberships (
    dataset_release_id INTEGER NOT NULL,
    material_id INTEGER NOT NULL,
    ordinal INTEGER NOT NULL,
    source_record_sha256 TEXT NOT NULL,
    PRIMARY KEY (dataset_release_id, material_id),
    FOREIGN KEY (dataset_release_id) REFERENCES dataset_releases(id) ON DELETE CASCADE,
    FOREIGN KEY (material_id) REFERENCES materials(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_memberships_release_ordinal
ON dataset_memberships(dataset_release_id, ordinal);

CREATE TABLE IF NOT EXISTS structures (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dataset_release_id INTEGER NOT NULL,
    material_id INTEGER NOT NULL,
    format TEXT NOT NULL,
    content TEXT NOT NULL,
    content_sha256 TEXT NOT NULL,
    UNIQUE(dataset_release_id, material_id, format),
    FOREIGN KEY (dataset_release_id) REFERENCES dataset_releases(id) ON DELETE CASCADE,
    FOREIGN KEY (material_id) REFERENCES materials(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS material_properties (
    dataset_release_id INTEGER NOT NULL,
    material_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    numeric_value REAL,
    text_value TEXT,
    unit TEXT,
    PRIMARY KEY (dataset_release_id, material_id, name),
    FOREIGN KEY (dataset_release_id) REFERENCES dataset_releases(id) ON DELETE CASCADE,
    FOREIGN KEY (material_id) REFERENCES materials(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_properties_name_numeric
ON material_properties(name, numeric_value);

CREATE TABLE IF NOT EXISTS data_quality_flags (
    dataset_release_id INTEGER NOT NULL,
    material_id INTEGER NOT NULL,
    code TEXT NOT NULL,
    severity TEXT NOT NULL,
    message TEXT NOT NULL,
    observed_value_json TEXT,
    PRIMARY KEY (dataset_release_id, material_id, code),
    FOREIGN KEY (dataset_release_id) REFERENCES dataset_releases(id) ON DELETE CASCADE,
    FOREIGN KEY (material_id) REFERENCES materials(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_quality_flags_release_code
ON data_quality_flags(dataset_release_id, code);

CREATE TABLE IF NOT EXISTS calculation_jobs (
    id TEXT PRIMARY KEY,
    material_id INTEGER,
    workflow TEXT NOT NULL,
    model_name TEXT,
    status TEXT NOT NULL,
    parameters_json TEXT NOT NULL,
    result_json TEXT,
    error_message TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (material_id) REFERENCES materials(id)
);

-- The full alpha(T) sequence is a first-class scientific result rather than
-- merely a visualisation artifact.  Keeping it independently queryable also
-- means that importing an existing QHA directory never loses its raw curve.
CREATE TABLE IF NOT EXISTS precision_thermal_expansion_curves (
    job_id TEXT PRIMARY KEY,
    points_json TEXT NOT NULL,
    unit TEXT NOT NULL,
    source_path TEXT,
    parsed_at TEXT NOT NULL,
    FOREIGN KEY (job_id) REFERENCES calculation_jobs(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS composite_designs (
    id TEXT PRIMARY KEY,
    pte_material_id INTEGER,
    nte_material_id INTEGER,
    model_name TEXT NOT NULL,
    parameters_json TEXT NOT NULL,
    result_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (pte_material_id) REFERENCES materials(id),
    FOREIGN KEY (nte_material_id) REFERENCES materials(id)
);
"""


@contextmanager
def connect_database(path: str | Path) -> Iterator[sqlite3.Connection]:
    db_path = Path(path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    try:
        yield connection
    except Exception:
        connection.rollback()
        raise
    else:
        connection.commit()
    finally:
        connection.close()


def initialize_database(path: str | Path) -> None:
    with connect_database(path) as connection:
        connection.executescript(SCHEMA_SQL)
        connection.execute(
            "INSERT OR REPLACE INTO schema_metadata(key, value) VALUES (?, ?)",
            ("schema_version", str(SCHEMA_VERSION)),
        )
