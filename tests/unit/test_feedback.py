"""Tests for feedback analysis and prompt formatting."""

from __future__ import annotations

from verifyloop.feedback.analyzer import build_evidence, summarize_statuses
from verifyloop.feedback.formatter import (
    format_concise_report,
    format_evidence_report,
    format_initial_prompt,
    format_patch_rejection,
    format_repository_context,
)
from verifyloop.models import FailureCategory, TestCaseResult, TestReport


def make_report(*cases: TestCaseResult, exit_code: int = 1) -> TestReport:
    return TestReport(
        command=["python", "-m", "pytest"],
        exit_code=exit_code,
        duration_seconds=0.1,
        cases=list(cases),
        stdout="",
        stderr="",
    )


def test_evidence_lists_failing_tests() -> None:
    report = make_report(
        TestCaseResult(name="test_a", status="passed"),
        TestCaseResult(
            name="test_b", status="failed", message="AssertionError: 1 != 2"
        ),
    )
    evidence = build_evidence(report, attempt=1, attempts_remaining=2)
    assert evidence.total == 2
    assert evidence.passed == 1
    assert evidence.failed == 1
    assert evidence.failing_tests[0]["test"] == "test_b"
    assert "AssertionError" in evidence.failing_tests[0]["message"]


def test_evidence_detects_regressions() -> None:
    report = make_report(
        TestCaseResult(name="test_old", status="failed", message="boom"),
    )
    evidence = build_evidence(
        report, attempt=2, previous_passing={"test_old", "test_other"}
    )
    assert evidence.regression_tests == ["test_old"]


def test_evidence_truncates_long_messages() -> None:
    report = make_report(
        TestCaseResult(name="test_long", status="failed", message="x" * 5000)
    )
    evidence = build_evidence(report, attempt=1)
    assert len(evidence.failing_tests[0]["message"]) <= 520


def test_evidence_limits_number_of_tests_listed() -> None:
    report = make_report(
        *[TestCaseResult(name=f"test_{i}", status="failed", message="m") for i in range(30)]
    )
    evidence = build_evidence(report, attempt=1)
    assert len(evidence.failing_tests) <= 8


def test_evidence_records_timeout() -> None:
    report = TestReport(
        command=[], exit_code=-1, duration_seconds=1.0, timed_out=True
    )
    evidence = build_evidence(report, attempt=1, category=FailureCategory.TIMEOUT)
    assert evidence.timed_out
    rendered = format_evidence_report(evidence)
    assert "time limit" in rendered


def test_evidence_report_includes_budget_and_files() -> None:
    report = make_report(TestCaseResult(name="test_x", status="failed", message="err"))
    evidence = build_evidence(
        report,
        attempt=2,
        changed_files=["app.py", "util.py"],
        attempts_remaining=1,
        seconds_remaining=42.0,
    )
    rendered = format_evidence_report(evidence)
    assert "Attempt 2 failed" in rendered
    assert "app.py" in rendered
    assert "Repair attempts remaining: 1" in rendered
    assert "seconds remaining: 42" in rendered


def test_evidence_report_has_no_hidden_test_reference() -> None:
    report = make_report(TestCaseResult(name="tests/test_a.py::test_a", status="failed"))
    evidence = build_evidence(report, attempt=1)
    rendered = format_evidence_report(evidence)
    assert "eval_tests" not in rendered


def test_concise_report_omits_messages() -> None:
    report = make_report(
        TestCaseResult(name="test_a", status="failed", message="SECRET_ASSERTION_DETAIL")
    )
    evidence = build_evidence(report, attempt=1)
    rendered = format_concise_report(evidence, summarize_statuses(report))
    assert "FAILED: test_a" in rendered
    assert "SECRET_ASSERTION_DETAIL" not in rendered


def test_rejection_prompt_is_not_a_test_failure() -> None:
    rendered = format_patch_rejection(2, "path traversal not allowed", "diff")
    assert "patch rejected before execution" in rendered
    assert "not a test failure" in rendered


def test_initial_prompt_contains_all_sections() -> None:
    rendered = format_initial_prompt(
        "Fix the bug.", "It should work.", "### File: a.py\n```python\nx=1\n```", "diff"
    )
    assert "Bug report" in rendered
    assert "Required behaviour" in rendered
    assert "unified diff" in rendered


def test_initial_prompt_edit_json_instructions() -> None:
    rendered = format_initial_prompt("d", "e", "ctx", "edit_json")
    assert '"edits"' in rendered


def test_repository_context_truncates() -> None:
    files = {f"f{i}.py": "x = 1\n" * 500 for i in range(10)}
    rendered = format_repository_context(files, max_chars=2000)
    assert len(rendered) < 6000
    assert "File:" in rendered


def test_summarize_statuses_limits_output() -> None:
    report = make_report(
        *[TestCaseResult(name=f"t{i}", status="passed") for i in range(40)]
    )
    rendered = summarize_statuses(report, limit=5)
    assert rendered.count("\n") <= 5
    assert "more tests" in rendered
