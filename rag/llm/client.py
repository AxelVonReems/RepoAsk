"""LLM interface, the Gemini implementation, and a fake for tests.

Like Embedder, the rest of the code depends only on the LLMClient protocol, so switching to
Azure OpenAI later means one new class, and tests never call a real API.
"""

import json
import logging
import re
import time
from collections.abc import Callable
from typing import Protocol

from google import genai
from google.genai import errors, types

from rag import config

log = logging.getLogger(__name__)


class LLMError(Exception):
    """The LLM gave no usable answer, even after retrying."""


class RateLimitedError(LLMError):
    """Per-minute limit hit; trying again after retry_after seconds should work."""

    def __init__(self, message: str, retry_after: float) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class QuotaExhaustedError(LLMError):
    """Daily quota used up: no retry helps until it resets."""


class LLMClient(Protocol):
    model_name: str

    def generate(self, system: str, prompt: str) -> str:
        """Returns the model's answer to prompt, following the system instruction."""
        ...


class GeminiClient:
    def __init__(
        self,
        api_key: str | None = config.GEMINI_API_KEY,
        model_name: str = config.GEMINI_MODEL,
        max_retries: int = config.LLM_MAX_RETRIES,
        max_retry_wait: float = config.LLM_MAX_RETRY_WAIT_SECONDS,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not api_key:
            raise ValueError("GEMINI_API_KEY is not set: add it to .env (see .env.example)")
        self.model_name = model_name
        self.max_retries = max_retries
        self.max_retry_wait = max_retry_wait
        self._sleep = sleep  # injectable, so tests do not actually wait
        # The SDK's own retries are off (its default): it cannot tell a per-minute limit,
        # worth retrying, from a daily one, which is not
        self._client = genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(timeout=int(config.LLM_TIMEOUT_SECONDS * 1000)),
        )
        self._config = types.GenerateContentConfig(
            # Temperature stays at the model default: Google advises against lowering it for
            # Gemini 3 models; grounding comes from the prompt instead
            max_output_tokens=config.LLM_MAX_OUTPUT_TOKENS,
        )

    def generate(self, system: str, prompt: str) -> str:
        request_config = self._config.model_copy(update={"system_instruction": system})
        for attempt in range(self.max_retries + 1):
            try:
                response = self._client.models.generate_content(
                    model=self.model_name, contents=prompt, config=request_config
                )
            except errors.APIError as error:
                delay = self._retry_delay(error, attempt)
                log.warning("Gemini %s, retrying in %.0fs", error.code, delay)
                self._sleep(delay)
                continue
            if not response.text:
                reason = response.candidates[0].finish_reason if response.candidates else None
                raise LLMError(f"Gemini returned no text (finish reason: {reason})")
            return response.text
        raise AssertionError("unreachable: the last attempt returns or raises")

    def _retry_delay(self, error: errors.APIError, attempt: int) -> float:
        """Seconds to wait before the next attempt, or raises when retrying is pointless."""
        details = json.dumps(error.details)
        last_attempt = attempt == self.max_retries
        if error.code == 429:
            # Gemini names the exhausted quota, e.g. GenerateRequestsPerDayPerProjectPerModel
            if "PerDay" in details:
                raise QuotaExhaustedError("Gemini daily quota exhausted") from error
            delay = _suggested_delay(details) or 2.0 * 2**attempt
            if last_attempt or delay > self.max_retry_wait:
                raise RateLimitedError("Gemini rate limit reached", retry_after=delay) from error
            return delay
        if error.code >= 500 and not last_attempt:
            return 2.0 * 2**attempt
        raise LLMError(f"Gemini request failed: {error.code} {error.status}") from error


def _suggested_delay(details: str) -> float | None:
    """The RetryInfo delay Gemini attaches to a 429, like "retryDelay": "23s"."""
    match = re.search(r'"retryDelay":\s*"(\d+(?:\.\d+)?)s"', details)
    return float(match.group(1)) if match else None


class FakeLLM:
    """Returns a canned answer and records every call. For tests and offline development."""

    model_name = "fake-llm"

    def __init__(self, answer: str = "Fake answer citing [1].") -> None:
        self.answer = answer
        self.calls: list[tuple[str, str]] = []

    def generate(self, system: str, prompt: str) -> str:
        self.calls.append((system, prompt))
        return self.answer
