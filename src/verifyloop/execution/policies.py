"""Execution policies: the exact commands VerifyLoop is permitted to run."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from verifyloop.execution.result_parser import classify_execution, count_console_collected
from verifyloop.execution.runner import ExecutionLimits, RawExecution, run_command
from verifyloop.models import TestReport


@dataclass(frozen=True)
class TestPolicy:
    """A declared, reproducible test invocation."""

    argv: tuple[str, ...]
    suite: str  # "feedback" | "eval" | "baseline"

    def describe(self) -> dict:
        return {"argv": list(self.argv), "suite": self.suite}


def pytest_policy(paths: Sequence[str], *, suite: str) -> TestPolicy:
    """Build a pytest policy that always emits JUnit XML for reliable parsing."""
    return TestPolicy(
        argv=(
            "python",
            "-m",
            "pytest",
            *paths,
            "-q",
            "-p",
            "no:cacheprovider",
            "--junitxml=.verifyloop/junit.xml",
        ),
        suite=suite,
    )


def run_test_policy(
    policy: TestPolicy,
    cwd: Path,
    *,
    allowed_commands: Sequence[str],
    limits: ExecutionLimits,
) -> TestReport:
    """Execute a test policy and normalize the result."""
    junit_path = cwd / ".verifyloop" / "junit.xml"
    if junit_path.exists():
        junit_path.unlink()
    junit_path.parent.mkdir(parents=True, exist_ok=True)

    raw: RawExecution = run_command(
        policy.argv,
        cwd,
        allowed_commands=allowed_commands,
        limits=limits,
    )
    report = classify_execution(raw, junit_path)

    # Cross-check: pytest says it collected tests but we parsed none.
    if (
        report.total == 0
        and not report.infrastructure_error
        and not report.timed_out
        and count_console_collected(f"{raw.stdout}\n{raw.stderr}")
    ):
        report.infrastructure_error = True
        report.infrastructure_message = (
            "pytest collected tests but no results could be parsed"
        )

    return report
