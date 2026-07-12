from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CATALOG_DATABASE_PATH = PROJECT_ROOT / "var" / "releases" / "catalog-v1.sqlite"
DEFAULT_WORKSPACE_DATABASE_PATH = PROJECT_ROOT / "var" / "workspace.sqlite"
DEFAULT_AGENT_BASE_URL = "https://api.cmsg666.xyz/v1"
DEFAULT_AGENT_MODEL = "gpt-5.6-luna"
DEFAULT_AGENT_ENV_PATH = PROJECT_ROOT / "var" / "config" / "agent.env"
DEFAULT_RELEASE_SLUG = "nte-candidates-6701-v1-1"
DEFAULT_PTE_RELEASE_SLUG = "pte-reference-185-v1"
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
    """Backward-compatible writable database path for CLI and worker code."""
    return workspace_database_path()


def catalog_database_path() -> Path:
    return Path(
        os.environ.get("TEP_CATALOG_DATABASE_PATH", DEFAULT_CATALOG_DATABASE_PATH)
    )


def workspace_database_path() -> Path:
    return Path(
        os.environ.get(
            "TEP_WORKSPACE_DATABASE_PATH",
            os.environ.get("TEP_DATABASE_PATH", DEFAULT_WORKSPACE_DATABASE_PATH),
        )
    )


@dataclass(frozen=True)
class AgentSettings:
    base_url: str
    model: str
    api_key: str | None
    timeout_seconds: float

    @property
    def configured(self) -> bool:
        return bool(self.api_key)


def load_agent_env(path: Path | None = None) -> dict[str, str]:
    env_path = path or DEFAULT_AGENT_ENV_PATH
    if not env_path.is_file():
        return {}
    allowed = {
        "TEP_AGENT_BASE_URL",
        "TEP_AGENT_MODEL",
        "TEP_AGENT_API_KEY",
        "TEP_AGENT_TIMEOUT_SECONDS",
    }
    values: dict[str, str] = {}
    for raw_line in env_path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key in allowed:
            values[key] = value.strip().strip('"').strip("'")
    return values


def agent_settings() -> AgentSettings:
    local_env = load_agent_env()

    def setting(name: str, default: str | None = None) -> str | None:
        return os.environ.get(name, local_env.get(name, default))

    return AgentSettings(
        base_url=(setting("TEP_AGENT_BASE_URL", DEFAULT_AGENT_BASE_URL) or DEFAULT_AGENT_BASE_URL).rstrip("/"),
        model=setting("TEP_AGENT_MODEL", DEFAULT_AGENT_MODEL) or DEFAULT_AGENT_MODEL,
        api_key=setting("TEP_AGENT_API_KEY") or None,
        timeout_seconds=float(setting("TEP_AGENT_TIMEOUT_SECONDS", "120") or "120"),
    )
