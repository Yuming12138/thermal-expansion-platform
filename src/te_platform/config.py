from __future__ import annotations

import os
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATABASE_PATH = PROJECT_ROOT / "var" / "dev.db"
DEFAULT_RELEASE_SLUG = "nte-candidates-6701-v1-1"
DEFAULT_DATASET_PATH = (
    PROJECT_ROOT
    / "datasets"
    / "releases"
    / "nte_candidates_6701_v1_1"
    / "nte_candidates_6701.json.gz"
)
DEFAULT_MANIFEST_PATH = (
    PROJECT_ROOT / "datasets" / "manifests" / "nte_candidates_6701_v1_1.json"
)


def database_path() -> Path:
    return Path(os.environ.get("TEP_DATABASE_PATH", DEFAULT_DATABASE_PATH))
