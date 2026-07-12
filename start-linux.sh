#!/usr/bin/env sh
set -eu

PROJECT_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
RUNTIME_ROOT="$PROJECT_ROOT/.runtime"
PORT=${TEP_PORT:-8000}

case "$PORT" in
  ''|*[!0-9]*)
    echo "TEP_PORT must be an integer between 1 and 65535." >&2
    exit 1
    ;;
esac

if ! command -v uv >/dev/null 2>&1; then
  echo "uv was not found. Install uv and run this file again." >&2
  echo "https://docs.astral.sh/uv/getting-started/installation/" >&2
  exit 1
fi

mkdir -p "$RUNTIME_ROOT"
export PYTHONUTF8=1
export PYTHONPATH="$PROJECT_ROOT/src"
export UV_PROJECT_ENVIRONMENT="$RUNTIME_ROOT/venv"
export UV_CACHE_DIR="$RUNTIME_ROOT/uv-cache"
export UV_PYTHON_INSTALL_DIR="$RUNTIME_ROOT/python"
export UV_PYTHON=3.11
export UV_MANAGED_PYTHON=1
export UV_LINK_MODE=copy
export TEP_CATALOG_DATABASE_PATH="$PROJECT_ROOT/var/releases/catalog-v1.sqlite"
export TEP_WORKSPACE_DATABASE_PATH="$PROJECT_ROOT/var/workspace.sqlite"

cd "$PROJECT_ROOT"
echo "Preparing the project-local portable environment..."
uv sync --frozen --no-dev --no-install-project --python 3.11 --managed-python
echo "Starting http://127.0.0.1:$PORT/"
echo "Press Ctrl+C to stop the platform."
exec uv run --frozen --no-sync python -m te_platform.launcher --port "$PORT"
