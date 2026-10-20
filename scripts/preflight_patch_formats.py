"""Run the patch-format / test-reachability preflight.

This script is deliberately separate from the strategy comparison. It runs the
same audited tasks under one one-shot attempt and changes only the requested patch
representation. It records whether the patch parsed, validated, applied, whether
pytest collected/executed tests, and whether a collection error was captured.

The stop rule is declared in ``docs/preflight/protocol_proposal.md``:

* at least two of three patches apply;
* at least two of three attempts execute a non-empty test suite;
* no infrastructure errors.

A format that does not meet the rule is not used for a later strategy comparison.
The script never launches a strategy comparison itself.

Usage:
    python scripts/preflight_patch_formats.py \
        --config config/preflight_patch_formats.yaml

The default formats are the existing ``edit_json`` representation and the stricter
``edit_json_single`` representation. Every run receives a new run ID; no previous
pilot artifact is overwritten.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from verifyloop.config import ExperimentConfig, load_config  # noqa: E402
from verifyloop.evaluation.evaluator import ExperimentRunner, RunnerHooks  # noqa: E402
from verifyloop.evaluation.metrics import build_summary  # noqa: E402
from verifyloop.storage.database import ExperimentStore  # noqa: E402
from verifyloop.storage.exports import export_bundle, export_summary  # noqa: E402


def _attempt_diagnostics(result: dict[str, Any]) -> dict[str, Any]:
    """Read attempt diagnostics, tolerating an older record shape."""
    diagnostics = result.get("diagnostics")
    if isinstance(diagnostics, dict):
        return diagnostics
    attempts = result.get("attempts") or []
    return {
        "attempts_with_model_response": sum(
            not bool(attempt.get("model_error")) for attempt in attempts
        ),
        "attempts_patch_format_parsed": sum(
            bool(attempt.get("patch")) for attempt in attempts
        ),
        "attempts_applicability_validated": sum(
            bool((attempt.get("validation") or {}).get("ok")) for attempt in attempts
        ),
        "attempts_patch_applied": sum(
            bool(attempt.get("applied")) for attempt in attempts
        ),
        "attempts_tests_collected": sum(
            bool((attempt.get("test_report") or {}).get("total"))
            for attempt in attempts
        ),
        "attempts_tests_executed": sum(
            bool((attempt.get("test_report") or {}).get("total"))
            for attempt in attempts
        ),
        "attempts_tests_passed": sum(
            bool((attempt.get("test_report") or {}).get("all_passed"))
            for attempt in attempts
        ),
        "attempts_tests_failed": sum(
            bool(
                (attempt.get("test_report") or {}).get("total")
                and not (attempt.get("test_report") or {}).get("all_passed")
            )
            for attempt in attempts
        ),
        "attempts_evidence_delivered": 0,
        "attempts_with_collection_error": sum(
            bool((attempt.get("test_report") or {}).get("collection_error_excerpt"))
            for attempt in attempts
        ),
        "test_reachability": any(
            bool((attempt.get("test_report") or {}).get("total"))
            for attempt in attempts
        ),
        "first_failure_stage": "",
    }


def _task_row(result: dict[str, Any]) -> dict[str, Any]:
    diag = _attempt_diagnostics(result)
    attempts = result.get("attempts") or []
    collection_excerpt = ""
    for attempt in attempts:
        excerpt = (attempt.get("test_report") or {}).get(
            "collection_error_excerpt", ""
        )
        if excerpt:
            collection_excerpt = excerpt
            break
    return {
        "task_id": result.get("task_id", ""),
        "outcome": result.get("outcome", ""),
        "attempt_count": result.get("attempt_count", 0),
        "model_response_received": bool(diag.get("attempts_with_model_response")),
        "format_parsed": bool(diag.get("attempts_patch_format_parsed")),
        "applicability_validated": bool(
            diag.get("attempts_applicability_validated")
        ),
        "patch_applied": bool(diag.get("attempts_patch_applied")),
        "tests_collected": bool(diag.get("attempts_tests_collected")),
        "tests_executed": bool(diag.get("attempts_tests_executed")),
        "tests_passed": bool(diag.get("attempts_tests_passed")),
        "tests_failed": bool(diag.get("attempts_tests_failed")),
        "evidence_delivered": bool(diag.get("attempts_evidence_delivered")),
        "collection_error_captured": bool(collection_excerpt),
        "collection_error_excerpt": collection_excerpt,
        "first_failure_stage": diag.get("first_failure_stage", ""),
        "test_reachability": bool(diag.get("test_reachability")),
        "attempts": [
            {
                "attempt": attempt.get("attempt"),
                "failure_stage": (attempt.get("diagnostics") or {}).get(
                    "failure_stage", ""
                ),
                "test_outcome": (attempt.get("diagnostics") or {}).get(
                    "test_outcome", ""
                ),
                "applied": attempt.get("applied"),
                "failure_category": attempt.get("failure_category"),
                "rejected_reason": attempt.get("rejected_reason", ""),
                "collection_error_excerpt": (
                    attempt.get("test_report") or {}
                ).get("collection_error_excerpt", ""),
            }
            for attempt in attempts
        ],
        "model_calls": result.get("model_calls", 0),
        "total_tokens": result.get("total_tokens", 0),
        "generation_seconds": result.get("generation_seconds", 0.0),
        "test_seconds": result.get("test_seconds", 0.0),
        "wall_clock_seconds": result.get("wall_clock_seconds", 0.0),
        "error_message": result.get("error_message", ""),
    }


def _format_summary(
    fmt: str,
    run_id: str,
    manifest_path: str,
    results: list[dict[str, Any]],
    *,
    task_count: int,
) -> dict[str, Any]:
    rows = [_task_row(result) for result in results]
    applied = sum(row["patch_applied"] for row in rows)
    executed = sum(row["tests_executed"] for row in rows)
    parsed = sum(row["format_parsed"] for row in rows)
    infra = sum(row["outcome"] == "infrastructure_error" for row in rows)
    ready = applied >= 2 and executed >= 2 and infra == 0
    return {
        "format": fmt,
        "run_id": run_id,
        "manifest_path": manifest_path,
        "task_count": task_count,
        "parsed": parsed,
        "applied": applied,
        "tests_executed": executed,
        "infrastructure_errors": infra,
        "preflight_ready": ready,
        "tasks": rows,
    }


def _print_format_table(summary: dict[str, Any]) -> None:
    print()
    print(f"## format: {summary['format']}  ({summary['run_id']})")
    print(
        f"parsed={summary['parsed']}/{summary['task_count']}  "
        f"applied={summary['applied']}/{summary['task_count']}  "
        f"tests_executed={summary['tests_executed']}/{summary['task_count']}  "
        f"infrastructure_errors={summary['infrastructure_errors']}  "
        f"ready={summary['preflight_ready']}"
    )
    print()
    print("| task | outcome | parsed | applied | collected | executed | passed | failed | collection excerpt | stage |")
    print("|---|---|---:|---:|---:|---:|---:|---:|---:|---|")
    for row in summary["tasks"]:
        print(
            "| {task_id} | {outcome} | {format_parsed} | {patch_applied} | "
            "{tests_collected} | {tests_executed} | {tests_passed} | "
            "{tests_failed} | {collection_error_captured} | "
            "{first_failure_stage} |".format(**row)
        )


def _run_format(
    base_config: ExperimentConfig,
    fmt: str,
    output_dir: Path,
    store: ExperimentStore,
) -> dict[str, Any]:
    config = base_config.model_copy(
        update={
            "name": f"{base_config.name}-{fmt}",
            "patch_format": fmt,
            "strategies": ["oneshot"],
            "trials": 1,
            "output_dir": str(output_dir),
        }
    )

    def on_start(run_id: str, total: int) -> None:
        print(f"run {run_id}: {total} task run(s), format={fmt}")

    def on_task(task_id: str, strategy: str, trial: int) -> None:
        print(f"  {task_id} :: {strategy} ... ", end="", flush=True)

    def on_done(result: Any) -> None:
        print(
            f"{result.outcome.value} "
            f"(attempts={len(result.attempts)}, calls={result.model_calls}, "
            f"{result.wall_clock_seconds:.1f}s)"
        )

    runner = ExperimentRunner(
        config,
        store=store,
        output_dir=output_dir,
        hooks=RunnerHooks(
            on_run_start=on_start,
            on_task_start=on_task,
            on_task_complete=on_done,
        ),
    )
    outcome = runner.run()
    results = store.load_results(outcome.run_id)
    export_bundle(
        results,
        build_summary(results),
        output_dir / "exports",
        run_id=outcome.run_id,
    )
    return _format_summary(
        fmt,
        outcome.run_id,
        str(outcome.manifest_path),
        results,
        task_count=len(base_config.benchmark.task_ids),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--config", default="config/preflight_patch_formats.yaml"
    )
    parser.add_argument(
        "--formats",
        nargs="+",
        default=["edit_json", "edit_json_single"],
        choices=["diff", "edit_json", "edit_json_single"],
    )
    parser.add_argument("--output", default=None)
    parser.add_argument(
        "--allow-mock",
        action="store_true",
        help="allow the mock provider (pipeline demonstration only)",
    )
    args = parser.parse_args(argv)

    config = load_config(args.config, use_env=True)
    if config.provider.provider == "mock" and not args.allow_mock:
        print(
            "Refusing to preflight with the mock provider: this produces no evidence "
            "about a real model. Use --allow-mock only for a pipeline check.",
            file=sys.stderr,
        )
        return 2
    if not config.benchmark.task_ids:
        print(
            "Preflight config must explicitly list task_ids; refusing to run all tasks.",
            file=sys.stderr,
        )
        return 2

    output_dir = Path(args.output or config.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    store = ExperimentStore(output_dir / "preflight.db")

    print(f"preflight config: {args.config}")
    print(
        f"provider={config.provider.provider} model={config.provider.model} "
        f"tasks={len(config.benchmark.task_ids)} formats={', '.join(args.formats)}"
    )
    print("This is a format/reachability preflight, not a strategy comparison.")

    summaries = []
    for fmt in args.formats:
        summaries.append(_run_format(config, fmt, output_dir, store))
        _print_format_table(summaries[-1])

    ready = [summary["format"] for summary in summaries if summary["preflight_ready"]]
    decision = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "config": str(args.config),
        "preflight_ready": bool(ready),
        "ready_formats": ready,
        "stop_rule": (
            "A format is ready only if >=2/3 patches apply, >=2/3 attempts execute "
            "a non-empty test suite, and there are no infrastructure errors."
        ),
        "formats": summaries,
    }
    summary_path = output_dir / "preflight_summary.json"
    export_summary(decision, summary_path)
    print()
    print(f"preflight ready formats: {', '.join(ready) if ready else 'none'}")
    print(f"combined summary: {summary_path}")
    if not ready:
        print(
            "STOP: no format met the pre-declared reachability rule. Do not launch "
            "the strategy comparison."
        )
        return 1
    print(
        "Preflight passed for at least one format. Freeze the protocol and select "
        "the representation before any strategy comparison; do not change formats "
        "mid-comparison."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
