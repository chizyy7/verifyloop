"""Tests for configuration loading, validation, and secret handling."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from pydantic import ValidationError

from verifyloop.config import (
    ExperimentConfig,
    ProviderConfig,
    apply_env_overrides,
    load_config,
    load_default_config,
    parse_dotenv,
    resolve_api_key,
)


def test_parse_dotenv_handles_comments_quotes_and_export() -> None:
    text = """
    # comment
    export A=1
    B="two words"
    C='single'
    MALFORMED
    EMPTY=
    """
    values = parse_dotenv(text)
    assert values == {"A": "1", "B": "two words", "C": "single", "EMPTY": ""}


def test_env_override_coerces_types() -> None:
    raw = {"provider": {"provider": "mock", "max_output_tokens": 900}}
    env = {"MAX_OUTPUT_TOKENS": "1500", "MODEL_PROVIDER": "ollama"}
    merged = apply_env_overrides(raw, env)
    assert merged["provider"]["max_output_tokens"] == 1500
    assert merged["provider"]["provider"] == "ollama"


def test_env_override_ignores_blank_values() -> None:
    raw = {"provider": {"provider": "mock"}}
    merged = apply_env_overrides(raw, {"MODEL_PROVIDER": ""})
    assert merged["provider"]["provider"] == "mock"


def test_defaults_are_valid() -> None:
    config = ExperimentConfig()
    assert config.provider.provider == "mock"
    assert config.budgets.max_attempts == 3
    assert config.strategies == ["oneshot", "blind_retry", "evidence_guided"]


def test_unknown_strategy_rejected() -> None:
    with pytest.raises(ValidationError):
        ExperimentConfig(strategies=["oneshot", "magic"])


def test_duplicate_strategies_collapse() -> None:
    config = ExperimentConfig(strategies=["oneshot", "oneshot"])
    assert config.strategies == ["oneshot"]


def test_zero_attempts_rejected() -> None:
    with pytest.raises(ValidationError):
        ExperimentConfig(budgets={"max_attempts": 0})


def test_unknown_key_rejected() -> None:
    with pytest.raises(ValidationError):
        ExperimentConfig.model_validate({"not_a_field": 1})


def test_missing_config_file_raises() -> None:
    with pytest.raises(FileNotFoundError):
        load_config("definitely-not-here.yaml", use_env=False)


def test_load_config_reads_yaml(tmp_path: Path) -> None:
    path = tmp_path / "c.yaml"
    path.write_text(
        "name: trial\nprovider:\n  provider: mock\n  model: x\ntrials: 2\n",
        encoding="utf-8",
    )
    config = load_config(path, use_env=False)
    assert config.name == "trial"
    assert config.trials == 2
    assert config.provider.model == "x"


def test_secret_is_never_serialized() -> None:
    provider = ProviderConfig(provider="openai_compatible", api_key_env="MY_TEST_KEY")
    provider = provider.with_api_key("super-secret-value")
    dumped = str(provider.model_dump())
    described = str(provider.describe())
    redacted = str(ExperimentConfig(provider=provider).redacted_dict())
    assert "super-secret-value" not in dumped
    assert "super-secret-value" not in described
    assert "super-secret-value" not in redacted
    assert described.find("True") != -1 or "api_key_present" in described


def test_describe_reports_presence_not_value() -> None:
    provider = ProviderConfig(provider="ollama").with_api_key("abc123")
    described = provider.describe()
    assert described["api_key_present"] is True
    assert "abc123" not in str(described)


def test_resolve_api_key_uses_named_variable() -> None:
    provider = ProviderConfig(api_key_env="VERIFYLOOP_TEST_KEY_XYZ")
    assert resolve_api_key(provider, {"VERIFYLOOP_TEST_KEY_XYZ": "v"}) == "v"
    assert resolve_api_key(provider, {}) is None


def test_default_config_file_loads() -> None:
    config = load_default_config(use_env=False)
    assert config.name == "default"
    assert config.benchmark.version == "v1"
