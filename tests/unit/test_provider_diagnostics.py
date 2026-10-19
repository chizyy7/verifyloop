"""Tests for the provider diagnostics and Ollama model discovery.

All HTTP traffic is served by ``httpx.MockTransport``; these tests never contact a
real Ollama instance.
"""

from __future__ import annotations

import json

import httpx

from verifyloop.model_providers.base import ProviderTimeout
from verifyloop.model_providers.compatible_api import OllamaProvider
from verifyloop.model_providers.diagnostics import (
    diagnose_provider,
    hint_for_error,
)

MODEL = "llama3.2:3b"


def _provider(handler, *, model: str = MODEL) -> OllamaProvider:
    return OllamaProvider(
        model=model,
        base_url="http://ollama.test",
        timeout_seconds=5,
        transport=httpx.MockTransport(handler),
    )


def _tags(*names: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={"models": [{"name": name, "model": name} for name in names]},
    )


def _chat(content: str = "Ready") -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "model": MODEL,
            "message": {"role": "assistant", "content": content},
            "prompt_eval_count": 12,
            "eval_count": 1,
            "done_reason": "stop",
        },
    )


def test_diagnostics_pass_with_installed_model() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/tags":
            return _tags(MODEL, "nomic-embed-text:latest")
        if request.url.path == "/api/chat":
            payload = json.loads(request.content)
            assert payload["model"] == MODEL
            assert payload["stream"] is False
            return _chat()
        return httpx.Response(404)

    report = diagnose_provider(_provider(handler))

    assert report.ok
    assert [step.name for step in report.steps] == [
        "api_reachable",
        "model_installed",
        "generation",
        "response_parseable",
    ]
    assert report.completion is not None
    assert report.completion.prompt_tokens == 12
    assert report.completion.completion_tokens == 1
    assert "PASS" in report.render()


def test_missing_model_is_reported_with_install_hint() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _tags("nomic-embed-text:latest")

    report = diagnose_provider(_provider(handler))

    assert not report.ok
    assert [step.name for step in report.steps] == ["api_reachable", "model_installed"]
    installed = report.steps[-1]
    assert not installed.ok
    assert "not installed" in installed.message
    assert "nomic-embed-text:latest" in installed.message
    assert "ollama pull" in installed.hint


def test_memory_allocation_failure_includes_body_and_hint() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/tags":
            return _tags(MODEL)
        return httpx.Response(
            500,
            json={"error": "unable to allocate CPU_REPACK buffer of size 3359637504"},
        )

    report = diagnose_provider(_provider(handler))

    assert not report.ok
    generation = next(step for step in report.steps if step.name == "generation")
    assert not generation.ok
    assert "CPU_REPACK" in generation.message
    assert "memory" in generation.hint.lower()
    assert "smaller model" in generation.hint.lower()


def test_unreachable_server_reports_start_hint() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    report = diagnose_provider(_provider(handler))

    assert not report.ok
    assert [step.name for step in report.steps] == ["api_reachable"]
    assert not report.steps[0].ok
    assert "ollama serve" in report.steps[0].hint


def test_empty_completion_is_reported_as_generation_failure() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/tags":
            return _tags(MODEL)
        return _chat("   ")

    report = diagnose_provider(_provider(handler))

    assert not report.ok
    generation = next(step for step in report.steps if step.name == "generation")
    assert not generation.ok
    assert "empty completion" in generation.message.lower()


def test_check_model_available_accepts_implicit_latest_tag() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _tags("llama3.2:latest")

    provider = _provider(handler, model="llama3.2")

    available, message = provider.check_model_available()

    assert available is True
    assert "installed" in message


def test_list_models_parses_native_tags_payload() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _tags(MODEL, "nomic-embed-text:latest")

    assert _provider(handler).list_models() == [MODEL, "nomic-embed-text:latest"]


def test_timeout_hint_mentions_timeout_setting() -> None:
    hint = hint_for_error(ProviderTimeout("request timed out after 5s"))

    assert "REQUEST_TIMEOUT_SECONDS" in hint


def test_cli_exposes_provider_check_command() -> None:
    from verifyloop.cli import build_parser

    args = build_parser().parse_args(["provider-check", "--timeout", "5"])

    assert args.func.__name__ == "cmd_provider_check"
    assert args.timeout == 5.0
