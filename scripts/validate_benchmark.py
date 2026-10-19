"""Validate every benchmark task against its own contract.

For each task this script proves four properties mechanically:

1. The visible feedback tests **fail** on the shipped buggy repository.
2. The reference fix applies cleanly to the buggy repository.
3. With the reference fix applied, the visible tests **pass**.
4. With the reference fix applied, the hidden evaluation tests **pass**.

It also confirms that evaluation tests are absent from the repository snapshot, so
they cannot leak into the model's context.

This is the gate that must pass before any experiment is run. A task that fails any
check is reported and the script exits non-zero.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from verifyloop.benchmark.manifest import LoadedTask, load_benchmark  # noqa: E402
from verifyloop.config import load_default_config  # noqa: E402
from verifyloop.execution.policies import pytest_policy, run_test_policy  # noqa: E402
from verifyloop.execution.runner import ExecutionLimits  # noqa: E402
from verifyloop.execution.workspace import create_workspace  # noqa: E402
from verifyloop.patching.applier import apply_patch  # noqa: E402
from verifyloop.patching.parser import parse_patch  # noqa: E402


def check_task(task: LoadedTask, allowed_commands: list[str], timeout: float) -> list[str]:
    problems: list[str] = []
    limits = ExecutionLimits(timeout_seconds=timeout, max_output_bytes=40_000)
    feedback = pytest_policy(["tests"], suite="feedback")
    evaluation = pytest_policy(["eval_tests"], suite="eval")

    with create_workspace(task.repo_dir) as workspace:
        # 1. Baseline must fail.
        baseline = run_test_policy(
            feedback, workspace.root, allowed_commands=allowed_commands, limits=limits
        )
        if baseline.infrastructure_error:
            problems.append(f"baseline infrastructure error: {baseline.summary_line()}")
        elif baseline.total == 0:
            problems.append("baseline collected no tests")
        elif baseline.all_passed:
            problems.append("baseline passes; the defect does not reproduce")

        # 2. Reference fix must apply.
        candidate, parsed = parse_patch(task.read_reference_patch(), "diff")
        result = apply_patch(parsed, workspace.root)
        if not result.ok:
            problems.append(f"reference fix failed to apply: {result.reason}")
            return problems

        # 3. Visible tests must pass after the fix.
        fixed = run_test_policy(
            feedback, workspace.root, allowed_commands=allowed_commands, limits=limits
        )
        if not fixed.all_passed:
            problems.append(f"visible tests still fail after fix: {fixed.summary_line()}")

        # 4. Hidden evaluation tests must pass after the fix.
        eval_dir = workspace.root / "eval_tests"
        for name, content in task.read_eval_tests():
            target = eval_dir / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8", newline="\n")
        evaluated = run_test_policy(
            evaluation, workspace.root, allowed_commands=allowed_commands, limits=limits
        )
        if not evaluated.all_passed:
            problems.append(
                f"evaluation tests fail after reference fix: {evaluated.summary_line()}"
            )
            for case in evaluated.failing_cases()[:3]:
                problems.append(f"    {case.name}: {case.message[:200]}")

    # Leakage check: evaluation tests must not exist in the shipped repo.
    leaked = list(task.repo_dir.rglob("test_eval_*.py"))
    if leaked:
        problems.append(f"evaluation tests leaked into repo: {leaked}")
    if (task.repo_dir / "reference").exists():
        problems.append("reference directory leaked into repo snapshot")

    return problems


def main(argv: list[str]) -> int:
    config = load_default_config(use_env=False)
    _, tasks = load_benchmark(
        REPO_ROOT / config.benchmark.root,
        version=config.benchmark.version,
        task_ids=config.benchmark.task_ids or None,
    )
    print(f"validating {len(tasks)} tasks (benchmark {config.benchmark.version})")
    failures = 0
    for task in tasks:
        problems = check_task(
            task,
            config.execution.allowed_commands,
            config.budgets.test_timeout_seconds,
        )
        if problems:
            failures += 1
            print(f"FAIL {task.id}")
            for problem in problems:
                print(f"     {problem}")
        else:
            print(f"ok   {task.id}  [{task.category}/{task.difficulty}]")
    print()
    if failures:
        print(f"{failures}/{len(tasks)} tasks failed validation")
        return 1
    print(f"all {len(tasks)} tasks validated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
