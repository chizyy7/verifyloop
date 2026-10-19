"""HTTP-backed providers: Ollama (native API) and OpenAI-compatible chat completions."""

from __future__ import annotations

import time
from typing import Any, Optional

import httpx

from verifyloop.model_providers.base import (
    Completion,
    ModelProvider,
    ProviderError,
    ProviderResponseError,
    ProviderTimeout,
    ProviderUnavailable,
)


class _HttpProvider(ModelProvider):
    def __init__(
        self,
        *,
        model: str,
        base_url: str,
        timeout_seconds: float = 120.0,
        api_key: Optional[str] = None,
        default_max_output_tokens: int = 900,
        default_temperature: float = 0.0,
        seed: Optional[int] = None,
        transport: Optional[httpx.BaseTransport] = None,
    ) -> None:
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self._api_key = api_key
        self.default_max_output_tokens = default_max_output_tokens
        self.default_temperature = default_temperature
        self.seed = seed
        self._transport = transport

    def _client(self) -> httpx.Client:
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return httpx.Client(
            timeout=httpx.Timeout(self.timeout_seconds),
            headers=headers,
            transport=self._transport,
            follow_redirects=False,
        )

    def _post(self, url: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            with self._client() as client:
                response = client.post(url, json=payload)
        except httpx.TimeoutException as exc:
            raise ProviderTimeout(
                f"request to {url} timed out after {self.timeout_seconds}s", retryable=True
            ) from exc
        except httpx.HTTPError as exc:
            raise ProviderUnavailable(f"cannot reach {url}: {exc}", retryable=True) from exc

        if response.status_code == 429:
            raise ProviderUnavailable(
                "provider rate limit (HTTP 429)", retryable=True
            )
        if response.status_code >= 500:
            # Keep the server's own explanation: Ollama reports model-load and
            # memory failures in the body, which is far more useful than a code.
            raise ProviderUnavailable(
                f"provider server error (HTTP {response.status_code})"
                f"{_body_excerpt(response)}",
                retryable=True,
            )
        if response.status_code >= 400:
            body = response.text[:400]
            raise ProviderResponseError(
                f"provider rejected request (HTTP {response.status_code}): {body}"
            )
        try:
            data = response.json()
        except ValueError as exc:
            raise ProviderResponseError("provider returned non-JSON body") from exc
        if not isinstance(data, dict):
            raise ProviderResponseError("provider returned a non-object JSON body")
        return data

    def _get_json(self, url: str) -> dict[str, Any]:
        """GET and decode a JSON object, mapping failures to provider errors."""
        try:
            with self._client() as client:
                response = client.get(url)
        except httpx.TimeoutException as exc:
            raise ProviderTimeout(
                f"request to {url} timed out after {self.timeout_seconds}s", retryable=True
            ) from exc
        except httpx.HTTPError as exc:
            raise ProviderUnavailable(f"cannot reach {url}: {exc}", retryable=True) from exc

        if response.status_code >= 400:
            raise ProviderUnavailable(
                f"cannot list models (HTTP {response.status_code})"
                f"{_body_excerpt(response)}",
                retryable=True,
            )
        try:
            data = response.json()
        except ValueError as exc:
            raise ProviderResponseError("provider returned non-JSON body") from exc
        if not isinstance(data, dict):
            raise ProviderResponseError("provider returned a non-object JSON body")
        return data

    def health_check(self) -> tuple[bool, str]:
        try:
            with self._client() as client:
                response = client.get(f"{self.base_url}/api/tags" if self.name == "ollama"
                                      else f"{self.base_url}/models")
            if response.status_code < 400:
                return True, f"{self.name} reachable at {self.base_url}"
            return False, f"{self.name} returned HTTP {response.status_code}"
        except httpx.HTTPError as exc:
            return False, f"{self.name} unreachable: {exc}"


class OllamaProvider(_HttpProvider):
    """Native Ollama ``/api/chat`` provider.

    Uses the native API rather than the OpenAI shim so that ``prompt_eval_count`` and
    ``eval_count`` are available for accurate token accounting.
    """

    name = "ollama"

    def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        max_output_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
    ) -> Completion:
        options: dict[str, Any] = {
            "temperature": (
                self.default_temperature if temperature is None else temperature
            ),
            "num_predict": (
                self.default_max_output_tokens
                if max_output_tokens is None
                else max_output_tokens
            ),
        }
        if self.seed is not None:
            options["seed"] = self.seed

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "stream": False,
            "options": options,
        }

        started = time.monotonic()
        data = self._post(f"{self.base_url}/api/chat", payload)
        duration = time.monotonic() - started

        message = data.get("message")
        if not isinstance(message, dict) or not isinstance(message.get("content"), str):
            raise ProviderResponseError("ollama response missing message.content")
        text = message["content"]
        if not text.strip():
            raise ProviderResponseError("ollama returned an empty completion")

        return Completion(
            text=text,
            model=str(data.get("model", self.model)),
            provider=self.name,
            prompt_tokens=_as_int(data.get("prompt_eval_count")),
            completion_tokens=_as_int(data.get("eval_count")),
            duration_seconds=duration,
            raw={
                "done_reason": data.get("done_reason"),
                "total_duration_ns": data.get("total_duration"),
            },
        )

    def list_models(self) -> list[str]:
        """Return the model names Ollama reports from ``GET /api/tags``."""
        data = self._get_json(f"{self.base_url}/api/tags")
        entries = data.get("models")
        if not isinstance(entries, list):
            raise ProviderResponseError("ollama /api/tags response missing models list")
        names: list[str] = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            name = entry.get("model") or entry.get("name")
            if isinstance(name, str) and name:
                names.append(name)
        return names

    def check_model_available(self) -> tuple[Optional[bool], str]:
        try:
            names = self.list_models()
        except ProviderError as exc:
            return None, str(exc)
        if _model_matches(self.model, names):
            return True, f"{self.model} is installed ({len(names)} model(s) available)"
        shown = ", ".join(sorted(names)) if names else "(none)"
        return False, f"{self.model} is not installed; available models: {shown}"

    def describe(self) -> dict[str, Any]:
        return {
            "provider": self.name,
            "model": self.model,
            "base_url": self.base_url,
            "api_key_present": bool(self._api_key),
            "timeout_seconds": self.timeout_seconds,
            "temperature": self.default_temperature,
            "seed": self.seed,
        }


