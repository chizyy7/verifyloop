"""Provider-independent model interface.

Every provider returns a :class:`Completion` with whatever usage metadata it can
actually supply. ``prompt_tokens``/``completion_tokens`` are ``None`` when the backend
does not report them; the controller never invents numbers to fill the gap.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Any, Optional


class ProviderError(RuntimeError):
    """Base class for provider failures."""

    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable


class ProviderTimeout(ProviderError):
    """The provider did not respond within the configured timeout."""


class ProviderUnavailable(ProviderError):
    """The provider could not be reached at all."""


class ProviderResponseError(ProviderError):
    """The provider responded, but with an unusable payload."""


@dataclass
class Completion:
    text: str
    model: str
    provider: str
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    duration_seconds: float = 0.0
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def total_tokens(self) -> Optional[int]:
        if self.prompt_tokens is None and self.completion_tokens is None:
            return None
        return (self.prompt_tokens or 0) + (self.completion_tokens or 0)


class ModelProvider(abc.ABC):
    """Abstract chat-completion provider."""

    name: str = "base"

    @abc.abstractmethod
    def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        max_output_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
    ) -> Completion:
        """Return a single completion. Raises :class:`ProviderError` on failure."""

    @abc.abstractmethod
    def describe(self) -> dict[str, Any]:
        """Safe-to-log provider metadata. Must never include credentials."""

    def health_check(self) -> tuple[bool, str]:
        """Cheap connectivity probe. Default: report configured, untested."""
        return True, "no health check implemented"

    def check_model_available(self) -> tuple[Optional[bool], str]:
        """Whether the configured model is present on the backend.

        Returns ``(None, reason)`` when the backend cannot enumerate its models.
        Providers that can enumerate models should override this.
        """
        return None, "model availability check is not supported by this provider"

    def close(self) -> None:
        """Release any resources. Default: no-op."""
