"""Preflight for a real-model pilot.

Two environment hazards are addressed before an experiment starts:

1. OneDrive on-demand files can be placeholders. The first read can block for
   minutes while the file is hydrated. This script reads every benchmark file
   once, before any model call is billed or timed.
2. A cold Python/pytest environment can make the first baseline test run much
   slower than later runs. This script executes every selected task's visible
   suite once and verifies the expected pre-fix failure.

It does not modify tasks, tests, scoring, or model settings. It exits non-zero
if hydration or a baseline check fails, so a contaminated run is not started.

Usage:
    python scripts/preflight_pilot.py --config config/pilot_ollama.yaml
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from verifyloop.benchmark.manifest import (  # noqa: E402
    load_benchmark,
    resolve_benchmark_root,
)
from verifyloop.config import load_config  # noqa: E402
from verifyloop.execution.policies import pytest_policy, run_test_policy  # noqa: E402
from verifyloop.execution.runner import ExecutionLimits  # noqa: E402
from verifyloop.execution.workspace import create_workspace  # noqa: E402


def hydrate(root: Path) -> None:
    files = sorted(path for path in root.rglob("*") if path.is_file())
    total = 0
    slow: list[tuple[float, Path]] = []
    print(f"hydrating {len(files)} benchmark files under {root}")
    for path in files:
        started = time.monotonic()
        try:
            total += len(path.read_bytes())
        except OSError as exc:
            raise SystemExit(f"cannot read {path}: {exc}") from exc
        elapsed = time.monotonic() - started
        if elapsed > 1.0:
            slow.append((elapsed, path))
    print(f"hydrated {total / 1024:.1f} KiB")
    for elapsed, path in slow:
        print(f"  slow read {elapsed:6.2f}s  {path.relative_to(root)}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config/pilot_ollama.yaml")
    args = parser.parse_args()

    config = load_config(args.config, use_env=True)
    root = resolve_benchmark_root(config.benchmark.root)
    hydrate(root)

    _, tasks = load_benchmark(
        root,
        version=config.benchmark.version,
        task_ids=config.benchmark.task_ids or None,
    )
    feedback = pytest_policy(["tests"], suite="feedback")
    limits = ExecutionLimits(
        timeout_seconds=config.budgets.test_timeout_seconds,
        max_output_bytes=60_000,
    )

    failures = 0
    print(f"checking {len(tasks)} task baselines")
    for task in tasks:
        started = time.monotonic()
        with create_workspace(
            task.repo_dir,
            workspace_root=config.execution.workspace_root,
            keep=False,
        ) as workspace:
            report = run_test_policy(
                feedback,
                workspace.root,
                allowed_commands=config.execution.allowed_commands,
                limits=limits,
            )
        elapsed = time.monotonic() - started
        if report.timed_out or report.infrastructure_error:
            failures += 1
            print(f"FAIL {task.definition.id}: {report.summary_line()} ({elapsed:.1f}s)")
            print(report.stdout[-2000:])
            print(report.stderr[-2000:])
        elif report.total == 0:
            failures += 1
            print(f"FAIL {task.definition.id}: no tests collected")
        elif report.all_passed:
            failures += 1
            print(f"FAIL {task.definition.id}: baseline unexpectedly passes")
        else:
            print(
                f"ok   {task.definition.id}: {report.summary_line()} "
                f"({elapsed:.1f}s wall, {report.duration_seconds:.1f}s test)"
            )

    if failures:
        print(f"preflight failed: {failures}/{len(tasks)} tasks")
        return 1
    print("preflight passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
