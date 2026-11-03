"""FastAPI app.

    uv run uvicorn rag.api.main:app [--reload]

Then open http://127.0.0.1:8000/docs to try it. The index and the embedding model load once at
startup (a few seconds), so each request only pays for one query embedding and one LLM call.
"""

import math
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from rag import config
from rag.api.models import AskRequest, AskResponse, HealthResponse, Source
from rag.indexing.embed import FastEmbedEmbedder
from rag.llm.answer import Answerer
from rag.llm.client import GeminiClient, LLMError, QuotaExhaustedError, RateLimitedError
from rag.retrieval.search import Index, Retriever


def create_app(answerer: Answerer | None = None) -> FastAPI:
    """Tests pass a ready Answerer (fake LLM, tiny index); otherwise the real one loads."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # Fails at startup, not on the first request, when the index or the key is missing
        app.state.answerer = answerer or Answerer(
            Retriever(Index.load(config.INDEX_DB_PATH), FastEmbedEmbedder()), GeminiClient()
        )
        yield

    app = FastAPI(
        title="RepoAsk",
        description="Ask questions about the READMEs of the most-starred GitHub repositories.",
        lifespan=lifespan,
    )

    # A plain `def` (not `async def`): retrieval and the Gemini call block, so FastAPI runs
    # this in its thread pool instead of stalling every other request on the event loop
    @app.post("/ask")
    def ask(body: AskRequest, request: Request) -> AskResponse:
        answerer: Answerer = request.app.state.answerer
        answer = answerer.ask(body.question, k=body.top_k)
        return AskResponse(
            answer=answer.text,
            sources=[
                Source(
                    n=n,
                    full_name=hit.full_name,
                    url=hit.url,
                    stars=hit.stars,
                    heading=hit.heading,
                    snippet=snippet(hit.body),
                    score=round(hit.score, 4),
                )
                for n, hit in enumerate(answer.sources, 1)
            ],
            model=answerer.llm.model_name,
        )

    @app.get("/health")
    def health(request: Request) -> HealthResponse:
        answerer: Answerer = request.app.state.answerer
        index = answerer.retriever.index
        age = index_age_days(index.built_at, datetime.now(UTC))
        return HealthResponse(
            status="ok",
            index_built_at=index.built_at,
            index_age_days=age,
            index_stale=age is None or age > config.INDEX_STALE_DAYS,
            repos=index.repo_count,
            chunks=index.chunk_count,
            embed_model=index.model,
            llm_model=answerer.llm.model_name,
        )

    # LLM failures are upstream problems, not bugs here: answer with a clear status instead
    # of a bare 500. 503 + Retry-After tells clients when trying again makes sense.
    @app.exception_handler(RateLimitedError)
    def rate_limited(request: Request, error: RateLimitedError) -> JSONResponse:
        return JSONResponse(
            {"detail": "The LLM is rate limited, try again shortly."},
            status_code=503,
            headers={"Retry-After": str(math.ceil(error.retry_after))},
        )

    @app.exception_handler(QuotaExhaustedError)
    def quota_exhausted(request: Request, error: QuotaExhaustedError) -> JSONResponse:
        return JSONResponse(
            {"detail": "The daily LLM quota is used up, try again tomorrow."}, status_code=503
        )

    @app.exception_handler(LLMError)
    def llm_failed(request: Request, error: LLMError) -> JSONResponse:
        return JSONResponse({"detail": "The LLM request failed."}, status_code=502)

    return app


def snippet(body: str, max_chars: int = 200) -> str:
    """One line of at most max_chars, cut at a word boundary."""
    text = " ".join(body.split())
    if len(text) <= max_chars:
        return text
    cut = text[: max_chars - 1]  # leaves room for the ellipsis
    # Drop the last word only if the cut went through its middle
    if text[max_chars - 1] != " " and " " in cut:
        cut = cut.rsplit(" ", 1)[0]
    return cut.rstrip() + "…"


def index_age_days(built_at: str | None, now: datetime) -> float | None:
    if not built_at:
        return None
    return round((now - datetime.fromisoformat(built_at)).total_seconds() / 86400, 1)


app = create_app()
