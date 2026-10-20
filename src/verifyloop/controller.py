"""The repair controller.

One controller instance executes one (task, strategy, trial). It owns:

* the state machine and its audit log,
* budget enforcement (attempts, model calls, tokens, wall clock),
* patch validation and application,
* feedback test execution,
* final independent evaluation on a *fresh* copy of the final candidate,
* regression and protected-asset checks.

Strategies only produce prompts; everything mechanical lives here so all conditions
are compared under identical rules.

Key fairness rule: the independent evaluation never runs inside the agent's
workspace, and its results are never fed back to the model.
"""

from __future__ import annotations

import hashlib
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from verifyloop.benchmark.manifest import LoadedTask, diff_snapshots, snapshot_tree
from verifyloop.config import BudgetConfig, ExperimentConfig
from verifyloop.execution.policies import TestPolicy, pytest_policy, run_test_policy
from verifyloop.execution.result_parser import categorize_failure
from verifyloop.execution.runner import ExecutionLimits
from verifyloop.execution.workspace import Workspace, create_workspace
from verifyloop.feedback.analyzer import build_evidence, passing_test_names
from verifyloop.feedback.formatter import (
    SYSTEM_PROMPT,
    estimate_prompt_tokens,
    format_repository_context,
)
from verifyloop.model_providers.base import ModelProvider, ProviderError
from verifyloop.models import (
    AttemptRecord,
    FailureCategory,
    Outcome,
    TaskResult,
    TestReport,
)
from verifyloop.patching.applier import apply_patch
from verifyloop.patching.parser import PatchParseError, parse_patch
from verifyloop.patching.validator import validate_patch
from verifyloop.state_machine import State, StateMachine
from verifyloop.strategies.base import Strategy, StrategyContext


class BudgetExceeded(RuntimeError):
    """Raised internally when a hard budget is hit."""


@dataclass
class BudgetTracker:
    """Mutable accounting for one task run."""

    limits: BudgetConfig
    started_at: float = field(default_factory=time.monotonic)
    model_calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    attempts: int = 0

    def elapsed(self) -> float:
        return time.monotonic() - self.started_at

    def seconds_remaining(self) -> float:
        return max(0.0, self.limits.max_wall_clock_seconds - self.elapsed())

    def time_exhausted(self) -> bool:
        return self.seconds_remaining() <= 0

    def can_call_model(self) -> bool:
        return (
            self.model_calls < self.limits.max_model_calls
            and self.prompt_tokens + self.completion_tokens < self.limits.max_total_tokens
            and not self.time_exhausted()
        )

    def record_call(
        self, prompt_tokens: Optional[int], completion_tokens: Optional[int]
    ) -> None:
        self.model_calls += 1
        self.prompt_tokens += prompt_tokens or 0
        self.completion_tokens += completion_tokens or 0

    def attempts_remaining(self) -> int:
        return max(0, self.limits.max_attempts - self.attempts)

    def describe(self) -> dict:
        return {
            "model_calls": self.model_calls,
            "max_model_calls": self.limits.max_model_calls,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.prompt_tokens + self.completion_tokens,
            "max_total_tokens": self.limits.max_total_tokens,
            "attempts": self.attempts,
            "max_attempts": self.limits.max_attempts,
            "elapsed_seconds": round(self.elapsed(), 3),
            "max_wall_clock_seconds": self.limits.max_wall_clock_seconds,
        }


@dataclass
class ControllerConfig:
    budgets: BudgetConfig
    allowed_commands: list[str]
    workspace_root: Path | None = None
    keep_workspaces: bool = False
    patch_format: str = "diff"
    protected_patterns: list[str] = field(default_factory=list)


def _limits(budgets: BudgetConfig) -> ExecutionLimits:
    return ExecutionLimits(
        timeout_seconds=budgets.test_timeout_seconds,
        max_output_bytes=budgets.max_output_chars * 4,
    )


