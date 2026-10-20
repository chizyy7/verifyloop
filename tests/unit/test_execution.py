"""Tests for the subprocess runner and pytest result classification."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from verifyloop.execution.policies import pytest_policy, run_test_policy
from verifyloop.execution.result_parser import categorize_failure, classify_execution
from verifyloop.execution.runner import (
    CommandNotAllowed,
    ExecutionLimits,
    build_command,
    run_command,
)


def test_rejects_command_outside_allowlist(tmp_path: Path) -> None:
    with pytest.raises(CommandNotAllowed):
        run_command(["rm", "-rf", "/"], tmp_path, allowed_commands=["python"])


def test_build_command_maps_python_to_interpreter() -> None:
    command = build_command(["python", "-c", "print(1)"], ["python"])
    assert command[0] == sys.executable


def test_build_command_rejects_empty() -> None:
    with pytest.raises(ValueError):
        build_command([], ["python"])


def test_runs_python_and_captures_output(tmp_path: Path) -> None:
    raw = run_command(
        ["python", "-c", "print('hello')"],
        tmp_path,
        allowed_commands=["python"],
        limits=ExecutionLimits(timeout_seconds=30),
    )
    assert raw.ok
    assert "hello" in raw.stdout


def test_timeout_is_detected(tmp_path: Path) -> None:
    raw = run_command(
        ["python", "-c", "import time; time.sleep(10)"],
        tmp_path,
        allowed_commands=["python"],
        limits=ExecutionLimits(timeout_seconds=1),
    )
    assert raw.timed_out
    assert not raw.ok
    report = classify_execution(raw)
    assert report.timed_out
    assert categorize_failure(report).value == "timeout"


def test_output_is_truncated(tmp_path: Path) -> None:
    raw = run_command(
        ["python", "-c", "print('x' * 100000)"],
        tmp_path,
        allowed_commands=["python"],
        limits=ExecutionLimits(timeout_seconds=30, max_output_bytes=1000),
    )
    assert raw.truncated
    assert len(raw.stdout) < 5000


def test_nonzero_exit_is_not_a_launch_error(tmp_path: Path) -> None:
    raw = run_command(
        ["python", "-c", "raise SystemExit(3)"],
        tmp_path,
        allowed_commands=["python"],
        limits=ExecutionLimits(timeout_seconds=30),
    )
    assert raw.exit_code == 3
    assert raw.launch_error == ""


def _write_passing_test(directory: Path) -> None:
    (directory / "test_ok.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")


def _write_failing_test(directory: Path) -> None:
    (directory / "test_bad.py").write_text(
        "def test_bad():\n    assert 1 == 2\n", encoding="utf-8"
    )


def test_pytest_policy_reports_passing(tmp_path: Path) -> None:
    _write_passing_test(tmp_path)
    report = run_test_policy(
        pytest_policy(["."], suite="feedback"),
        tmp_path,
        allowed_commands=["python"],
        limits=ExecutionLimits(timeout_seconds=60),
    )
    assert report.all_passed
    assert report.total == 1
    assert categorize_failure(report).value == "none"


def test_pytest_policy_reports_failure(tmp_path: Path) -> None:
    _write_failing_test(tmp_path)
    report = run_test_policy(
        pytest_policy(["."], suite="feedback"),
        tmp_path,
        allowed_commands=["python"],
        limits=ExecutionLimits(timeout_seconds=60),
    )
    assert not report.all_passed
    assert report.failed == 1
    assert categorize_failure(report).value == "assertion"


def test_no_tests_collected_is_not_success(tmp_path: Path) -> None:
    (tmp_path / "empty.py").write_text("x = 1\n", encoding="utf-8")
    report = run_test_policy(
        pytest_policy(["."], suite="feedback"),
        tmp_path,
        allowed_commands=["python"],
        limits=ExecutionLimits(timeout_seconds=60),
    )
    assert not report.all_passed
    assert report.no_tests_collected


def test_collection_error_is_classified(tmp_path: Path) -> None:
    (tmp_path / "test_broken.py").write_text(
        "import module_that_does_not_exist\n", encoding="utf-8"
    )
    report = run_test_policy(
        pytest_policy(["."], suite="feedback"),
        tmp_path,
        allowed_commands=["python"],
        limits=ExecutionLimits(timeout_seconds=60),
    )
    assert not report.all_passed
    assert not report.all_passed  # explicit: never count this as success


def test_syntax_error_classified(tmp_path: Path) -> None:
    (tmp_path / "test_syntax.py").write_text("def test(:\n", encoding="utf-8")
    report = run_test_policy(
        pytest_policy(["."], suite="feedback"),
        tmp_path,
        allowed_commands=["python"],
        limits=ExecutionLimits(timeout_seconds=60),
    )
    assert not report.all_passed


def test_collection_error_excerpt_is_actionable(tmp_path: Path) -> None:
    (tmp_path / "test_broken.py").write_text(
        'raise RuntimeError("API_KEY=supersecret-value")\n', encoding="utf-8"
    )
    report = run_test_policy(
        pytest_policy(["."], suite="feedback"),
        tmp_path,
        allowed_commands=["python"],
        limits=ExecutionLimits(timeout_seconds=60),
    )
    assert report.collection_failed
    assert report.collection_error_excerpt
    assert "RuntimeError" in report.collection_error_excerpt
    assert "supersecret-value" not in report.collection_error_excerpt
    assert "***redacted***" in report.collection_error_excerpt
    assert "site-packages" not in report.collection_error_excerpt
    assert "test_broken.py" in report.collection_error_excerpt
    assert categorize_failure(report).value == "collection_error"


def test_collection_error_redacts_environment_secret(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SERVICE_TOKEN", "env-secret-value")
    (tmp_path / "test_broken.py").write_text(
        'raise RuntimeError("env-secret-value")\n', encoding="utf-8"
    )
    report = run_test_policy(
        pytest_policy(["."], suite="feedback"),
        tmp_path,
        allowed_commands=["python"],
        limits=ExecutionLimits(timeout_seconds=60),
    )
    assert "env-secret-value" not in report.collection_error_excerpt
    assert "***redacted***" in report.collection_error_excerpt


def test_syntax_error_excerpt_contains_exception(tmp_path: Path) -> None:
    (tmp_path / "test_syntax.py").write_text("def test(:\n", encoding="utf-8")
    report = run_test_policy(
        pytest_policy(["."], suite="feedback"),
        tmp_path,
        allowed_commands=["python"],
        limits=ExecutionLimits(timeout_seconds=60),
    )
    assert report.collection_error_excerpt
    assert "SyntaxError" in report.collection_error_excerpt
    assert "site-packages" not in report.collection_error_excerpt
    assert "C:\\Users" not in report.collection_error_excerpt
    assert categorize_failure(report).value == "syntax_error"
