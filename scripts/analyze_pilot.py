"""Summarize VerifyLoop pilot JSONL exports.

Usage:
    python scripts/analyze_pilot.py \
        outputs/exports/run-A.results.jsonl \
        outputs/exports/run-B.results.jsonl \
        --exclude-task exception_json_005

The analysis is descriptive. It deliberately does not compute p-values: at this
sample size, and with repeated runs of the same model, inferential statistics
would be misleading.
"""

from __future__ import annotations

import argparse
import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable


def load_rows(paths: Iterable[Path]) -> list[dict]:
    rows: list[dict] = []
    for path in paths:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))
    return rows


def valid(row: dict) -> bool:
    return row["outcome"] not in {"infrastructure_error", "invalid_task"}


def mean(values: list[float]) -> float:
    return statistics.fmean(values) if values else 0.0


def median(values: list[float]) -> float:
    return statistics.median(values) if values else 0.0


def strategy_table(rows: list[dict]) -> str:
    order = ["oneshot", "blind_retry", "evidence_guided"]
    lines = [
        "| strategy | cells | valid | verified | failed_tests | patch_rejected | infra | budget_exh | mean attempts | mean wall s | median wall s | mean gen s | mean test s | mean tokens |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for name in order:
        cells = [row for row in rows if row["strategy"] == name]
        good = [row for row in cells if valid(row)]
        lines.append(
            "| {name} | {cells} | {valid} | {verified} | {failed} | {rejected} | "
            "{infra} | {budget} | {attempts:.2f} | {wall:.1f} | {median_wall:.1f} | "
            "{gen:.1f} | {test:.1f} | {tokens:.0f} |".format(
                name=name,
                cells=len(cells),
                valid=len(good),
                verified=sum(row["outcome"] == "verified_success" for row in cells),
                failed=sum(row["outcome"] == "failed_tests" for row in cells),
                rejected=sum(row["outcome"] == "patch_rejected" for row in cells),
                infra=sum(row["outcome"] == "infrastructure_error" for row in cells),
                budget=sum(bool(row["budget_exhausted"]) for row in cells),
                attempts=mean([row["attempt_count"] for row in good]),
                wall=mean([row["wall_clock_seconds"] for row in good]),
                median_wall=median([row["wall_clock_seconds"] for row in good]),
                gen=mean([row["generation_seconds"] for row in good]),
                test=mean([row["test_seconds"] for row in good]),
                tokens=mean([row["total_tokens"] for row in good]),
            )
        )
    return "\n".join(lines)


def task_table(rows: list[dict]) -> str:
    tasks = sorted({row["task_id"] for row in rows})
    strategies = ["oneshot", "blind_retry", "evidence_guided"]
    lines = [
        "| task | " + " | ".join(strategies) + " |",
        "|---|" + "---|" * len(strategies),
    ]
    for task in tasks:
        values = []
        for strategy in strategies:
            cell_rows = [
                row
                for row in rows
                if row["task_id"] == task and row["strategy"] == strategy
            ]
            if not cell_rows:
                values.append("-")
            elif len(cell_rows) == 1:
                values.append(cell_rows[0]["outcome"])
            else:
                counts = Counter(row["outcome"] for row in cell_rows)
                values.append(
                    ", ".join(
                        f"{outcome} x{count}" for outcome, count in sorted(counts.items())
                    )
                )
        lines.append(f"| {task} | " + " | ".join(values) + " |")
    return "\n".join(lines)


def applicability_table(rows: list[dict]) -> str:
    lines = [
        "| strategy | cells with an attempt | first attempt applied | first attempt rejected | cells with any test report | evidence prompts recorded |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for name in ["oneshot", "blind_retry", "evidence_guided"]:
        cells = [row for row in rows if row["strategy"] == name and row["attempts"]]
        applied = sum(bool(row["attempts"][0].get("applied")) for row in cells)
        any_test = sum(
            any(attempt.get("test_report") for attempt in row["attempts"])
            for row in cells
        )
        lines.append(
            f"| {name} | {len(cells)} | {applied} | {len(cells) - applied} | "
            f"{any_test} | {sum(bool(row['feedback_reports']) for row in cells)} |"
        )
    return "\n".join(lines)


def categories(rows: list[dict]) -> str:
    good = [row for row in rows if valid(row)]
    counts = Counter(row["failure_category"] for row in good)
    return ", ".join(f"`{name}`={count}" for name, count in sorted(counts.items()))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("jsonl", nargs="+", type=Path)
    parser.add_argument(
        "--exclude-task",
        action="append",
        default=[],
        help="task id to exclude from the analyzed tables (repeatable)",
    )
    args = parser.parse_args()

    rows = load_rows(args.jsonl)
    excluded = set(args.exclude_task)
    analyzed = [row for row in rows if row["task_id"] not in excluded]

    print("# VerifyLoop pilot analysis")
    print()
    print("Run files:")
    for path in args.jsonl:
        print(f"- `{path.as_posix()}`")
    print()
    if excluded:
        print(f"Excluded tasks: {', '.join(sorted(excluded))}")
        print()
    print(f"Total recorded cells: {len(rows)}")
    print(f"Analyzed cells: {len(analyzed)} (excluding {len(rows) - len(analyzed)})")
    print()

    for run_id in sorted({row["run_id"] for row in rows}):
        run_rows = [row for row in analyzed if row["run_id"] == run_id]
        if not run_rows:
            continue
        print(f"## {run_id}")
        print()
        print(
            f"provider `{run_rows[0]['provider']}`, model `{run_rows[0]['model']}`, "
            f"benchmark `{run_rows[0]['benchmark_version']}`"
        )
        print()
        print("### Outcomes")
        print()
        print(strategy_table(run_rows))
        print()
        print("### Task by strategy")
        print()
        print(task_table(run_rows))
        print()
        print("### Patch applicability and evidence delivery")
        print()
        print(applicability_table(run_rows))
        print()
        print(f"### Failure categories (valid cells)\n\n{categories(run_rows)}")
        print()

    print("## Combined analyzed cells")
    print()
    print(strategy_table(analyzed))
    print()
    print("### Combined task by strategy")
    print()
    print(task_table(analyzed))
    print()
    print("### Combined patch applicability and evidence delivery")
    print()
    print(applicability_table(analyzed))
    print()
    print(f"### Combined failure categories (valid cells)\n\n{categories(analyzed)}")
    print()
    print("> Descriptive only. Runs reuse the same model and tasks; cells are not")
    print("> independent trials. No significance test is reported or implied.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
