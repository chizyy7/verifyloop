"""Integration tests for the controller.

These cover the ten scenarios required by the project brief. They use the real
subprocess test runner and a scripted mock provider; no network access is required.
They prove the *mechanism* works. They are not evidence about real-model behaviour.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from verifyloop.benchmark.manifest import load_benchmark
from verifyloop.config import BudgetConfig
from verifyloop.controller import ControllerConfig, RepairController
from verifyloop.model_providers.base import ProviderTimeout
from verifyloop.model_providers.mock import MockProvider, MockResponse
from verifyloop.models import Outcome
from verifyloop.strategies import get_strategy

REPO_ROOT = Path(__file__).resolve().parents[2]
BENCHMARK_ROOT = REPO_ROOT / "benchmarks" / "synthetic"

TASK_ID = "boundary_paginate_001"


@pytest.fixture(scope="module")
def task():
    _, tasks = load_benchmark(BENCHMARK_ROOT, version="v1", task_ids=[TASK_ID])
    return tasks[0]


@pytest.fixture(scope="module")
def reference_patch(task) -> str:
    return task.read_reference_patch()


def make_controller(
    task,
    responses,
    *,
    strategy: str = "evidence_guided",
    max_attempts: int = 3,
    max_model_calls: int = 12,
    max_total_tokens: int = 60_000,
    max_wall_clock_seconds: float = 300,
    patch_format: str = "diff",
) -> RepairController:
    provider = MockProvider(responses=responses, model="mock-scripted")
    return RepairController(
        provider=provider,
        strategy=get_strategy(strategy),
        config=ControllerConfig(
            budgets=BudgetConfig(
                max_attempts=max_attempts,
                max_model_calls=max_model_calls,
                max_total_tokens=max_total_tokens,
                max_wall_clock_seconds=max_wall_clock_seconds,
                test_timeout_seconds=60,
            ),
            allowed_commands=["python", "py", "pytest"],
            patch_format=patch_format,
        ),
        task=task,
    )


def broken_variant(patch: str) -> str:
    """A patch that applies cleanly but is still wrong."""
    return patch.replace(
        "    end = start + per_page\n", "    end = start + per_page - 1\n"
    )


# 1 -------------------------------------------------------------------------
def test_scenario_1_valid_patch_succeeds(task, reference_patch) -> None:
    result = make_controller(
        task, [MockResponse(text=reference_patch)], strategy="oneshot"
    ).run()
    assert result.outcome is Outcome.VERIFIED_SUCCESS
    assert result.final_report is not None
    assert result.final_report.all_passed
    assert result.protected_assets_modified is False


# 2 -------------------------------------------------------------------------
def test_scenario_2_repair_recovers(task, reference_patch) -> None:
    result = make_controller(
        task,
        [MockResponse(text=broken_variant(reference_patch)),
         MockResponse(text=reference_patch)],
        strategy="evidence_guided",
    ).run()
    assert result.outcome is Outcome.VERIFIED_SUCCESS
    assert len(result.attempts) == 2
    assert result.attempts[0].test_report is not None
    assert not result.attempts[0].test_report.all_passed
    assert result.feedback_reports, "evidence strategy must produce a feedback report"
    assert "Attempt 1 failed" in result.feedback_reports[0]


# 3 -------------------------------------------------------------------------
def test_scenario_3_all_attempts_fail(task, reference_patch) -> None:
    broken = broken_variant(reference_patch)
    result = make_controller(
        task,
        [MockResponse(text=broken) for _ in range(3)],
        strategy="evidence_guided",
        max_attempts=3,
    ).run()
    assert result.outcome is Outcome.FAILED_TESTS
    assert len(result.attempts) == 3


# 4 -------------------------------------------------------------------------
def test_scenario_4_patch_cannot_apply(task) -> None:
    bad_patch = """--- a/paging.py
