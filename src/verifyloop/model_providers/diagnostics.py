"""Provider connection diagnostics.

A reachable HTTP endpoint is not evidence that a model can generate usable output.
This module checks, in order:

1. the API is reachable,
2. the configured model is installed (when the backend can enumerate models),
3. a tiny generation request succeeds,
4. the completion payload can be parsed into non-empty text.

It never downloads models and never mutates the configured provider.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from verifyloop.model_providers.base import (
    Completion,
    ModelProvider,
    ProviderError,
    ProviderResponseError,
    ProviderTimeout,
    ProviderUnavailable,
)

DIAGNOSTIC_SYSTEM = "You are a terse assistant."
DIAGNOSTIC_PROMPT = "Reply with exactly the word: ready"

#: Fragments llama.cpp/Ollama use when a model cannot be loaded into RAM.
_MEMORY_MARKERS = (
    "unable to allocate",
    "cannot allocate",
    "failed to allocate",
    "cpu_repack",
    "failed to load model",
    "out of memory",
    "not enough memory",
)


@dataclass(frozen=True)
class DiagnosticStep:
    """One check in the diagnostic sequence."""

    name: str
    ok: bool
    message: str
    hint: str = ""


@dataclass
class DiagnosticReport:
    """Structured outcome of a provider check."""

    provider: str
    model: str
    base_url: str
    steps: list[DiagnosticStep] = field(default_factory=list)
    completion: Optional[Completion] = None

    @property
    def ok(self) -> bool:
        return bool(self.steps) and all(step.ok for step in self.steps)

    def render(self) -> str:
        lines = [
            f"provider: {self.provider}",
            f"model: {self.model}",
            f"base_url: {self.base_url or '(not applicable)'}",
            "",
        ]
        for step in self.steps:
            status = "OK" if step.ok else "FAIL"
            lines.append(f"[{status}] {step.name}: {step.message}")
            if step.hint:
                lines.append(f"       hint: {step.hint}")
        lines.append("")
        lines.append(f"result: {'PASS' if self.ok else 'FAIL'}")
        return "\n".join(lines)


def hint_for_error(exc: ProviderError) -> str:
    """Return an actionable hint without inventing a cause."""
    return _hint_for_text(
        str(exc),
        timeout=isinstance(exc, ProviderTimeout),
        unavailable=isinstance(exc, ProviderUnavailable),
        response=isinstance(exc, ProviderResponseError),
    )


def _hint_for_text(
    text: str,
    *,
    timeout: bool = False,
    unavailable: bool = False,
    response: bool = False,
) -> str:
    lowered = text.lower()
    if any(marker in lowered for marker in _MEMORY_MARKERS):
        return (
            "The backend could not load the model into memory. Free RAM (close other "
            "applications) or use a smaller model; VerifyLoop does not change system "
            "settings or download models automatically."
        )
    if timeout:
        return (
            "The request exceeded the configured timeout. Increase "
            "REQUEST_TIMEOUT_SECONDS or reduce the prompt size."
        )
    if unavailable:
        return (
            "The backend may not be running. Start Ollama with `ollama serve`, then "
            "confirm MODEL_BASE_URL (default http://localhost:11434)."
        )
    if response:
        return (
            "The server responded, but the payload was not a usable chat completion. "
            "Check the model name and the Ollama server log."
        )
    return ""


def diagnose_provider(
    provider: ModelProvider, *, max_output_tokens: int = 16
) -> DiagnosticReport:
    """Run the full diagnostic sequence against ``provider``."""
    report = DiagnosticReport(
        provider=getattr(provider, "name", "unknown"),
        model=getattr(provider, "model", "unknown"),
        base_url=getattr(provider, "base_url", ""),
    )

    reachable, message = provider.health_check()
    if not reachable:
        report.steps.append(
            DiagnosticStep(
                "api_reachable",
                False,
                message,
                hint=_hint_for_text(message, unavailable=True),
            )
        )
        return report
    report.steps.append(DiagnosticStep("api_reachable", True, message))

    installed, model_message = provider.check_model_available()
    if installed is not None:
        hint = ""
        if not installed:
            hint = (
                "Install it manually with `ollama pull <model>`; VerifyLoop never "
                "downloads models automatically."
            )
        report.steps.append(
            DiagnosticStep("model_installed", installed, model_message, hint)
        )
        if not installed:
            return report

    try:
        completion = provider.complete(
            DIAGNOSTIC_SYSTEM,
            DIAGNOSTIC_PROMPT,
            max_output_tokens=max_output_tokens,
        )
    except ProviderError as exc:
        report.steps.append(
            DiagnosticStep(
                "generation",
                False,
                f"{type(exc).__name__}: {exc}",
                hint=hint_for_error(exc),
            )
        )
        return report
    except Exception as exc:  # noqa: BLE001 - diagnostics must report, not crash
        report.steps.append(
            DiagnosticStep("generation", False, f"{type(exc).__name__}: {exc}")
        )
        return report

    report.completion = completion
    report.steps.append(
        DiagnosticStep(
            "generation",
            True,
            f"completed in {completion.duration_seconds:.2f}s"
            + _format_usage(completion),
        )
    )

    text = (completion.text or "").strip()
    if not text:
        report.steps.append(
            DiagnosticStep("response_parseable", False, "completion text was empty")
        )
        return report
    preview = " ".join(text.split())[:120]
    report.steps.append(DiagnosticStep("response_parseable", True, repr(preview)))
    return report


def _format_usage(completion: Completion) -> str:
    if completion.prompt_tokens is None and completion.completion_tokens is None:
        return " (token usage not reported)"
    return (
        f" ({completion.prompt_tokens} prompt + "
        f"{completion.completion_tokens} completion tokens)"
    )