class OpenAICompatibleProvider(_HttpProvider):
    """Any server implementing ``POST /v1/chat/completions``."""

    name = "openai_compatible"

    def _endpoint(self) -> str:
        base = self.base_url
        if base.endswith("/v1"):
            return f"{base}/chat/completions"
        return f"{base}/v1/chat/completions"

    def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        max_output_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
    ) -> Completion:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "max_tokens": (
                self.default_max_output_tokens
                if max_output_tokens is None
                else max_output_tokens
            ),
            "temperature": (
                self.default_temperature if temperature is None else temperature
            ),
            "stream": False,
        }
        if self.seed is not None:
            payload["seed"] = self.seed

        started = time.monotonic()
        data = self._post(self._endpoint(), payload)
        duration = time.monotonic() - started

        choices = data.get("choices")
        if not isinstance(choices, list) or not choices:
            raise ProviderResponseError("provider response has no choices")
        first = choices[0]
        message = first.get("message") if isinstance(first, dict) else None
        if not isinstance(message, dict) or not isinstance(message.get("content"), str):
            raise ProviderResponseError("provider response missing message.content")
        text = message["content"]
        if not text.strip():
            raise ProviderResponseError("provider returned an empty completion")

        usage = data.get("usage") or {}
        if not isinstance(usage, dict):
            usage = {}

        return Completion(
            text=text,
            model=str(data.get("model", self.model)),
            provider=self.name,
            prompt_tokens=_as_int(usage.get("prompt_tokens")),
            completion_tokens=_as_int(usage.get("completion_tokens")),
            duration_seconds=duration,
            raw={"finish_reason": first.get("finish_reason")},
        )

    def describe(self) -> dict[str, Any]:
        return {
            "provider": self.name,
            "model": self.model,
            "base_url": self.base_url,
            "api_key_present": bool(self._api_key),
            "timeout_seconds": self.timeout_seconds,
            "temperature": self.default_temperature,
            "seed": self.seed,
        }


def _as_int(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return None


def _body_excerpt(response: httpx.Response, limit: int = 300) -> str:
    """Collapse an error body into a short, single-line suffix for messages."""
    try:
        text = response.text
    except Exception:  # noqa: BLE001 - body decoding is best-effort
        return ""
    text = " ".join(text.split())
    if not text:
        return ""
    return f": {text[:limit]}"


def _model_matches(requested: str, available: list[str]) -> bool:
    """Match an Ollama model id, tolerating the implicit ``:latest`` tag."""
    if requested in available:
        return True
    if ":" not in requested:
        return f"{requested}:latest" in available
    return False
