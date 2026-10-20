"""Tests for bounded diagnostic redaction."""

from __future__ import annotations

from verifyloop.redaction import REDACTED, redact_text


def test_redacts_environment_secret_values(monkeypatch) -> None:
    monkeypatch.setenv("SERVICE_TOKEN", "env-secret-value")
    text = "traceback: env-secret-value"
    assert "env-secret-value" not in redact_text(text)
    assert REDACTED in redact_text(text)


def test_redacts_key_value_and_common_token_shapes() -> None:
    text = (
        'API_KEY=abc123 password="hunter2" '
        "Authorization: Bearer abc.def.ghi sk-abcdefghijkl "
        "ghp_abcdefghijklmnopqrstuvwxyz0123456789"
    )
    redacted = redact_text(text)
    assert "abc123" not in redacted
    assert "hunter2" not in redacted
    assert "abc.def.ghi" not in redacted
    assert "sk-abcdefghijkl" not in redacted
    assert "ghp_abcdefghijklmnopqrstuvwxyz0123456789" not in redacted
    assert REDACTED in redacted


def test_preserves_non_secret_context() -> None:
    text = "ERROR collecting tests/test_app.py: AssertionError: 1 != 2"
    assert redact_text(text) == text
