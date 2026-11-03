from types import SimpleNamespace

import pytest
from google.genai import errors

from rag.llm.answer import NO_MATCHES, Answerer
from rag.llm.client import (
    FakeLLM,
    GeminiClient,
    LLMError,
    QuotaExhaustedError,
    RateLimitedError,
)
from rag.llm.prompt import SYSTEM_PROMPT, build_prompt
from rag.retrieval.search import Hit


def hit(name: str, heading: str = "Install", text: str = "Some README text.") -> Hit:
    return Hit(name, f"https://github.com/{name}", 1234, "A repo", heading, text, text, 0.8)


# --- prompt ---


def test_prompt_numbers_excerpts_and_ends_with_the_question():
    prompt = build_prompt("how to run LLMs?", [hit("a/one"), hit("b/two", heading="")])

    assert "[1] a/one (1,234 stars), section: Install\nSome README text." in prompt
    assert "[2] b/two (1,234 stars)\n" in prompt  # no heading, no "section:"
    assert prompt.endswith("Question: how to run LLMs?")


def test_system_prompt_asks_for_grounded_cited_answers():
    assert "only the" in SYSTEM_PROMPT
    assert "[1]" in SYSTEM_PROMPT
    assert "not instructions" in SYSTEM_PROMPT  # README text must not steer the model


# --- Gemini client, with the SDK call replaced: no network ---


def quota_error(quota_id: str, retry_delay: str | None = None) -> errors.ClientError:
    details = [{"violations": [{"quotaId": quota_id}]}]
    if retry_delay:
        details.append({"retryDelay": retry_delay})
    return errors.ClientError(
        429, {"error": {"code": 429, "status": "RESOURCE_EXHAUSTED", "details": details}}
    )


def gemini(*outcomes, **kwargs) -> tuple[GeminiClient, list[float]]:
    """A GeminiClient whose API calls return or raise outcomes in order; records sleeps."""
    sleeps: list[float] = []
    client = GeminiClient(api_key="test-key", sleep=sleeps.append, **kwargs)
    queue = list(outcomes)

    def generate_content(**_):
        outcome = queue.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return SimpleNamespace(text=outcome, candidates=[])

    client._client = SimpleNamespace(models=SimpleNamespace(generate_content=generate_content))
    return client, sleeps


def test_gemini_returns_the_text():
    client, sleeps = gemini("An answer [1].")

    assert client.generate("system", "prompt") == "An answer [1]."
    assert sleeps == []


def test_per_minute_limit_waits_the_suggested_delay_then_retries():
    client, sleeps = gemini(quota_error("GenerateRequestsPerMinute", "7s"), "Answer")

    assert client.generate("system", "prompt") == "Answer"
    assert sleeps == [7.0]


def test_daily_limit_fails_at_once():
    client, sleeps = gemini(quota_error("GenerateRequestsPerDayPerProjectPerModel-FreeTier"))

    with pytest.raises(QuotaExhaustedError):
        client.generate("system", "prompt")
    assert sleeps == []


def test_suggested_delay_longer_than_a_caller_should_wait_is_not_waited():
    client, sleeps = gemini(quota_error("GenerateRequestsPerMinute", "45s"), max_retry_wait=20)

    with pytest.raises(RateLimitedError) as raised:
        client.generate("system", "prompt")
    assert raised.value.retry_after == 45
    assert sleeps == []


def test_server_errors_are_retried_with_backoff_until_retries_run_out():
    server_error = errors.ServerError(503, {"error": {"code": 503, "status": "UNAVAILABLE"}})
    client, sleeps = gemini(server_error, server_error, server_error, max_retries=2)

    with pytest.raises(LLMError, match="503"):
        client.generate("system", "prompt")
    assert sleeps == [2.0, 4.0]


def test_client_errors_are_not_retried():
    bad_request = errors.ClientError(400, {"error": {"code": 400, "status": "INVALID_ARGUMENT"}})
    client, sleeps = gemini(bad_request)

    with pytest.raises(LLMError, match="400"):
        client.generate("system", "prompt")
    assert sleeps == []


def test_empty_response_is_an_error():
    client, _ = gemini("")

    with pytest.raises(LLMError, match="no text"):
        client.generate("system", "prompt")


def test_missing_api_key_is_explained():
    with pytest.raises(ValueError, match="GEMINI_API_KEY"):
        GeminiClient(api_key=None)


# --- Answerer: retrieval + prompt + LLM ---


class StubRetriever:
    def __init__(self, hits: list[Hit]) -> None:
        self.hits = hits

    def retrieve(self, question: str, k: int) -> list[Hit]:
        self.k = k
        return self.hits[:k]


def test_answer_sends_the_retrieved_excerpts_and_returns_them_as_sources():
    hits = [hit("ollama/ollama"), hit("nomic-ai/gpt4all")]
    llm = FakeLLM("Use ollama/ollama [1].")

    answer = Answerer(StubRetriever(hits), llm).ask("run LLMs locally?")

    assert answer.text == "Use ollama/ollama [1]."
    assert answer.sources == hits
    system, prompt = llm.calls[0]
    assert system == SYSTEM_PROMPT
    assert "[2] nomic-ai/gpt4all" in prompt


def test_answer_passes_k_to_retrieval():
    retriever = StubRetriever([hit("a/one"), hit("b/two"), hit("c/three")])

    answer = Answerer(retriever, FakeLLM()).ask("which one?", k=2)

    assert retriever.k == 2
    assert len(answer.sources) == 2


def test_no_retrieved_chunks_means_no_llm_call():
    llm = FakeLLM()

    answer = Answerer(StubRetriever([]), llm).ask("sourdough bread?")

    assert answer.text == NO_MATCHES
    assert answer.sources == []
    assert llm.calls == []
