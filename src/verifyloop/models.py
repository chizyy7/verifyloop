"""Shared data models used across the engine."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class Outcome(str, Enum):
    """Terminal outcome for a single task attempt under one strategy."""

    VERIFIED_SUCCESS = "verified_success"
    VISIBLE_ONLY_SUCCESS = "visible_only_success"  # visible pass, independent eval fail
    FAILED_TESTS = "failed_tests"
    PATCH_REJECTED = "patch_rejected"  # never applied
    PATCH_CONFLICT = "patch_conflict"  # applied attempt failed
    BUDGET_EXHAUSTED = "budget_exhausted"
    INVALID_TASK = "invalid_task"
    INFRASTRUCTURE_ERROR = "infrastructure_error"

    @property
    def is_success(self) -> bool:
        return self is Outcome.VERIFIED_SUCCESS

    @property
    def counts_toward_denominator(self) -> bool:
        """Infrastructure and invalid-task results are excluded from success rates."""
        return self not in {Outcome.INVALID_TASK, Outcome.INFRASTRUCTURE_ERROR}


class FailureCategory(str, Enum):
    ASSERTION = "assertion"
    EXCEPTION = "exception"
    IMPORT_ERROR = "import_error"
    SYNTAX_ERROR = "syntax_error"
    TIMEOUT = "timeout"
    NO_TESTS_COLLECTED = "no_tests_collected"
    COLLECTION_ERROR = "collection_error"
    ENVIRONMENT_ERROR = "environment_error"
    PATCH_FORMAT = "patch_format"
    PATCH_PATH = "patch_path"
    PATCH_CONFLICT = "patch_conflict"
    MODEL_ERROR = "model_error"
    BUDGET = "budget"
    NONE = "none"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class TestCaseResult:
    name: str
    status: str  # passed | failed | error | skipped
    duration_seconds: float = 0.0
    message: str = ""
    file: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "duration_seconds": round(self.duration_seconds, 6),
            "message": self.message,
            "file": self.file,
        }


@dataclass
class TestReport:
    """Normalized result of one test execution."""

    command: list[str]
    exit_code: int
    duration_seconds: float
    cases: list[TestCaseResult] = field(default_factory=list)
    stdout: str = ""
    stderr: str = ""
    #: Bounded, redacted excerpt of a pytest collection error. Empty when no
    #: recognizable collection failure was present.
    collection_error_excerpt: str = ""
    timed_out: bool = False
    infrastructure_error: bool = False
    infrastructure_message: str = ""

    @property
    def total(self) -> int:
        return len(self.cases)

    @property
    def passed(self) -> int:
        return sum(1 for case in self.cases if case.status == "passed")

    @property
    def failed(self) -> int:
        return sum(1 for case in self.cases if case.status == "failed")

    @property
    def errors(self) -> int:
        return sum(1 for case in self.cases if case.status == "error")

    @property
    def skipped(self) -> int:
        return sum(1 for case in self.cases if case.status == "skipped")

    @property
    def all_passed(self) -> bool:
        """True only when tests actually ran and none failed."""
        return (
            not self.timed_out
            and not self.infrastructure_error
            and self.total > 0
            and self.failed == 0
            and self.errors == 0
            and self.exit_code == 0
        )

    @property
    def no_tests_collected(self) -> bool:
        return self.total == 0 and not self.infrastructure_error

    @property
    def collection_failed(self) -> bool:
        """True when pytest reported a collection error.

        JUnit XML sometimes emits one synthetic error case for a collection failure,
        so ``total`` alone cannot distinguish this from a test that ran and failed.
        The console excerpt is the reliable signal.
        """
        return bool(self.collection_error_excerpt) and not (
            self.timed_out or self.infrastructure_error
        )

    def failing_cases(self) -> list[TestCaseResult]:
        return [case for case in self.cases if case.status in {"failed", "error"}]

    def summary_line(self) -> str:
        if self.timed_out:
            return "TIMEOUT"
        if self.infrastructure_error:
            return f"INFRASTRUCTURE_ERROR: {self.infrastructure_message}"
        if self.no_tests_collected:
            return "NO_TESTS_COLLECTED"
        return (
            f"{self.passed} passed, {self.failed} failed, "
            f"{self.errors} errors, {self.skipped} skipped"
        )

    def to_dict(self, *, include_output: bool = True) -> dict[str, Any]:
        data: dict[str, Any] = {
            "command": self.command,
            "exit_code": self.exit_code,
            "duration_seconds": round(self.duration_seconds, 4),
            "total": self.total,
            "passed": self.passed,
            "failed": self.failed,
            "errors": self.errors,
            "skipped": self.skipped,
            "timed_out": self.timed_out,
            "infrastructure_error": self.infrastructure_error,
            "infrastructure_message": self.infrastructure_message,
            "all_passed": self.all_passed,
            "no_tests_collected": self.no_tests_collected,
            "collection_failed": self.collection_failed,
            "collection_error_excerpt": self.collection_error_excerpt,
            "cases": [case.to_dict() for case in self.cases],
        }
        if include_output:
            data["stdout"] = self.stdout
            data["stderr"] = self.stderr
        return data


@dataclass
class PatchCandidate:
    """A parsed, not-yet-applied patch."""

    raw: str
    format: str  # "diff" | "edit_json" | "edit_json_single"
    changed_files: list[str] = field(default_factory=list)
    size_bytes: int = 0
    sha256: str = ""

    def __post_init__(self) -> None:
        if not self.size_bytes:
            self.size_bytes = len(self.raw.encode("utf-8"))
        if not self.sha256:
            self.sha256 = hashlib.sha256(self.raw.encode("utf-8")).hexdigest()


@dataclass
class ValidationResult:
    ok: bool
    reason: str = ""
    category: FailureCategory = FailureCategory.NONE
    changed_files: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "reason": self.reason,
            "category": self.category.value,
            "changed_files": self.changed_files,
        }


@dataclass
class AttemptDiagnostics:
    """Stage-by-stage outcome of one repair attempt.

    These flags exist because "the patch was rejected" is not a single failure mode.
    A model can return no usable response, return text that is not a patch, return a
    patch that cannot be validated, return a patch that cannot be applied, or return
    a patch that applies but prevents pytest from collecting or executing tests.
    Recording each stage separately makes those cases auditable instead of collapsing
    them into one rejection count.
    """

    model_response_received: bool = False
    patch_format_parsed: bool = False
    applicability_checked: bool = False
    applicability_validated: bool = False
    patch_applied: bool = False
    tests_collected: bool = False
    tests_executed: bool = False
    tests_passed: bool = False
    tests_failed: bool = False
    evidence_delivered: bool = False
    evidence_kind: str = ""
    evidence_prompt_sha256: str = ""
    evidence_prompt_chars: int = 0
    #: not_run | collection_error | timeout | infrastructure_error | passed | failed
    test_outcome: str = "not_run"
    #: model_response | patch_format | patch_validation | patch_application |
    #: test_collection | test_execution | test_result | (empty for success)
    failure_stage: str = ""
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_response_received": self.model_response_received,
            "patch_format_parsed": self.patch_format_parsed,
            "applicability_checked": self.applicability_checked,
            "applicability_validated": self.applicability_validated,
            "patch_applied": self.patch_applied,
            "tests_collected": self.tests_collected,
            "tests_executed": self.tests_executed,
            "tests_passed": self.tests_passed,
            "tests_failed": self.tests_failed,
            "evidence_delivered": self.evidence_delivered,
            "evidence_kind": self.evidence_kind,
            "evidence_prompt_sha256": self.evidence_prompt_sha256,
            "evidence_prompt_chars": self.evidence_prompt_chars,
            "test_outcome": self.test_outcome,
            "failure_stage": self.failure_stage,
            "detail": self.detail,
        }


@dataclass
class AttemptRecord:
    """Everything that happened in one generate → validate → test cycle."""

    attempt: int
    model_call_index: int
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    generation_seconds: float = 0.0
    patch: Optional[PatchCandidate] = None
    validation: Optional[ValidationResult] = None
    test_report: Optional[TestReport] = None
    failure_category: FailureCategory = FailureCategory.NONE
    applied: bool = False
    rejected_reason: str = ""
    model_error: str = ""
    #: Exact model text, truncated by the controller. Kept so that format
    #: failures can be analysed after the run instead of only counted.
    raw_output: str = ""
    diagnostics: AttemptDiagnostics = field(default_factory=AttemptDiagnostics)

    def to_dict(self, *, include_output: bool = False) -> dict[str, Any]:
        return {
            "attempt": self.attempt,
            "model_call_index": self.model_call_index,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "generation_seconds": round(self.generation_seconds, 4),
            "patch": (
                {
                    "format": self.patch.format,
                    "changed_files": self.patch.changed_files,
                    "size_bytes": self.patch.size_bytes,
                    "sha256": self.patch.sha256,
                }
                if self.patch
                else None
            ),
            "validation": self.validation.to_dict() if self.validation else None,
            "test_report": (
                self.test_report.to_dict(include_output=include_output)
                if self.test_report
                else None
            ),
            "failure_category": self.failure_category.value,
            "applied": self.applied,
            "rejected_reason": self.rejected_reason,
            "model_error": self.model_error,
            "raw_output": self.raw_output,
            "diagnostics": self.diagnostics.to_dict(),
        }


@dataclass
class TaskResult:
    """Persistable result of one strategy on one task for one trial."""

    run_id: str
    task_id: str
    strategy: str
    model: str
    provider: str
    benchmark_version: str
    trial: int
    outcome: Outcome
    attempts: list[AttemptRecord] = field(default_factory=list)
    feedback_reports: list[str] = field(default_factory=list)
    final_report: Optional[TestReport] = None
    baseline_report: Optional[TestReport] = None
    failure_category: FailureCategory = FailureCategory.NONE
    model_calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    generation_seconds: float = 0.0
    test_seconds: float = 0.0
    wall_clock_seconds: float = 0.0
    budget_exhausted: bool = False
    regression_detected: bool = False
    protected_assets_modified: bool = False
    error_message: str = ""
    state_log: list[dict[str, Any]] = field(default_factory=list)

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    def diagnostics_summary(self) -> dict[str, Any]:
        """Aggregate attempt-stage outcomes for analysis and CSV export.

        Counts are attempts, not tests. ``test_reachability`` means at least one
        attempt applied a patch and actually executed a non-empty test suite.
        """
        attempts = self.attempts
        first_failure = next(
            (
                attempt.diagnostics.failure_stage
                for attempt in attempts
                if attempt.diagnostics.failure_stage
            ),
            "",
        )
        return {
            "attempts_with_model_response": sum(
                attempt.diagnostics.model_response_received for attempt in attempts
            ),
            "attempts_patch_format_parsed": sum(
                attempt.diagnostics.patch_format_parsed for attempt in attempts
            ),
            "attempts_applicability_checked": sum(
                attempt.diagnostics.applicability_checked for attempt in attempts
            ),
            "attempts_applicability_validated": sum(
                attempt.diagnostics.applicability_validated for attempt in attempts
            ),
            "attempts_patch_applied": sum(
                attempt.diagnostics.patch_applied for attempt in attempts
            ),
            "attempts_tests_collected": sum(
                attempt.diagnostics.tests_collected for attempt in attempts
            ),
            "attempts_tests_executed": sum(
                attempt.diagnostics.tests_executed for attempt in attempts
            ),
            "attempts_tests_passed": sum(
                attempt.diagnostics.tests_passed for attempt in attempts
            ),
            "attempts_tests_failed": sum(
                attempt.diagnostics.tests_failed for attempt in attempts
            ),
            "attempts_evidence_delivered": sum(
                attempt.diagnostics.evidence_delivered for attempt in attempts
            ),
            "attempts_with_collection_error": sum(
                bool(
                    attempt.test_report
                    and attempt.test_report.collection_error_excerpt
                )
                for attempt in attempts
            ),
            "first_failure_stage": first_failure,
            "test_reachability": any(
                attempt.diagnostics.tests_executed for attempt in attempts
            ),
        }

    def to_dict(self, *, include_output: bool = False) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "task_id": self.task_id,
            "strategy": self.strategy,
            "model": self.model,
            "provider": self.provider,
            "benchmark_version": self.benchmark_version,
            "trial": self.trial,
            "outcome": self.outcome.value,
            "attempt_count": len(self.attempts),
            "attempts": [
                attempt.to_dict(include_output=include_output) for attempt in self.attempts
            ],
            "diagnostics": self.diagnostics_summary(),
            "feedback_reports": list(self.feedback_reports),
            "final_report": (
                self.final_report.to_dict(include_output=include_output)
                if self.final_report
                else None
            ),
            "baseline_report": (
                self.baseline_report.to_dict(include_output=False)
                if self.baseline_report
                else None
            ),
            "failure_category": self.failure_category.value,
            "model_calls": self.model_calls,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "generation_seconds": round(self.generation_seconds, 4),
            "test_seconds": round(self.test_seconds, 4),
            "wall_clock_seconds": round(self.wall_clock_seconds, 4),
            "budget_exhausted": self.budget_exhausted,
            "regression_detected": self.regression_detected,
            "protected_assets_modified": self.protected_assets_modified,
            "error_message": self.error_message,
            "state_log": self.state_log,
        }
