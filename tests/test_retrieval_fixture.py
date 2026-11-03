"""End-to-end retrieval with the real embedding model on a 5-README fixture index.

The CI counterpart of eval/run_eval.py: the real index is not available in CI, so this checks
that clean -> chunk -> embed -> search ranks the obvious repository first for plain questions.
"""

import hashlib
import json
import sqlite3

import pytest

from rag.indexing.build_index import build_index
from rag.indexing.embed import FastEmbedEmbedder
from rag.retrieval.search import Index, Retriever

READMES = {
    "ollama/ollama": (
        "Run large language models locally.",
        "# Ollama\n\nGet up and running with large language models on your own machine. "
        "Download a model and chat with it offline, no GPU or cloud account required.",
    ),
    "tailwindlabs/tailwindcss": (
        "A utility-first CSS framework.",
        "# Tailwind CSS\n\nStyle your pages with utility classes like `flex` and `pt-4` "
        "directly in your HTML, without writing custom CSS.",
    ),
    "junegunn/fzf": (
        "A command-line fuzzy finder.",
        "# fzf\n\nAn interactive filter for the terminal: pipe any list into it and "
        "pick items by typing a few letters of their name.",
    ),
    "yt-dlp/yt-dlp": (
        "A command-line audio/video downloader.",
        "# yt-dlp\n\nDownload videos and audio from YouTube and thousands of other sites "
        "from the command line.",
    ),
    "excalidraw/excalidraw": (
        "Virtual whiteboard for hand-drawn diagrams.",
        "# Excalidraw\n\nA collaborative whiteboard for sketching diagrams that look "
        "hand-drawn. Export to PNG or SVG.",
    ),
}


@pytest.fixture(scope="module")
def retriever(tmp_path_factory: pytest.TempPathFactory) -> Retriever:
    tmp = tmp_path_factory.mktemp("fixture")
    worker_db = tmp / "worker.db"
    db = sqlite3.connect(worker_db)
    db.executescript(
        """
        CREATE TABLE repositories (id TEXT PRIMARY KEY, fullName TEXT, url TEXT, metric INTEGER,
                                   description TEXT, topics TEXT);
        CREATE TABLE readmes (repoId TEXT PRIMARY KEY, content TEXT, contentSha TEXT);
        """
    )
    for n, (name, (description, readme)) in enumerate(READMES.items()):
        url = f"https://github.com/{name}"
        db.execute(
            "INSERT INTO repositories VALUES (?, ?, ?, ?, ?, ?)",
            (str(n), name, url, 1000 - n, description, json.dumps([])),
        )
        sha = hashlib.sha256(readme.encode()).hexdigest()
        db.execute("INSERT INTO readmes VALUES (?, ?, ?)", (str(n), readme, sha))
    db.commit()
    db.close()

    embedder = FastEmbedEmbedder()
    build_index(worker_db, tmp / "index.db", embedder, log=lambda _: None)
    return Retriever(Index.load(tmp / "index.db"), embedder)


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("How can I run an LLM on my laptop?", "ollama/ollama"),
        ("Which CSS framework uses utility classes?", "tailwindlabs/tailwindcss"),
        ("Interactive fuzzy search in the terminal", "junegunn/fzf"),
        ("Download a YouTube video from the command line", "yt-dlp/yt-dlp"),
        ("Whiteboard app for sketching diagrams", "excalidraw/excalidraw"),
    ],
)
def test_known_question_ranks_the_right_repo_first(
    retriever: Retriever, question: str, expected: str
):
    assert retriever.retrieve(question)[0].full_name == expected


def test_top_k_is_respected(retriever: Retriever):
    assert len(retriever.retrieve("command line tool", k=2)) == 2