+++ b/paging.py
@@ -1,1 +1,1 @@
-this context does not exist anywhere
+replaced
"""
    result = make_controller(
        task,
        [MockResponse(text=bad_patch), MockResponse(text=bad_patch)],
        strategy="evidence_guided",
        max_attempts=2,
    ).run()
    assert result.outcome is Outcome.PATCH_REJECTED
    assert all(not attempt.applied for attempt in result.attempts)
    assert "context not found" in result.attempts[0].rejected_reason


# 5 -------------------------------------------------------------------------
def test_scenario_5_test_timeout(task, reference_patch, tmp_path) -> None:
    # Replace the feedback test with one that sleeps, inside a private task copy.
    import shutil

    task_copy = tmp_path / "task"
    shutil.copytree(task.task_dir, task_copy)
    (task_copy / "repo" / "tests" / "test_paging.py").write_text(
        "import time\n\n\ndef test_slow():\n    time.sleep(30)\n",
        encoding="utf-8",
    )
    _, tasks = load_benchmark(
        tmp_path, version=None, task_ids=None
    ) if False else (None, None)
    # Load directly from the copied task directory via the loader.
    from verifyloop.benchmark.manifest import LoadedTask, TaskDefinition

    definition = TaskDefinition.model_validate_json(
        (task_copy / "task.json").read_text(encoding="utf-8")
    )
    slow_task = LoadedTask(
        definition=definition,
        task_dir=task_copy,
        repo_dir=task_copy / "repo",
        eval_tests_dir=task_copy / "eval_tests",
        reference_patch_path=task_copy / "reference" / "fix.patch",
        benchmark_version="v1",
        entry_sha256="0" * 64,
    )
    controller = make_controller(
        slow_task, [MockResponse(text=reference_patch)], max_attempts=1
    )
    controller.config.budgets.test_timeout_seconds = 2
    result = controller.run()
    # Baseline times out, so the task is classified as infrastructure failure.
    assert result.outcome is Outcome.INFRASTRUCTURE_ERROR
    assert "TIMEOUT" in result.error_message


# 6 -------------------------------------------------------------------------
def test_scenario_6_no_tests_collected(tmp_path) -> None:
    from verifyloop.benchmark.manifest import LoadedTask, TaskDefinition

    task_dir = tmp_path / "emptytask"
    (task_dir / "repo" / "tests").mkdir(parents=True)
    (task_dir / "repo" / "app.py").write_text("x = 1\n", encoding="utf-8")
    (task_dir / "eval_tests").mkdir(parents=True)
    (task_dir / "eval_tests" / "test_eval.py").write_text(
        "def test_eval():\n    assert True\n", encoding="utf-8"
    )
    (task_dir / "reference").mkdir(parents=True)
    (task_dir / "reference" / "fix.patch").write_text("", encoding="utf-8")
    definition = TaskDefinition(
        id="emptytask",
        title="empty",
        description="d",
        category="c",
        difficulty="easy",
        expected_behavior="e",
        feedback_command=["python", "-m", "pytest", "tests"],
        eval_command=["python", "-m", "pytest", "eval_tests"],
    )
    loaded = LoadedTask(
        definition=definition,
        task_dir=task_dir,
        repo_dir=task_dir / "repo",
        eval_tests_dir=task_dir / "eval_tests",
        reference_patch_path=task_dir / "reference" / "fix.patch",
        benchmark_version="v1",
        entry_sha256="0" * 64,
    )
    result = make_controller(loaded, [], max_attempts=1).run()
    assert result.outcome is Outcome.INVALID_TASK
    assert result.model_calls == 0


# 7 -------------------------------------------------------------------------
def test_scenario_7_visible_pass_but_eval_fails(task) -> None:
    """A patch that satisfies visible tests but not the hidden evaluation suite."""
    # paging.py fix that passes the visible tests but mishandles iterators,
    # which only the evaluation suite exercises.
    patch = """--- a/paging.py
+++ b/paging.py
@@ -10,6 +10,6 @@
         raise ValueError("page must be >= 1")
     if per_page < 1:
         raise ValueError("per_page must be >= 1")
     start = (page - 1) * per_page
-    end = start + per_page - 1
+    end = start + per_page
     return list(items[start:end])
"""
    result = make_controller(
        task, [MockResponse(text=patch)], strategy="oneshot", max_attempts=1
    ).run()
    assert result.outcome is Outcome.VISIBLE_ONLY_SUCCESS
    assert result.final_report is not None
    assert not result.final_report.all_passed


# 8 -------------------------------------------------------------------------
def test_scenario_8_regression_detected(task, reference_patch) -> None:
    """A patch that fixes the target test but breaks a previously passing one."""
    patch = """--- a/paging.py
+++ b/paging.py
@@ -6,7 +6,7 @@
     if page < 1:
         raise ValueError("page must be >= 1")
     if per_page < 1:
-        raise ValueError("per_page must be >= 1")
+        return []
     start = (page - 1) * per_page
-    end = start + per_page - 1
+    end = start + per_page
     return list(items[start:end])
