import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import numpy as np
import pytest
from fastapi.testclient import TestClient

from rag.api.main import create_app, index_age_days, snippet
from rag.llm.answer import Answerer
from rag.llm.client import FakeLLM, LLMError, QuotaExhaustedError, RateLimitedError
from rag.retrieval.search import Index, Retriever


class StubEmbedder:
    model_name = "fake"
    dim = 2

    def embed_query(self, text: str) -> np.ndarray:
        return np.array([1, 0], dtype=np.float32)


class FailingLLM(FakeLLM):
    def __init__(self, error: Exception) -> None:
        super().__init__()
        self.error = error

    def generate(self, system: str, prompt: str) -> str:
        raise self.error


BODY = "Install it:\n\n    pip install one\n\nThen run it."


def make_answerer(llm: FakeLLM, built_at: datetime | None = None) -> Answerer:
    """Two repos in a 2-dim index; the stub query vector matches a/one best."""
    built_at = built_at or datetime.now(UTC)
    chunks = [
        ("1", "a/one", "https://github.com/a/one", 100, "One", "Install", BODY, "a/one\n\n" + BODY),
        ("2", "b/two", "https://github.com/b/two", 50, "Two", "", "Use two.", "b/two\n\nUse two."),
    ]
    meta = {"built_at": built_at.isoformat(), "settings": json.dumps({"model": "fake"})}
    # Both repos score above the default threshold: 1.0 and 0.8
    vectors = np.array([[1, 0], [0.8, 0.6]], dtype=np.float32)
    index = Index(vectors, chunks, meta)
    return Answerer(Retriever(index, StubEmbedder()), llm)


def client_for(answerer: Answerer) -> Iterator[TestClient]:
    # `with` runs the app's startup (lifespan), like uvicorn does
    with TestClient(create_app(answerer)) as client:
        yield client


@pytest.fixture
def client() -> Iterator[TestClient]:
    yield from client_for(make_answerer(FakeLLM("Use a/one [1].")))


def test_ask_returns_answer_and_numbered_sources(client: TestClient):
    response = client.post("/ask", json={"question": "which repo should I use?"})

    assert response.status_code == 200
    body = response.json()
    assert body["answer"] == "Use a/one [1]."
    assert body["model"] == "fake-llm"
    assert [(s["n"], s["full_name"]) for s in body["sources"]] == [(1, "a/one"), (2, "b/two")]
    assert body["sources"][0]["score"] == pytest.approx(1.0)


def test_sources_carry_a_one_line_snippet(client: TestClient):
    sources = client.post("/ask", json={"question": "which repo should I use?"}).json()["sources"]

    assert sources[0]["snippet"] == "Install it: pip install one Then run it."


def test_top_k_limits_the_sources(client: TestClient):
    response = client.post("/ask", json={"question": "which repo should I use?", "top_k": 1})

    assert [s["full_name"] for s in response.json()["sources"]] == ["a/one"]


@pytest.mark.parametrize("top_k", [0, 11])
def test_top_k_outside_1_to_10_is_rejected(client: TestClient, top_k: int):
    response = client.post("/ask", json={"question": "which repo?", "top_k": top_k})

    assert response.status_code == 422


@pytest.mark.parametrize("question", ["", "hi", "x" * 501])
def test_ask_rejects_too_short_or_too_long_questions(client: TestClient, question: str):
    assert client.post("/ask", json={"question": question}).status_code == 422


def test_ask_requires_a_question_field(client: TestClient):
    assert client.post("/ask", json={}).status_code == 422


def test_health_reports_the_index(client: TestClient):
    body = client.get("/health").json()

    assert body["status"] == "ok"
    assert (body["repos"], body["chunks"]) == (2, 2)
    assert body["embed_model"] == "fake"
    assert body["llm_model"] == "fake-llm"
    assert body["index_stale"] is False


def test_health_flags_an_old_index_as_stale():
    old = datetime.now(UTC) - timedelta(days=30)
    for client in client_for(make_answerer(FakeLLM(), built_at=old)):
        body = client.get("/health").json()

    assert body["index_stale"] is True
    assert body["index_age_days"] == pytest.approx(30, abs=0.1)


@pytest.mark.parametrize(
    ("error", "status", "retry_after"),
    [
        (RateLimitedError("limited", retry_after=7.2), 503, "8"),
        (QuotaExhaustedError("daily quota"), 503, None),
        (LLMError("broken"), 502, None),
    ],
)
def test_llm_failures_map_to_clear_statuses(error: Exception, status: int, retry_after):
    for client in client_for(make_answerer(FailingLLM(error))):
        response = client.post("/ask", json={"question": "which repo should I use?"})

    assert response.status_code == status
    assert response.headers.get("retry-after") == retry_after
    assert "LLM" in response.json()["detail"]


def test_index_age_days():
    now = datetime(2026, 11, 3, 12, tzinfo=UTC)

    assert index_age_days("2026-11-01T12:00:00+00:00", now) == 2.0
    assert index_age_days(None, now) is None


def test_snippet_cuts_long_text_at_a_word_boundary():
    text = "word " * 100

    cut = snippet(text, max_chars=20)

    assert cut == "word word word word…"
    assert len(cut) <= 20
    assert snippet("short   text\n") == "short text"
    assert snippet("word " * 100, max_chars=22) == "word word word word…"  # cut mid-word
