"""Request and response bodies. Pydantic validates input and FastAPI documents both at /docs."""

from pydantic import BaseModel, Field

from rag import config


class AskRequest(BaseModel):
    # Bounded: every question costs an embedding and a Gemini request
    question: str = Field(min_length=3, max_length=config.QUESTION_MAX_CHARS)
    top_k: int = Field(default=config.SEARCH_TOP_K, ge=1, le=10, description="Sources to use")


class Source(BaseModel):
    n: int = Field(description="The number the answer cites as [n]")
    full_name: str
    url: str
    stars: int
    heading: str
    snippet: str = Field(description="Start of the README section the source comes from")
    score: float = Field(description="Cosine similarity to the question")


class AskResponse(BaseModel):
    answer: str
    sources: list[Source]
    model: str


class HealthResponse(BaseModel):
    status: str
    index_built_at: str | None
    index_age_days: float | None
    index_stale: bool
    repos: int
    chunks: int
    embed_model: str | None
    llm_model: str
