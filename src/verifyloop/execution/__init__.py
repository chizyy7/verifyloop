"""Allowlisted subprocess execution and test-result normalization."""

from __future__ import annotations

from verifyloop.execution.policies import TestPolicy, pytest_policy, run_test_policy
from verifyloop.execution.result_parser import (
    categorize_failure,
    classify_execution,
    count_console_collected,
)
from verifyloop.execution.runner import (
    CommandNotAllowed,
    ExecutionLimits,
    RawExecution,
    build_command,
    resolve_executable,
    run_command,
)

__all__ = [
    "CommandNotAllowed",
    "ExecutionLimits",
    "RawExecution",
    "TestPolicy",
    "build_command",
    "categorize_failure",
    "classify_execution",
    "count_console_collected",
    "pytest_policy",
    "resolve_executable",
    "run_command",
    "run_test_policy",
]
