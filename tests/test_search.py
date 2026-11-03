import json
import sqlite3
from pathlib import Path

import numpy as np
import pytest

from rag.indexing.build_index import SCHEMA
from rag.retrieval.search import Index, Retriever


def unit(*values: float) -> np.ndarray:
    v = np.array(values, dtype=np.float32)
    return v / np.linalg.norm(v)


# (repo id, chunk vector). Query (1, 0, 0) ranks them: a1 > a2 > a3 > b1 > c1
CHUNKS = [
    ("a", unit(1, 0.1, 0)),
    ("a", unit(1, 0.2, 0)),
    ("a", unit(1, 0.3, 0)),
    ("b", unit(1, 1, 0)),
    ("c", unit(0, 1, 1)),
]
QUERY = unit(1, 0, 0)


@pytest.fixture
def index_db(tmp_path: Path) -> Path:
    """A 3-dim index.db with the schema build_index writes, and hand-picked vectors."""
    path = tmp_path / "index.db"
    db = sqlite3.connect(path)
    db.executescript(SCHEMA)
    for repo_id, stars in (("a", 300), ("b", 200), ("c", 100)):
        db.execute(
            "INSERT INTO repos VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                repo_id,
                f"owner/{repo_id}",
                f"https://github.com/owner/{repo_id}",
                stars,
                f"Repo {repo_id}",
                "[]",
                "sha",
            ),
        )
    for position, (repo_id, vector) in enumerate(CHUNKS):
        db.execute(
            "INSERT INTO chunks (repo_id, position, heading, body, text, vector) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                repo_id,
                position,
                f"H{position}",
                "body",
                f"owner/{repo_id}\n\nchunk {position}",
                vector.tobytes(),
            ),
        )
    meta = {
        "dim": "3",
        "built_at": "2026-11-03T08:00:00+00:00",
        "settings": json.dumps({"model": "fake"}),
    }
    db.executemany("INSERT INTO meta VALUES (?, ?)", meta.items())
    db.commit()
    db.close()
    return path


class StubEmbedder:
    model_name = "fake"
    dim = 3

    def embed_query(self, text: str) -> np.ndarray:
        return QUERY


def test_load_reads_vectors_and_meta(index_db: Path):
    index = Index.load(index_db)

    assert index.vectors.shape == (5, 3)
    assert (index.chunk_count, index.repo_count) == (5, 3)
    assert index.model == "fake"
    assert index.built_at == "2026-11-03T08:00:00+00:00"


def test_results_are_ranked_by_cosine_similarity(index_db: Path):
    hits = Index.load(index_db).search(QUERY, k=5, max_per_repo=5)

    assert [h.text.split()[-1] for h in hits] == ["0", "1", "2", "3", "4"]
    assert hits[0].score == pytest.approx(float(CHUNKS[0][1] @ QUERY))
    assert all(a.score >= b.score for a, b in zip(hits, hits[1:], strict=False))


def test_max_per_repo_makes_room_for_other_repos(index_db: Path):
    hits = Index.load(index_db).search(QUERY, k=3, max_per_repo=2)

    assert [h.full_name for h in hits] == ["owner/a", "owner/a", "owner/b"]


def test_min_score_drops_weak_matches(index_db: Path):
    hits = Index.load(index_db).search(QUERY, k=5, max_per_repo=5, min_score=0.5)

    assert "owner/c" not in {h.full_name for h in hits}  # orthogonal to the query: score 0


def test_hit_carries_repo_details(index_db: Path):
    hit = Index.load(index_db).search(QUERY, k=1)[0]

    assert (hit.full_name, hit.stars, hit.description) == ("owner/a", 300, "Repo a")
    assert hit.url == "https://github.com/owner/a"
    assert hit.heading == "H0"


def test_query_with_wrong_dimension_is_rejected(index_db: Path):
    with pytest.raises(ValueError, match="shape"):
        Index.load(index_db).search(np.ones(4, dtype=np.float32))


def test_missing_index_explains_how_to_build_it(tmp_path: Path):
    with pytest.raises(FileNotFoundError, match="build_index"):
        Index.load(tmp_path / "missing.db")
    assert not (tmp_path / "missing.db").exists(), "loading must not create an empty database"


def test_retriever_embeds_the_question_and_searches(index_db: Path):
    hits = Retriever(Index.load(index_db), StubEmbedder()).retrieve("anything", k=1)

    assert hits[0].full_name == "owner/a"


def test_retriever_refuses_an_index_from_another_model(index_db: Path):
    embedder = StubEmbedder()
    embedder.model_name = "other-model"

    with pytest.raises(ValueError, match="rebuild"):
        Retriever(Index.load(index_db), embedder)
