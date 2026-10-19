"""Model provider factory and public exports."""

from __future__ import annotations

from typing import Optional

from verifyloop.config import ProviderConfig
from verifyloop.model_providers.base import (
    Completion,
    ModelProvider,
    ProviderError,
    ProviderResponseError,
    ProviderTimeout,
    ProviderUnavailable,
)
from verifyloop.model_providers.compatible_api import (
    OllamaProvider,
    OpenAICompatibleProvider,
)
from verifyloop.model_providers.diagnostics import DiagnosticReport, diagnose_provider
from verifyloop.model_providers.mock import MockProvider, MockResponse

__all__ = [
    "Completion",
    "DiagnosticReport",
    "MockProvider",
    "MockResponse",
    "ModelProvider",
    "OllamaProvider",
    "OpenAICompatibleProvider",
    "ProviderError",
    "ProviderResponseError",
    "ProviderTimeout",
    "ProviderUnavailable",
    "build_provider",
    "diagnose_provider",
]


def build_provider(
    config: ProviderConfig,
    *,
    mock_responses: Optional[list[MockResponse]] = None,
) -> ModelProvider:
    """Instantiate the provider described by ``config``.

    Raises :class:`ProviderError` for an unusable configuration rather than
    silently falling back to the mock, which would corrupt experiment provenance.
    """
    if config.provider == "mock":
        return MockProvider(
            responses=mock_responses or [],
            model=config.model,
        )
    if config.provider == "ollama":
        return OllamaProvider(
            model=config.model,
            base_url=config.base_url,
            timeout_seconds=config.request_timeout_seconds,
            api_key=config.api_key,
            default_max_output_tokens=config.max_output_tokens,
            default_temperature=config.temperature,
            seed=config.seed,
        )
    if config.provider == "openai_compatible":
        if not config.api_key:
            raise ProviderError(
                f"provider {config.provider!r} requires an API key in "
                f"${config.api_key_env}, which is not set"
            )
        return OpenAICompatibleProvider(
            model=config.model,
            base_url=config.base_url,
            timeout_seconds=config.request_timeout_seconds,
            api_key=config.api_key,
            default_max_output_tokens=config.max_output_tokens,
            default_temperature=config.temperature,
            seed=config.seed,
        )
    raise ProviderError(f"unknown provider: {config.provider!r}")