"""
    result = make_controller(
        task, [MockResponse(text=patch)], strategy="oneshot", max_attempts=1
    ).run()
    # The regression is visible in the feedback suite, so this ends as a test failure
    # or a visible-only success, but never a verified success.
    assert result.outcome is not Outcome.VERIFIED_SUCCESS
    assert result.attempts[0].test_report is not None
    assert not result.attempts[0].test_report.all_passed


# 9 -------------------------------------------------------------------------
def test_scenario_9_provider_timeout(task, reference_patch) -> None:
    result = make_controller(
        task,
        [MockResponse(error=ProviderTimeout, error_message="simulated timeout"),
         MockResponse(text=reference_patch)],
        strategy="evidence_guided",
        max_attempts=2,
    ).run()
    assert result.attempts[0].model_error
    assert "timeout" in result.attempts[0].model_error.lower()
    assert result.outcome is Outcome.VERIFIED_SUCCESS


# 10 ------------------------------------------------------------------------
def test_scenario_10_budget_exhaustion(task, reference_patch) -> None:
    broken = broken_variant(reference_patch)
    result = make_controller(
        task,
        [MockResponse(text=broken) for _ in range(10)],
        strategy="evidence_guided",
        max_attempts=5,
        max_model_calls=2,
    ).run()
    assert result.budget_exhausted
    assert result.model_calls == 2
    # The candidate from the last funded attempt is still evaluated independently.
    assert result.final_report is not None
    assert result.outcome in {Outcome.FAILED_TESTS, Outcome.BUDGET_EXHAUSTED}


# Additional controller invariants -----------------------------------------


def test_blind_retry_gets_no_evidence(task, reference_patch) -> None:
    result = make_controller(
        task,
        [MockResponse(text=broken_variant(reference_patch)),
         MockResponse(text=reference_patch)],
        strategy="blind_retry",
    ).run()
    assert result.outcome is Outcome.VERIFIED_SUCCESS
    assert result.feedback_reports == []


def test_oneshot_never_retries(task, reference_patch) -> None:
    result = make_controller(
        task,
        [MockResponse(text=broken_variant(reference_patch)) for _ in range(5)],
        strategy="oneshot",
        max_attempts=5,
    ).run()
    assert len(result.attempts) == 1
    assert result.model_calls == 1
    # Stopping because one-shot chooses not to retry is not budget exhaustion.
    assert result.budget_exhausted is False


def test_oneshot_does_not_retry_after_provider_error(task) -> None:
    """A provider error must not turn one-shot into a retrying condition."""
    result = make_controller(
        task,
        [MockResponse(error=ProviderTimeout, error_message="simulated timeout"),
         MockResponse(text="this response must never be requested")],
        strategy="oneshot",
        max_attempts=2,
    ).run()
    assert len(result.attempts) == 1
    assert result.model_calls == 1
    assert result.outcome is Outcome.INFRASTRUCTURE_ERROR
    assert "timeout" in result.attempts[0].model_error.lower()


def test_state_log_is_auditable(task, reference_patch) -> None:
    result = make_controller(
        task, [MockResponse(text=reference_patch)], strategy="oneshot"
    ).run()
    states = [event["target"] for event in result.state_log]
    assert states[0] == "BASELINE_CHECK"
    assert "PATCH_VALIDATION" in states
    assert "FEEDBACK_TESTING" in states
    assert "FINAL_EVALUATION" in states
    assert states[-1] == "COMPLETED"


def test_malformed_patch_is_rejected_not_crashed(task) -> None:
    result = make_controller(
        task,
        [MockResponse(text="I'm sorry, I can't do that.")],
        strategy="oneshot",
        max_attempts=1,
    ).run()
    assert result.outcome is Outcome.PATCH_REJECTED
    assert result.attempts[0].failure_category.value == "patch_format"


def test_hidden_tests_never_appear_in_prompts(task, reference_patch) -> None:
    provider = MockProvider(
        responses=[MockResponse(text=broken_variant(reference_patch)),
                   MockResponse(text=reference_patch)],
        model="mock-scripted",
    )
    controller = RepairController(
        provider=provider,
        strategy=get_strategy("evidence_guided"),
        config=ControllerConfig(
            budgets=BudgetConfig(max_attempts=2, test_timeout_seconds=60),
            allowed_commands=["python", "py", "pytest"],
            patch_format="diff",
        ),
        task=task,
    )
    controller.run()
    for call in provider.calls:
        combined = call["system"] + call["user"]
        assert "eval_tests" not in combined
        assert "test_eval_paging" not in combined
        assert "reference/fix.patch" not in combined


def test_diagnostics_track_successful_pipeline(task, reference_patch) -> None:
    result = make_controller(
        task, [MockResponse(text=reference_patch)], strategy="oneshot"
    ).run()
    assert result.outcome is Outcome.VERIFIED_SUCCESS
    attempt = result.attempts[0]
    assert attempt.diagnostics.model_response_received
    assert attempt.diagnostics.patch_format_parsed
    assert attempt.diagnostics.applicability_checked
    assert attempt.diagnostics.applicability_validated
    assert attempt.diagnostics.patch_applied
    assert attempt.diagnostics.tests_collected
    assert attempt.diagnostics.tests_executed
    assert attempt.diagnostics.tests_passed
    assert not attempt.diagnostics.tests_failed
    assert attempt.diagnostics.test_outcome == "passed"
    assert attempt.diagnostics.failure_stage == ""
    summary = result.to_dict()["diagnostics"]
    assert summary["attempts_patch_applied"] == 1
    assert summary["test_reachability"] is True
    assert summary["attempts_with_collection_error"] == 0


def test_diagnostics_track_format_failure(task) -> None:
    result = make_controller(
        task, [MockResponse(text="I cannot produce a patch.")],
        strategy="oneshot", max_attempts=1,
    ).run()
    attempt = result.attempts[0]
    assert attempt.diagnostics.model_response_received
    assert not attempt.diagnostics.patch_format_parsed
    assert attempt.diagnostics.failure_stage == "patch_format"
    assert result.diagnostics_summary()["first_failure_stage"] == "patch_format"


def test_diagnostics_track_application_conflict(task) -> None:
    bad_patch = """--- a/paging.py
