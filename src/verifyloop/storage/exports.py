"""Portable exports of experiment results.

JSONL is the archival format (one full result document per line). CSV is the
analysis-friendly flat format. Both are derived only from persisted results.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Sequence

CSV_COLUMNS = [
    "run_id",
    "task_id",
    "strategy",
    "trial",
    "model",
    "provider",
    "benchmark_version",
    "outcome",
    "verified_success",
    "attempt_count",
    "model_calls",
    "prompt_tokens",
    "completion_tokens",
    "total_tokens",
    "generation_seconds",
    "test_seconds",
    "wall_clock_seconds",
    "regression_detected",
    "budget_exhausted",
    "failure_category",
    "visible_only_success",
    "protected_assets_modified",
    "error_message",
]


def _flat_row(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "run_id": result.get("run_id", ""),
        "task_id": result.get("task_id", ""),
        "strategy": result.get("strategy", ""),
        "trial": result.get("trial", 0),
        "model": result.get("model", ""),
        "provider": result.get("provider", ""),
        "benchmark_version": result.get("benchmark_version", ""),
        "outcome": result.get("outcome", ""),
        "verified_success": int(result.get("outcome") == "verified_success"),
        "attempt_count": result.get("attempt_count", 0),
        "model_calls": result.get("model_calls", 0),
        "prompt_tokens": result.get("prompt_tokens", 0),
        "completion_tokens": result.get("completion_tokens", 0),
        "total_tokens": result.get("total_tokens", 0),
        "generation_seconds": result.get("generation_seconds", 0.0),
        "test_seconds": result.get("test_seconds", 0.0),
        "wall_clock_seconds": result.get("wall_clock_seconds", 0.0),
        "regression_detected": int(bool(result.get("regression_detected"))),
        "budget_exhausted": int(bool(result.get("budget_exhausted"))),
        "failure_category": result.get("failure_category", ""),
        "visible_only_success": int(
            result.get("outcome") == "visible_only_success"
        ),
        "protected_assets_modified": int(bool(result.get("protected_assets_modified"))),
        "error_message": result.get("error_message", ""),
    }


def export_jsonl(results: Sequence[dict[str, Any]], path: str | Path) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8", newline="\n") as handle:
        for result in results:
            handle.write(json.dumps(result, sort_keys=True) + "\n")
    return target


def export_csv(results: Sequence[dict[str, Any]], path: str | Path) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for result in results:
            writer.writerow(_flat_row(result))
    return target


def export_summary(summary: dict[str, Any], path: str | Path) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return target


def export_bundle(
    results: Sequence[dict[str, Any]],
    summary: dict[str, Any],
    directory: str | Path,
    *,
    run_id: str,
) -> dict[str, Path]:
    base = Path(directory)
    base.mkdir(parents=True, exist_ok=True)
    return {
        "jsonl": export_jsonl(results, base / f"{run_id}.results.jsonl"),
        "csv": export_csv(results, base / f"{run_id}.results.csv"),
        "summary": export_summary(summary, base / f"{run_id}.summary.json"),
    }
