"""Deterministic scripted provider for tests and offline demos.

The mock is intentionally *not* an LLM. It plays back a queue of responses and
records every prompt it receives, so the controller can be tested end-to-end without
network access or spend. Mock results are never evidence about real-model behaviour.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional, Sequence

from verifyloop.model_providers.base import (
    Completion,
    ModelProvider,
    ProviderError,
    ProviderResponseError,
    ProviderTimeout,
)


@dataclass
class MockResponse:
    text: str = ""
    error: Optional[type[ProviderError]] = None
    error_message: str = ""
    delay_seconds: float = 0.0
    prompt_tokens: Optional[int] = 100
    completion_tokens: Optional[int] = 50


class MockProvider(ModelProvider):
    """Queue-driven provider with deterministic token accounting."""

    name = "mock"

    def __init__(
        self,
        responses: Sequence[MockResponse] | None = None,
        *,
        model: str = "mock-scripted",
        repeat_last: bool = False,
        default_response: Optional[MockResponse] = None,
        responder: Optional[Callable[[str, str], MockResponse]] = None,
    ) -> None:
        self.model = model
        self._responses: list[MockResponse] = list(responses or [])
        self._repeat_last = repeat_last
        self._default = default_response
        self._responder = responder
        self.calls: list[dict[str, str]] = []

    @property
    def remaining(self) -> int:
        return len(self._responses)

    def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        max_output_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
    ) -> Completion:
        self.calls.append({"system": system_prompt, "user": user_prompt})
        started = time.monotonic()

        if self._responder is not None:
            response = self._responder(system_prompt, user_prompt)
        elif self._responses:
            response = self._responses.pop(0)
        elif self._repeat_last and self._responses is not None:
            response = self._default or MockResponse(text="")
        elif self._default is not None:
            response = self._default
        else:
            raise ProviderResponseError(
                f"mock provider has no response queued (call {len(self.calls)})"
            )

        if response.delay_seconds:
            time.sleep(response.delay_seconds)
        if response.error is not None:
            raise response.error(response.error_message or "mock error")

        duration = time.monotonic() - started
        return Completion(
            text=response.text,
            model=self.model,
            provider=self.name,
            prompt_tokens=response.prompt_tokens,
            completion_tokens=response.completion_tokens,
            duration_seconds=duration,
            raw={"mock": True},
        )

    def describe(self) -> dict[str, Any]:
        return {
            "provider": self.name,
            "model": self.model,
            "queued_responses": len(self._responses),
            "calls_so_far": len(self.calls),
        }

    def health_check(self) -> tuple[bool, str]:
        return True, "mock provider is always available"

    def push(self, *responses: MockResponse) -> None:
        self._responses.extend(responses)


def scripted_responses(patch_text: str, attempts: int = 1) -> list[MockResponse]:
    """Convenience: repeat the same patch text for N attempts."""
    return [MockResponse(text=patch_text) for _ in range(attempts)]


def timeout_response(message: str = "simulated provider timeout") -> MockResponse:
    return MockResponse(error=ProviderTimeout, error_message=message)


def error_response(message: str = "simulated provider error") -> MockResponse:
    return MockResponse(error=ProviderResponseError, error_message=message)