+++ b/paging.py
@@ -1,1 +1,1 @@
-this context does not exist anywhere
+replaced
"""
    result = make_controller(
        task, [MockResponse(text=bad_patch)],
        strategy="oneshot", max_attempts=1,
    ).run()
    attempt = result.attempts[0]
    assert attempt.diagnostics.patch_format_parsed
    assert attempt.diagnostics.applicability_validated
    assert not attempt.diagnostics.patch_applied
    assert attempt.diagnostics.failure_stage == "patch_application"


def test_evidence_delivery_is_recorded_for_evidence_condition(
    task, reference_patch
) -> None:
    result = make_controller(
        task,
        [MockResponse(text=broken_variant(reference_patch)),
         MockResponse(text=reference_patch)],
        strategy="evidence_guided",
    ).run()
    first = result.attempts[0]
    assert first.diagnostics.evidence_delivered
    assert first.diagnostics.evidence_kind == "structured"
    assert len(first.diagnostics.evidence_prompt_sha256) == 64
    assert first.diagnostics.evidence_prompt_chars > 0
    assert result.feedback_reports


def test_blind_retry_records_no_evidence_delivery(task, reference_patch) -> None:
    result = make_controller(
        task,
        [MockResponse(text=broken_variant(reference_patch)),
         MockResponse(text=reference_patch)],
        strategy="blind_retry",
    ).run()
    assert not result.attempts[0].diagnostics.evidence_delivered
    assert result.feedback_reports == []


def test_collection_failure_reaches_evidence_prompt(task) -> None:
    syntax_break = (
        '{"file": "paging.py", "search": "    return list(items[start:end])", '
        '"replace": "    return list(items[start:end]"}'
    )
    repair = (
        '{"file": "paging.py", "search": "    end = start + per_page - 1", '
        '"replace": "    end = start + per_page"}'
    )
    result = make_controller(
        task,
        [MockResponse(text=syntax_break), MockResponse(text=repair)],
        strategy="evidence_guided",
        max_attempts=2,
        patch_format="edit_json_single",
    ).run()

    first = result.attempts[0]
    assert first.applied
    assert first.test_report is not None
    assert first.test_report.collection_failed
    assert first.test_report.collection_error_excerpt
    assert first.diagnostics.failure_stage == "test_collection"
    assert first.diagnostics.evidence_delivered
    assert "Collection error" in result.feedback_reports[0]
    assert "SyntaxError" in result.feedback_reports[0]
    assert result.attempts[1].diagnostics.tests_executed
    summary = result.to_dict()["diagnostics"]
    assert summary["attempts_with_collection_error"] == 1
    assert summary["attempts_tests_collected"] == 1
