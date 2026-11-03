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
# Measured on a 4-core Intel i5: batch 1 = 12 chunks/s, 8 = 7.8, 64 = 5.3. Batches are padded
# to their longest input, and that padding costs more than batching saves on this CPU.
EMBED_BATCH_SIZE = int(os.environ.get("EMBED_BATCH_SIZE", 1))
# BGE recommends this instruction for short search queries (documents get none).
# Set EMBED_QUERY_PREFIX="" in .env to compare without it in the eval.
EMBED_QUERY_PREFIX = os.environ.get(
    "EMBED_QUERY_PREFIX", "Represent this sentence for searching relevant passages: "
)

# Chunk sizes in model tokens: body + prefix must stay under the model's 512-token limit
CHUNK_MAX_TOKENS = int(os.environ.get("CHUNK_MAX_TOKENS", 350))
CHUNK_OVERLAP_TOKENS = int(os.environ.get("CHUNK_OVERLAP_TOKENS", 50))
CHUNK_PREFIX_MAX_TOKENS = int(os.environ.get("CHUNK_PREFIX_MAX_TOKENS", 150))

# Retrieval: chunks handed to the LLM, and how many of them may come from one repository
# (without a cap, a few huge awesome lists fill every slot)
SEARCH_TOP_K = int(os.environ.get("SEARCH_TOP_K", 5))
SEARCH_MAX_PER_REPO = int(os.environ.get("SEARCH_MAX_PER_REPO", 2))
# Chunks scoring below this are dropped. Measured on 25 extra questions: off-topic ones peak at
# 0.65, real ones start at 0.71. With nothing left, /ask declines without calling the LLM.
SEARCH_MIN_SCORE = float(os.environ.get("SEARCH_MIN_SCORE", 0.68))

# LLM (Gemini). The key is a secret: .env locally, a secret store in deployment.
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite")
LLM_MAX_OUTPUT_TOKENS = int(os.environ.get("LLM_MAX_OUTPUT_TOKENS", 2048))
LLM_TIMEOUT_SECONDS = float(os.environ.get("LLM_TIMEOUT_SECONDS", 30))
# Free tier: 15 requests/min, 500/day. Per-minute limits are retried after the delay Gemini
# suggests, unless that delay is longer than a caller should wait; the daily limit never is.
LLM_MAX_RETRIES = int(os.environ.get("LLM_MAX_RETRIES", 2))
LLM_MAX_RETRY_WAIT_SECONDS = float(os.environ.get("LLM_MAX_RETRY_WAIT_SECONDS", 20))

# API: /health flags the index as stale when the last build is older than this
INDEX_STALE_DAYS = int(os.environ.get("INDEX_STALE_DAYS", 14))
QUESTION_MAX_CHARS = int(os.environ.get("QUESTION_MAX_CHARS", 500))
