"""Semantic search over index.db.

    uv run python -m rag.retrieval.search "how do I run LLMs locally" [-k 5] [--max-per-repo 2]

The whole index is loaded into one (chunks, dim) float32 matrix. Vectors are L2-normalized,
so a single matrix-vector product gives the cosine similarity of every chunk; at ~12k chunks
that takes about a millisecond, and a vector database would only add moving parts.
"""

import argparse
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from rag import config
from rag.indexing.embed import Embedder, FastEmbedEmbedder


@dataclass(frozen=True)
class Hit:
    full_name: str
    url: str
    stars: int
    description: str | None
    heading: str
    text: str  # what was embedded: repo prefix + chunk body
    score: float  # cosine similarity, higher is more relevant


class Index:
    """index.db in memory: the vector matrix plus, row by row, what each vector belongs to."""

    def __init__(self, vectors: np.ndarray, chunks: list[tuple], meta: dict[str, str]) -> None:
        self.vectors = vectors
        self._chunks = chunks  # (repo_id, full_name, url, stars, description, heading, text)
        settings = json.loads(meta.get("settings", "{}"))
        self.model: str | None = settings.get("model")
        self.built_at: str | None = meta.get("built_at")
        self.repo_count = len({c[0] for c in chunks})

    @property
    def chunk_count(self) -> int:
        return len(self._chunks)

    @property
    def dim(self) -> int:
        return self.vectors.shape[1]

    @classmethod
    def load(cls, path: Path) -> "Index":
        if not path.exists():
            raise FileNotFoundError(
                f"{path} not found: run `uv run python -m rag.indexing.build_index` first"
            )
        # Read-only: the API must never modify the index, and a typo must not create an empty one
        db = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
        meta = dict(db.execute("SELECT key, value FROM meta"))
        rows = db.execute(
            """
            SELECT r.id, r.full_name, r.url, r.stars, r.description, c.heading, c.text, c.vector
            FROM chunks c JOIN repos r ON r.id = c.repo_id
            ORDER BY c.id
            """
        ).fetchall()
        db.close()

        dim = int(meta.get("dim", 0))
        if not rows or not dim:
            raise ValueError(f"{path} is empty: rebuild it with build_index")
        vectors = np.frombuffer(b"".join(row[-1] for row in rows), dtype=np.float32)
        return cls(vectors.reshape(-1, dim), [row[:-1] for row in rows], meta)

    def search(
        self,
        query_vector: np.ndarray,
        k: int = config.SEARCH_TOP_K,
        max_per_repo: int = config.SEARCH_MAX_PER_REPO,
        min_score: float = config.SEARCH_MIN_SCORE,
    ) -> list[Hit]:
        if query_vector.shape != (self.dim,):
            raise ValueError(f"query has shape {query_vector.shape}, index expects ({self.dim},)")

        scores = self.vectors @ query_vector
        hits: list[Hit] = []
        per_repo: dict[str, int] = {}
        # Walk down the full ranking (sorting 12k floats is cheap) and skip repos at their cap
        for row in np.argsort(-scores):
            score = float(scores[row])
            if score < min_score or len(hits) == k:
                break
            repo_id, full_name, url, stars, description, heading, text = self._chunks[row]
            if per_repo.get(repo_id, 0) >= max_per_repo:
                continue
            per_repo[repo_id] = per_repo.get(repo_id, 0) + 1
            hits.append(Hit(full_name, url, stars, description, heading, text, score))
        return hits


class Retriever:
    """Index + the embedder that turns questions into query vectors for it."""

    def __init__(self, index: Index, embedder: Embedder) -> None:
        # Vectors from different models live in different spaces: comparing them is meaningless
        if index.model != embedder.model_name:
            raise ValueError(
                f"index was built with {index.model!r}, embedder is {embedder.model_name!r}: "
                "rebuild the index"
            )
        self.index = index
        self.embedder = embedder

    def retrieve(self, question: str, **search_options) -> list[Hit]:
        return self.index.search(self.embedder.embed_query(question), **search_options)


def main() -> None:
    parser = argparse.ArgumentParser(description="Search index.db from the command line")
    parser.add_argument("question")
    parser.add_argument("-k", type=int, default=config.SEARCH_TOP_K)
    parser.add_argument("--max-per-repo", type=int, default=config.SEARCH_MAX_PER_REPO)
    parser.add_argument("--min-score", type=float, default=config.SEARCH_MIN_SCORE)
    args = parser.parse_args()

    retriever = Retriever(Index.load(config.INDEX_DB_PATH), FastEmbedEmbedder())
    hits = retriever.retrieve(
        args.question, k=args.k, max_per_repo=args.max_per_repo, min_score=args.min_score
    )
    for rank, hit in enumerate(hits, 1):
        body = hit.text.split("\n\n", 1)[-1].replace("\n", " ")
        print(f"{rank}. {hit.score:.3f}  {hit.full_name} ({hit.stars:,}★)  § {hit.heading or '-'}")
        print(f"   {body[:160]}")


if __name__ == "__main__":
    main()
