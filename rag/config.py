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

# Embedding model (fastembed). bge-small reads at most 512 tokens per input.
EMBED_MODEL = os.environ.get("EMBED_MODEL", "BAAI/bge-small-en-v1.5")
MODEL_CACHE_DIR = _path("MODEL_CACHE_DIR", ".cache/fastembed")

# Chunk sizes in model tokens: body + prefix must stay under the model's 512-token limit
CHUNK_MAX_TOKENS = int(os.environ.get("CHUNK_MAX_TOKENS", 350))
CHUNK_OVERLAP_TOKENS = int(os.environ.get("CHUNK_OVERLAP_TOKENS", 50))
CHUNK_PREFIX_MAX_TOKENS = int(os.environ.get("CHUNK_PREFIX_MAX_TOKENS", 150))
