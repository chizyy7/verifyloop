"""Turn a failed :class:`TestReport` into structured, bounded diagnostic evidence.

Two levels of detail are supported so the feedback-detail ablation is a
configuration change rather than a code fork:

``concise``
    Statuses and test names only. This is the ablation control for "does the
    *content* of the evidence matter, or merely the signal that something failed?"

``structured``
    Statuses, test names, clipped failure messages, traceback excerpts, regression
    indicators, changed files, and remaining budget.

Both are derived only from *visible* feedback tests. Hidden evaluation results are
never passed to this module.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Sequence

from verifyloop.models import FailureCategory, TestCaseResult, TestReport
from verifyloop.redaction import redact_text

MAX_MESSAGE_CHARS = 500
MAX_TOTAL_MESSAGE_CHARS = 2_500
MAX_TESTS_LISTED = 8


@dataclass
class FailureEvidence:
    """Structured summary of one failed test run."""

    attempt: int
    total: int
    passed: int
    failed: int
    errors: int
    skipped: int
    failing_tests: list[dict[str, str]] = field(default_factory=list)
    regression_tests: list[str] = field(default_factory=list)
    changed_files: list[str] = field(default_factory=list)
    attempts_remaining: int = 0
    seconds_remaining: float = 0.0
    category: FailureCategory = FailureCategory.UNKNOWN
    timed_out: bool = False
    no_tests_collected: bool = False
    collection_failed: bool = False
    infrastructure_error: bool = False
    infrastructure_message: str = ""
    collection_error_excerpt: str = ""
    exit_code: int = 0

    def to_dict(self) -> dict:
        return {
            "attempt": self.attempt,
            "total": self.total,
            "passed": self.passed,
            "failed": self.failed,
            "errors": self.errors,
            "skipped": self.skipped,
            "failing_tests": self.failing_tests,
            "regression_tests": self.regression_tests,
            "changed_files": self.changed_files,
            "attempts_remaining": self.attempts_remaining,
            "seconds_remaining": round(self.seconds_remaining, 1),
            "category": self.category.value,
            "timed_out": self.timed_out,
            "no_tests_collected": self.no_tests_collected,
            "collection_failed": self.collection_failed,
            "infrastructure_error": self.infrastructure_error,
            "infrastructure_message": self.infrastructure_message,
            "collection_error_excerpt": self.collection_error_excerpt,
            "exit_code": self.exit_code,
        }


def _clip(text: str, limit: int = MAX_MESSAGE_CHARS) -> str:
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def _traceback_excerpt(case: TestCaseResult) -> str:
    """Extract a short traceback-ish excerpt from a pytest failure message."""
    message = case.message.strip()
    if not message:
        return ""
    lines = [line.rstrip() for line in message.splitlines() if line.strip()]
    if len(lines) <= 6:
        return "\n".join(lines)
    # Keep the tail: the final assertion line carries the signal.
    return "\n".join(lines[-6:])


def build_evidence(
    report: TestReport,
    *,
    attempt: int,
    changed_files: Sequence[str] = (),
    previous_passing: Iterable[str] = (),
    attempts_remaining: int = 0,
    seconds_remaining: float = 0.0,
    category: FailureCategory | None = None,
) -> FailureEvidence:
    """Summarize ``report`` into bounded evidence."""
    previous = set(previous_passing)
    failing = report.failing_cases()

    entries: list[dict[str, str]] = []
    total_chars = 0
    for case in failing[:MAX_TESTS_LISTED]:
        excerpt = redact_text(_traceback_excerpt(case))
        if total_chars + len(excerpt) > MAX_TOTAL_MESSAGE_CHARS:
            excerpt = excerpt[: max(0, MAX_TOTAL_MESSAGE_CHARS - total_chars)]
        total_chars += len(excerpt)
        entries.append(
            {
                "test": case.name,
                "status": case.status,
                "message": _clip(redact_text(case.message)),
                "traceback_excerpt": excerpt,
            }
        )

    regressions = [
        case.name
        for case in failing
        if case.name in previous
    ]

    resolved_category = category or FailureCategory.UNKNOWN
    return FailureEvidence(
        attempt=attempt,
        total=report.total,
        passed=report.passed,
        failed=report.failed,
        errors=report.errors,
        skipped=report.skipped,
        failing_tests=entries,
        regression_tests=regressions,
        changed_files=list(changed_files),
        attempts_remaining=attempts_remaining,
        seconds_remaining=seconds_remaining,
        category=resolved_category,
        timed_out=report.timed_out,
        no_tests_collected=report.no_tests_collected,
        collection_failed=report.collection_failed,
        infrastructure_error=report.infrastructure_error,
        infrastructure_message=report.infrastructure_message,
        collection_error_excerpt=report.collection_error_excerpt,
        exit_code=report.exit_code,
    )


def passing_test_names(report: TestReport) -> set[str]:
    return {case.name for case in report.cases if case.status == "passed"}


def summarize_statuses(report: TestReport, limit: int = 12) -> str:
    """One-line-per-test status listing used by the concise condition."""
    lines: list[str] = []
    for case in report.cases[:limit]:
        lines.append(f"- {case.status.upper()}: {case.name}")
    if report.total > limit:
        lines.append(f"- ... {report.total - limit} more tests")
    return "\n".join(lines)
