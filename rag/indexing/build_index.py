"""Builds index.db from the ingest worker's worker.db.

    uv run python -m rag.indexing.build_index [--limit N] [--rebuild]

Incremental: a repository is re-embedded only when something that ends up in its chunks
changed (README content, description, topics, name). Stars and URLs are refreshed without
re-embedding. Changing the model, chunk settings or PIPELINE_VERSION rebuilds everything.
Each repository is committed separately, so an interrupted build resumes where it stopped.
"""

import argparse
import hashlib
import json
import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from rag import config
from rag.indexing.chunk import RepoInfo, chunk_readme
from rag.indexing.clean import clean_readme
from rag.indexing.embed import Embedder, FastEmbedEmbedder

# Bump when clean.py or chunk.py change how text is produced: forces a full rebuild
PIPELINE_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS repos (
    id TEXT PRIMARY KEY,
    full_name TEXT NOT NULL,
    url TEXT NOT NULL,
    stars INTEGER NOT NULL,
    description TEXT,
    topics TEXT NOT NULL,
    source_sha TEXT NOT NULL  -- hash of everything that is embedded for this repo
);
CREATE TABLE IF NOT EXISTS chunks (
    id INTEGER PRIMARY KEY,
    repo_id TEXT NOT NULL REFERENCES repos(id) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    heading TEXT NOT NULL,
    body TEXT NOT NULL,
    text TEXT NOT NULL,
    vector BLOB NOT NULL  -- float32, L2-normalized, dim stored in meta
);
CREATE INDEX IF NOT EXISTS chunks_repo_id ON chunks(repo_id);
"""


@dataclass
class SourceRepo:
    id: str
    full_name: str
    url: str
    stars: int
    description: str | None
    topics: tuple[str, ...]
    content: str
    content_sha: str

    @property
    def source_sha(self) -> str:
        parts = [self.content_sha, self.full_name, self.description or "", *self.topics]
        return hashlib.sha256(json.dumps(parts).encode()).hexdigest()


@dataclass
class BuildStats:
    repos: int = 0
    embedded_repos: int = 0
    skipped_repos: int = 0
    removed_repos: int = 0
    embedded_chunks: int = 0
    total_chunks: int = 0
    full_rebuild: bool = False
    seconds: float = 0.0


def build_index(
    worker_db: Path,
    index_db: Path,
    embedder: Embedder,
    limit: int | None = None,
    rebuild: bool = False,
    log: Callable[[str], None] = print,
) -> BuildStats:
    started = time.perf_counter()
    stats = BuildStats()
    sources = _read_worker(worker_db, limit)
    stats.repos = len(sources)

    index_db.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(index_db)
    # Python's sqlite3 leaves foreign keys off by default; ON DELETE CASCADE needs them on
    db.execute("PRAGMA foreign_keys = ON")
    db.executescript(SCHEMA)

    settings = _settings(embedder)
    if rebuild or _meta(db, "settings") != settings:
        log("Settings changed or --rebuild: rebuilding the whole index")
        stats.full_rebuild = True
        with db:
            db.execute("DELETE FROM repos")
            _set_meta(db, settings=settings, dim=str(embedder.dim))

    stats.removed_repos = _remove_stale(db, {s.id for s in sources})
    indexed = dict(db.execute("SELECT id, source_sha FROM repos"))
    todo = [s for s in sources if indexed.get(s.id) != s.source_sha]
    stats.skipped_repos = len(sources) - len(todo)

    # Unchanged repos still get fresh stars and URLs; those are not part of the embedding
    with db:
        db.executemany(
            "UPDATE repos SET stars = ?, url = ? WHERE id = ?",
            [(s.stars, s.url, s.id) for s in sources if indexed.get(s.id) == s.source_sha],
        )

    log(f"{len(sources)} repos: {len(todo)} to embed, {stats.skipped_repos} unchanged")
    progress = _Progress(len(todo), log)
    for source in todo:
        stats.embedded_chunks += _index_repo(db, source, embedder)
        stats.embedded_repos += 1
        progress.update(stats.embedded_repos, stats.embedded_chunks)

    stats.total_chunks = db.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    with db:
        _set_meta(
            db,
            built_at=datetime.now(UTC).isoformat(timespec="seconds"),
            repo_count=str(len(sources)),
            chunk_count=str(stats.total_chunks),
        )
    db.close()

    stats.seconds = round(time.perf_counter() - started, 1)
    return stats


def _read_worker(worker_db: Path, limit: int | None) -> list[SourceRepo]:
    # Read-only: the index build must never modify the worker's database
    db = sqlite3.connect(f"{worker_db.resolve().as_uri()}?mode=ro", uri=True)
    rows = db.execute(
        """
        SELECT r.id, r.fullName, r.url, r.metric, r.description, r.topics,
               m.content, m.contentSha
        FROM repositories r JOIN readmes m ON m.repoId = r.id
        ORDER BY r.metric DESC
        LIMIT ?
        """,
        (limit if limit is not None else -1,),
    ).fetchall()
    db.close()
    return [
        SourceRepo(id, name, url, stars, desc, tuple(json.loads(topics)), content, sha)
        for id, name, url, stars, desc, topics, content, sha in rows
    ]


def _settings(embedder: Embedder) -> str:
    """Everything that changes the vectors of every chunk. A mismatch forces a full rebuild."""
    return json.dumps(
        {
            "pipeline_version": PIPELINE_VERSION,
            "model": embedder.model_name,
            "dim": embedder.dim,
            "readme_max_bytes": config.README_MAX_BYTES,
            "chunk_max_tokens": config.CHUNK_MAX_TOKENS,
            "chunk_overlap_tokens": config.CHUNK_OVERLAP_TOKENS,
            "chunk_prefix_max_tokens": config.CHUNK_PREFIX_MAX_TOKENS,
        },
        sort_keys=True,
    )


def _remove_stale(db: sqlite3.Connection, keep: set[str]) -> int:
    stale = [(repo_id,) for (repo_id,) in db.execute("SELECT id FROM repos") if repo_id not in keep]
    with db:
        db.executemany("DELETE FROM repos WHERE id = ?", stale)
    return len(stale)


def _index_repo(db: sqlite3.Connection, source: SourceRepo, embedder: Embedder) -> int:
    repo = RepoInfo(source.full_name, source.description, source.topics)
    chunks = chunk_readme(clean_readme(source.content), repo, embedder.count_tokens)
    vectors = embedder.embed_documents([c.text for c in chunks])

    # One transaction per repo: an interrupted build keeps every repo finished so far
    with db:
        db.execute("DELETE FROM repos WHERE id = ?", (source.id,))
        db.execute(
            "INSERT INTO repos VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                source.id,
                source.full_name,
                source.url,
                source.stars,
                source.description,
                json.dumps(source.topics),
                source.source_sha,
            ),
        )
        db.executemany(
            "INSERT INTO chunks (repo_id, position, heading, body, text, vector) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [
                (source.id, i, c.heading, c.body, c.text, v.astype(np.float32).tobytes())
                for i, (c, v) in enumerate(zip(chunks, vectors, strict=True))
            ],
        )
    return len(chunks)


def _meta(db: sqlite3.Connection, key: str) -> str | None:
    row = db.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row[0] if row else None


def _set_meta(db: sqlite3.Connection, **values: str) -> None:
    db.executemany(
        "INSERT INTO meta (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        values.items(),
    )


class _Progress:
    """Logs repos done, embedding speed and ETA at most every few seconds."""

    def __init__(self, total: int, log: Callable[[str], None], every_seconds: float = 10) -> None:
        self.total, self.log, self.every = total, log, every_seconds
        self.started = self.last = time.perf_counter()

    def update(self, done: int, chunks: int) -> None:
        now = time.perf_counter()
        if now - self.last < self.every and done < self.total:
            return
        self.last = now
        elapsed = now - self.started
        eta_min = elapsed / done * (self.total - done) / 60
        self.log(
            f"  [{done}/{self.total}] {chunks:,} chunks, "
            f"{chunks / elapsed:.1f} chunks/s, ETA {eta_min:.0f} min"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Build index.db from worker.db")
    parser.add_argument("--limit", type=int, help="only the top N repos by stars (fast subset)")
    parser.add_argument("--rebuild", action="store_true", help="re-embed everything")
    args = parser.parse_args()

    stats = build_index(
        config.WORKER_DB_PATH,
        config.INDEX_DB_PATH,
        FastEmbedEmbedder(),
        limit=args.limit,
        rebuild=args.rebuild,
    )
    print(json.dumps(stats.__dict__, indent=2))


if __name__ == "__main__":
    main()
