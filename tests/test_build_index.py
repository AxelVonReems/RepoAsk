import hashlib
import json
import sqlite3
from collections.abc import Sequence
from pathlib import Path

import numpy as np
import pytest

from rag.indexing.build_index import build_index


class FakeEmbedder:
    """Deterministic stand-in: hashes words into an 8-dim vector. Records what it embedded."""

    model_name = "fake"
    dim = 8

    def __init__(self) -> None:
        self.embedded: list[str] = []

    def embed_documents(self, texts: Sequence[str]) -> np.ndarray:
        self.embedded.extend(texts)
        return np.stack([self._vector(t) for t in texts]) if texts else np.empty((0, 8))

    def embed_query(self, text: str) -> np.ndarray:
        return self._vector(text)

    def count_tokens(self, text: str) -> int:
        return len(text.split())

    def _vector(self, text: str) -> np.ndarray:
        v = np.zeros(self.dim, dtype=np.float32)
        for word in text.split():
            v[int(hashlib.md5(word.encode()).hexdigest(), 16) % self.dim] += 1
        return v / (np.linalg.norm(v) or 1)


@pytest.fixture
def worker_db(tmp_path: Path) -> Path:
    """A minimal worker.db with the columns build_index reads, as the Node worker creates them."""
    path = tmp_path / "worker.db"
    db = sqlite3.connect(path)
    db.executescript(
        """
        CREATE TABLE repositories (id TEXT PRIMARY KEY, fullName TEXT, url TEXT, metric INTEGER,
                                   description TEXT, topics TEXT);
        CREATE TABLE readmes (repoId TEXT PRIMARY KEY, content TEXT, contentSha TEXT);
        """
    )
    db.close()
    for repo_id, stars in (("1", 300), ("2", 200), ("3", 100)):
        set_repo(path, repo_id, stars=stars, readme=f"# Repo {repo_id}\nIt does thing {repo_id}.")
    return path


def set_repo(path: Path, repo_id: str, stars: int = 1, readme: str = "# R", **fields) -> None:
    db = sqlite3.connect(path)
    db.execute(
        "INSERT OR REPLACE INTO repositories VALUES (?, ?, ?, ?, ?, ?)",
        (
            repo_id,
            fields.get("name", f"owner/repo{repo_id}"),
            f"https://github.com/owner/repo{repo_id}",
            stars,
            fields.get("description", f"Repo number {repo_id}"),
            json.dumps(fields.get("topics", ["demo"])),
        ),
    )
    sha = hashlib.sha256(readme.encode()).hexdigest()
    db.execute("INSERT OR REPLACE INTO readmes VALUES (?, ?, ?)", (repo_id, readme, sha))
    db.commit()
    db.close()


def build(worker_db: Path, embedder: FakeEmbedder | None = None, **kwargs):
    embedder = embedder or FakeEmbedder()
    stats = build_index(
        worker_db, worker_db.parent / "index.db", embedder, log=lambda _: None, **kwargs
    )
    return stats, embedder


def query(worker_db: Path, sql: str, *args):
    db = sqlite3.connect(worker_db.parent / "index.db")
    rows = db.execute(sql, args).fetchall()
    db.close()
    return rows


def test_first_build_indexes_every_repo(worker_db: Path):
    stats, embedder = build(worker_db)

    assert stats.full_rebuild
    assert (stats.repos, stats.embedded_repos, stats.skipped_repos) == (3, 3, 0)
    assert stats.total_chunks == len(embedder.embedded) == 3
    assert query(worker_db, "SELECT value FROM meta WHERE key = 'dim'") == [("8",)]


def test_vectors_round_trip_as_float32(worker_db: Path):
    build(worker_db)

    (blob,) = query(worker_db, "SELECT vector FROM chunks LIMIT 1")[0]
    vector = np.frombuffer(blob, dtype=np.float32)
    assert vector.shape == (8,)
    assert np.isclose(np.linalg.norm(vector), 1.0)


def test_rerun_without_changes_embeds_nothing(worker_db: Path):
    build(worker_db)

    stats, embedder = build(worker_db)

    assert not stats.full_rebuild
    assert (stats.embedded_repos, stats.skipped_repos) == (0, 3)
    assert embedder.embedded == []
    assert stats.total_chunks == 3


def test_changed_readme_reembeds_only_that_repo(worker_db: Path):
    build(worker_db)
    set_repo(worker_db, "2", stars=200, readme="# Repo 2\nNow it does something new.")

    stats, embedder = build(worker_db)

    assert stats.embedded_repos == 1
    assert all("owner/repo2" in text for text in embedder.embedded)
    assert query(worker_db, "SELECT COUNT(*) FROM chunks WHERE repo_id = '2'") == [(1,)]


def test_changed_description_or_topics_reembeds(worker_db: Path):
    build(worker_db)
    set_repo(worker_db, "1", stars=300, readme="# Repo 1\nIt does thing 1.", topics=["llm"])

    stats, _ = build(worker_db)

    assert stats.embedded_repos == 1, "Topics are in the chunk prefix, so the vectors changed"


def test_star_change_updates_without_reembedding(worker_db: Path):
    build(worker_db)
    set_repo(worker_db, "3", stars=999, readme="# Repo 3\nIt does thing 3.")

    stats, embedder = build(worker_db)

    assert embedder.embedded == []
    assert query(worker_db, "SELECT stars FROM repos WHERE id = '3'") == [(999,)]


def test_repo_removed_from_worker_is_removed_from_index(worker_db: Path):
    build(worker_db)
    db = sqlite3.connect(worker_db)
    db.execute("DELETE FROM repositories WHERE id = '3'")
    db.commit()
    db.close()

    stats, _ = build(worker_db)

    assert stats.removed_repos == 1
    assert query(worker_db, "SELECT COUNT(*) FROM chunks WHERE repo_id = '3'") == [(0,)]


def test_limit_builds_the_top_repos_by_stars(worker_db: Path):
    stats, _ = build(worker_db, limit=2)

    assert stats.repos == 2
    assert query(worker_db, "SELECT id FROM repos ORDER BY id") == [("1",), ("2",)]


def test_model_change_forces_full_rebuild(worker_db: Path):
    build(worker_db)
    other = FakeEmbedder()
    other.model_name = "another-model"

    stats, embedder = build(worker_db, other)

    assert stats.full_rebuild
    assert stats.embedded_repos == 3


def test_rebuild_flag_reembeds_everything(worker_db: Path):
    build(worker_db)

    stats, _ = build(worker_db, rebuild=True)

    assert stats.embedded_repos == 3


def test_worker_db_is_opened_read_only(worker_db: Path):
    before = worker_db.read_bytes()

    build(worker_db)

    assert worker_db.read_bytes() == before
