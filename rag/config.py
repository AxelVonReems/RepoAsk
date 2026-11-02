"""Settings for the RAG side. Mirrors ingest/src/config.ts: non-secret defaults live here,
.env (at the repo root) can override them, secrets only ever come from the environment."""

import os
from pathlib import Path

from dotenv import load_dotenv

# Repo root (rag/config.py -> ..). .env and data/ are shared with the ingest worker.
ROOT_DIR = Path(__file__).resolve().parent.parent

load_dotenv(ROOT_DIR / ".env")


def _path(env_name: str, default: str) -> Path:
    """Relative paths resolve against the repo root, like DB_PATH in config.ts."""
    return ROOT_DIR / os.environ.get(env_name, default)


# Input written by the ingest worker, output read by the API
WORKER_DB_PATH = _path("DB_PATH", "data/worker.db")
INDEX_DB_PATH = _path("INDEX_DB_PATH", "data/index.db")

# READMEs are truncated to this many bytes before chunking (median is ~12 KB)
README_MAX_BYTES = int(os.environ.get("README_MAX_BYTES", 30_000))