class RepairController:
    """Runs one task under one strategy."""

    def __init__(
        self,
        *,
        provider: ModelProvider,
        strategy: Strategy,
        config: ControllerConfig,
        task: LoadedTask,
        trial: int = 0,
        run_id: Optional[str] = None,
    ) -> None:
        self.provider = provider
        self.strategy = strategy
        self.config = config
        self.task = task
        self.trial = trial
        self.run_id = run_id or uuid.uuid4().hex[:12]
        self.machine = StateMachine()
        self.budget = BudgetTracker(limits=config.budgets)
        self.result = TaskResult(
            run_id=self.run_id,
            task_id=task.id,
            strategy=strategy.name,
            model=getattr(provider, "model", "unknown"),
            provider=getattr(provider, "name", "unknown"),
            benchmark_version=task.benchmark_version,
            trial=trial,
            outcome=Outcome.INFRASTRUCTURE_ERROR,
        )
        self._previous_passing: set[str] = set()
        self._final_candidate: dict[str, str] | None = None
        self._final_changed_files: list[str] = []
        self._outcome_decided = False

    # -- public ------------------------------------------------------------

    def run(self) -> TaskResult:
        started = time.monotonic()
        try:
            self._run()
        except Exception as exc:  # noqa: BLE001 - convert to a recorded failure
            self.result.outcome = Outcome.INFRASTRUCTURE_ERROR
            self.result.failure_category = FailureCategory.ENVIRONMENT_ERROR
            self.result.error_message = f"{type(exc).__name__}: {exc}"
            if not self.machine.is_terminal:
                try:
                    self.machine.transition(State.FAILED, reason="unhandled exception")
                except Exception:
                    pass
        finally:
            self.result.wall_clock_seconds = time.monotonic() - started
            self.result.state_log = self.machine.to_dict()["events"]
        return self.result

    # -- internals ---------------------------------------------------------

    def _run(self) -> None:
        feedback_policy = pytest_policy(["tests"], suite="feedback")
        eval_policy = pytest_policy(["eval_tests"], suite="eval")

        self.machine.transition(State.BASELINE_CHECK, reason="start")
        baseline = self._check_baseline(feedback_policy)
        self.result.baseline_report = baseline
        if baseline is None:
            return  # outcome already recorded

        self.machine.transition(State.CONTEXT_READY, reason="baseline valid")

        with create_workspace(
            self.task.repo_dir,
            workspace_root=self.config.workspace_root,
            keep=self.config.keep_workspaces,
        ) as workspace:
            self._execute_loop(workspace, feedback_policy)

        if self._final_candidate is None:
            if self._outcome_decided:
                return  # a specific failure was already recorded
            self.result.outcome = Outcome.PATCH_REJECTED
            self._fail(State.FAILED, reason="no applicable patch")
            return

        self.machine.transition(State.FINAL_EVALUATION, reason="evaluate candidate")
        self._evaluate_final(eval_policy)

    def _check_baseline(self, policy: TestPolicy) -> Optional[TestReport]:
        """Confirm the task is broken before the model is called."""
        with create_workspace(
            self.task.repo_dir,
            workspace_root=self.config.workspace_root,
            keep=self.config.keep_workspaces,
        ) as workspace:
            report = run_test_policy(
                policy,
                workspace.root,
                allowed_commands=self.config.allowed_commands,
                limits=_limits(self.config.budgets),
            )
        if report.infrastructure_error or report.timed_out:
            self.result.outcome = Outcome.INFRASTRUCTURE_ERROR
            self.result.failure_category = FailureCategory.ENVIRONMENT_ERROR
            self.result.error_message = (
                f"baseline execution failed: {report.summary_line()}"
            )
            self.machine.transition(State.INVALID_TASK, reason="baseline infrastructure")
            return None
        if report.total == 0:
            self.result.outcome = Outcome.INVALID_TASK
            self.result.failure_category = FailureCategory.NO_TESTS_COLLECTED
            self.result.error_message = "baseline collected no tests"
            self.machine.transition(State.INVALID_TASK, reason="no baseline tests")
            return None
        if report.all_passed:
            self.result.outcome = Outcome.INVALID_TASK
            self.result.failure_category = FailureCategory.NONE
            self.result.error_message = (
                "baseline already passes; task does not reproduce a defect"
            )
            self.machine.transition(State.INVALID_TASK, reason="baseline passes")
            return None
        return report

    def _execute_loop(self, workspace: Workspace, feedback_policy: TestPolicy) -> None:
        attempt = 1
        context_files = self._read_context_files(workspace)
        repository_context = format_repository_context(context_files)
        prompt = self.strategy.initial_prompt(
            StrategyContext(
                task_description=self.task.definition.description,
                expected_behavior=self.task.definition.expected_behavior,
                repository_context=repository_context,
                patch_format=self.config.patch_format,
                attempt=0,
                max_attempts=self.config.budgets.max_attempts,
            )
        )

        while True:
            if not self.budget.can_call_model():
                self.result.budget_exhausted = True
                self.result.outcome = Outcome.BUDGET_EXHAUSTED
                self._outcome_decided = True
                self._fail(State.BUDGET_EXHAUSTED, reason="budget exhausted before call")
                return

            self.machine.transition(
                State.REPAIR_GENERATION if attempt > 1 else State.PATCH_GENERATION,
                reason=f"attempt {attempt}",
            )
            record = self._generate_and_apply(workspace, prompt, attempt)
            self.result.attempts.append(record)

            if record.model_error:
                self.result.failure_category = FailureCategory.MODEL_ERROR
                # Respect the strategy policy here too: a one-shot run must not
                # retry after a provider error, or the condition is no longer
                # one-shot and its budget accounting becomes incomparable.
                if not self._may_retry(attempt):
                    self.result.outcome = Outcome.INFRASTRUCTURE_ERROR
                    self.result.error_message = record.model_error
                    self._outcome_decided = True
                    self._fail(State.FAILED, reason="model error with no budget left")
                    return
                attempt += 1
                prompt = self.strategy.retry_prompt(
                    StrategyContext(
                        task_description=self.task.definition.description,
                        expected_behavior=self.task.definition.expected_behavior,
                        repository_context=repository_context,
                        patch_format=self.config.patch_format,
                        attempt=attempt - 1,
                        max_attempts=self.config.budgets.max_attempts,
                        rejection_reason=f"provider error: {record.model_error}",
                    )
                )
                continue

            if not record.applied:
                # Patch never reached the test suite.
                self.result.failure_category = record.failure_category
                if not self._may_retry(attempt):
                    self.result.outcome = Outcome.PATCH_REJECTED
                    self.result.error_message = record.rejected_reason
                    self._outcome_decided = True
                    self._fail(State.FAILED, reason="patch rejected; no retries left")
                    return
                attempt += 1
                prompt = self.strategy.retry_prompt(
                    StrategyContext(
                        task_description=self.task.definition.description,
                        expected_behavior=self.task.definition.expected_behavior,
                        repository_context=repository_context,
                        patch_format=self.config.patch_format,
                        attempt=attempt - 1,
                        max_attempts=self.config.budgets.max_attempts,
                        rejection_reason=record.rejected_reason,
                    )
                )
                continue

            # Patch applied: run feedback tests.
            self.machine.transition(State.FEEDBACK_TESTING, reason=f"attempt {attempt}")
            report = run_test_policy(
                feedback_policy,
                workspace.root,
                allowed_commands=self.config.allowed_commands,
                limits=_limits(self.config.budgets),
            )
            record.test_report = report
            self.result.test_seconds += report.duration_seconds

            if report.infrastructure_error:
                self.result.outcome = Outcome.INFRASTRUCTURE_ERROR
                self.result.failure_category = FailureCategory.ENVIRONMENT_ERROR
                self.result.error_message = report.summary_line()
                self._outcome_decided = True
                self._fail(State.FAILED, reason="feedback infrastructure error")
                return

            category = categorize_failure(report)
            record.failure_category = category

            if report.all_passed:
                self._final_candidate = workspace.capture_contents()
                self._final_changed_files = self._changed_source_files(workspace)
                self.result.outcome = Outcome.VISIBLE_ONLY_SUCCESS
                self.result.failure_category = FailureCategory.NONE
                return

            if not self._may_retry(attempt):
                self._final_candidate = workspace.capture_contents()
                self._final_changed_files = self._changed_source_files(workspace)
                self.result.outcome = Outcome.FAILED_TESTS
                self.result.failure_category = category
                # Distinguish "the strategy chose to stop" (one-shot) and "ran out
                # of attempts" from "ran out of budget". Without the strategy
                # check, one-shot would be mislabeled as budget-exhausted merely
                # because its configured attempt ceiling is larger than one.
                if (
                    self._strategy_would_retry(attempt)
                    and attempt < self.config.budgets.max_attempts
                    and not self.budget.can_call_model()
                ):
                    self.result.budget_exhausted = True
                return

            self.machine.transition(State.FAILURE_ANALYSIS, reason=f"attempt {attempt}")
            evidence = build_evidence(
                report,
                attempt=attempt,
                changed_files=record.patch.changed_files if record.patch else [],
                previous_passing=self._previous_passing,
                attempts_remaining=self.budget.attempts_remaining() - 1,
                seconds_remaining=self.budget.seconds_remaining(),
                category=category,
            )
            if evidence.regression_tests:
                self.result.regression_detected = True
            self._previous_passing |= passing_test_names(report)

            prompt = self.strategy.retry_prompt(
                StrategyContext(
                    task_description=self.task.definition.description,
                    expected_behavior=self.task.definition.expected_behavior,
                    repository_context=repository_context,
                    patch_format=self.config.patch_format,
                    attempt=attempt,
                    max_attempts=self.config.budgets.max_attempts,
                    evidence=evidence,
                    test_report=report,
                )
            )
            if self.strategy.uses_evidence:
                self.result.feedback_reports.append(prompt)
            attempt += 1
            workspace.reset()

    def _strategy_would_retry(self, attempt: int) -> bool:
        return self.strategy.should_retry(
            StrategyContext(
                task_description="",
                expected_behavior="",
                repository_context="",
                patch_format=self.config.patch_format,
                attempt=attempt,
                max_attempts=self.config.budgets.max_attempts,
            )
        )

    def _may_retry(self, attempt: int) -> bool:
        if not self._strategy_would_retry(attempt):
            return False
        return attempt < self.config.budgets.max_attempts and self.budget.can_call_model()

    def _generate_and_apply(
        self, workspace: Workspace, prompt: str, attempt: int
    ) -> AttemptRecord:
        record = AttemptRecord(
            attempt=attempt, model_call_index=self.budget.model_calls + 1
        )
        started = time.monotonic()
        try:
            completion = self.provider.complete(
                SYSTEM_PROMPT,
                prompt,
                max_output_tokens=self.config.budgets.max_output_chars // 4,
            )
        except ProviderError as exc:
            record.model_error = str(exc)
            record.generation_seconds = time.monotonic() - started
            self.budget.record_call(
                estimate_prompt_tokens(prompt), 0
            )
            self.result.model_calls += 1
            self.result.prompt_tokens += estimate_prompt_tokens(prompt)
            return record

        record.generation_seconds = time.monotonic() - started
        record.raw_output = completion.text[: self.config.budgets.max_output_chars]
        prompt_tokens = (
            completion.prompt_tokens
            if completion.prompt_tokens is not None
            else estimate_prompt_tokens(SYSTEM_PROMPT + prompt)
        )
        completion_tokens = (
            completion.completion_tokens
            if completion.completion_tokens is not None
            else estimate_prompt_tokens(completion.text)
        )
        record.prompt_tokens = prompt_tokens
        record.completion_tokens = completion_tokens
        self.budget.record_call(prompt_tokens, completion_tokens)
        self.result.model_calls += 1
        self.result.prompt_tokens += prompt_tokens
        self.result.completion_tokens += completion_tokens
        self.result.generation_seconds += record.generation_seconds

        try:
            candidate, parsed = parse_patch(completion.text, self.config.patch_format)
        except PatchParseError as exc:
            record.rejected_reason = str(exc)
            record.failure_category = exc.category
            return record

        record.patch = candidate
        validation = validate_patch(
            parsed,
            workspace.root,
            protected_patterns=self.config.protected_patterns,
            max_patch_bytes=self.config.budgets.max_patch_bytes,
            raw_size_bytes=candidate.size_bytes,
        )
        record.validation = validation
        if not validation.ok:
            record.rejected_reason = validation.reason
            record.failure_category = validation.category
            return record

        self.machine.transition(State.PATCH_VALIDATION, reason=f"attempt {attempt}")
        before = workspace.snapshot()
        apply_result = apply_patch(parsed, workspace.root)
        if not apply_result.ok:
            record.rejected_reason = apply_result.reason
            record.failure_category = apply_result.category
            workspace.reset()
            return record

        after = workspace.snapshot()
        changes = diff_snapshots(before, after)
        record.applied = True
        record.patch.changed_files = sorted(
            changes["added"] + changes["modified"]
        )
        return record

    def _read_context_files(self, workspace: Workspace) -> dict[str, str]:
        """Source files exposed to the model: never tests or hidden assets."""
        files: dict[str, str] = {}
        for relative in workspace.list_source_files():
            try:
                files[relative] = workspace.read_file(relative)
            except (OSError, UnicodeDecodeError):
                continue
        return files

    def _changed_source_files(self, workspace: Workspace) -> list[str]:
        changes = workspace.changed_since_baseline()
        return sorted(changes["added"] + changes["modified"])

    def _evaluate_final(self, policy: TestPolicy) -> None:
        """Run hidden evaluation tests on a fresh copy of the final candidate."""
        assert self._final_candidate is not None
        with create_workspace(
            self.task.repo_dir,
            workspace_root=self.config.workspace_root,
            keep=self.config.keep_workspaces,
        ) as eval_workspace:
            # Restore only the candidate's source changes onto a pristine tree.
            candidate_hashes = {
                path: hashlib.sha256(content.encode("utf-8")).hexdigest()
                for path, content in self._final_candidate.items()
            }
            changes = diff_snapshots(eval_workspace.baseline_snapshot, candidate_hashes)
            for relative in changes["removed"]:
                target = eval_workspace.root / relative
                if target.is_file():
                    target.unlink()
            for relative in changes["added"] + changes["modified"]:
                content = self._final_candidate.get(relative)
                if content is None:
                    continue
                eval_workspace.write_file(relative, content)

            # Protected assets must be byte-identical to the pristine snapshot.
            tampered = [
                path
                for path in changes["modified"] + changes["removed"]
                if path.startswith(("tests/", "eval_tests/", "reference/"))
                or path in {"conftest.py", "task.json", "manifest.json"}
            ]
            self.result.protected_assets_modified = bool(tampered)

            eval_dir = eval_workspace.root / "eval_tests"
            for name, content in self.task.read_eval_tests():
                target = eval_dir / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8", newline="\n")

            report = run_test_policy(
                policy,
                eval_workspace.root,
                allowed_commands=self.config.allowed_commands,
                limits=_limits(self.config.budgets),
            )
            self.result.final_report = report
            self.result.test_seconds += report.duration_seconds

        if report.infrastructure_error:
            self.result.outcome = Outcome.INFRASTRUCTURE_ERROR
            self.result.failure_category = FailureCategory.ENVIRONMENT_ERROR
            self.result.error_message = report.summary_line()
            self._fail(State.FAILED, reason="evaluation infrastructure error")
            return

        if self.result.protected_assets_modified:
            self.result.outcome = Outcome.FAILED_TESTS
            self.result.failure_category = FailureCategory.PATCH_PATH
            self.result.error_message = "protected evaluation assets were modified"
            self._fail(State.FAILED, reason="protected asset modified")
            return

        if report.all_passed and self.result.outcome is not Outcome.INFRASTRUCTURE_ERROR:
            self.result.outcome = Outcome.VERIFIED_SUCCESS
            self.result.failure_category = FailureCategory.NONE
            self.machine.transition(State.COMPLETED, reason="verified success")
            return

        if report.total == 0:
            self.result.failure_category = FailureCategory.NO_TESTS_COLLECTED
            self.result.outcome = Outcome.FAILED_TESTS
        elif self.result.outcome is Outcome.VISIBLE_ONLY_SUCCESS:
            # Visible tests passed but independent evaluation did not.
            self.result.failure_category = categorize_failure(report)
            self.result.outcome = Outcome.VISIBLE_ONLY_SUCCESS
        else:
            self.result.failure_category = categorize_failure(report)
            self.result.outcome = Outcome.FAILED_TESTS
        self._fail(State.FAILED, reason="independent evaluation failed")

    def _fail(self, state: State, *, reason: str) -> None:
        if not self.machine.is_terminal:
            self.machine.transition(state, reason=reason)
