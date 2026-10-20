"""VerifyLoop command-line interface.

Commands:
    doctor          inspect the environment and provider configuration
    provider-check  verify connectivity, model presence, and a real generation
    list-tasks      list benchmark tasks
    validate-bench  verify every task's contract
    smoke-test      run the full pipeline with the mock provider
    run             execute an experiment from a configuration file
    export          export persisted results to JSONL/CSV/summary
    report          print a results report from persisted data
    ui              launch the Streamlit dashboard
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Optional, Sequence

from verifyloop import __version__
from verifyloop.benchmark.manifest import BenchmarkError, load_benchmark, resolve_benchmark_root
from verifyloop.config import (
    STRATEGY_NAMES,
    ExperimentConfig,
    load_config,
    load_default_config,
)
from verifyloop.evaluation.metrics import build_summary
from verifyloop.storage.database import ExperimentStore
from verifyloop.storage.exports import export_bundle


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _default_db(config: ExperimentConfig) -> Path:
    override = os.environ.get("VERIFYLOOP_DB")
    if override:
        return Path(override)
    return _repo_root() / config.output_dir / "verifyloop.db"


# ---------------------------------------------------------------------------
# doctor
# ---------------------------------------------------------------------------


def cmd_doctor(args: argparse.Namespace) -> int:
    config = load_default_config(args.config, use_env=True)
    print(f"VerifyLoop {__version__}")
    print(f"repository: {_repo_root()}")
    print()
    print("## Runtime")
    print(f"python: {sys.version.split()[0]} ({sys.executable})")
    print(f"platform: {platform.platform()}")
    print(f"machine: {platform.machine()}")
    print(f"git: {_which('git') or 'NOT FOUND'}")
    print()
    print("## Provider configuration (no secrets shown)")
    for key, value in config.provider.describe().items():
        print(f"{key}: {value}")
    print()
    print("## Benchmark")
    root = resolve_benchmark_root(config.benchmark.root)
    try:
        manifest, tasks = load_benchmark(
            root, version=config.benchmark.version, task_ids=config.benchmark.task_ids or None
        )
        print(f"manifest: {root / 'manifest.json'}")
        print(f"version: {manifest.version}")
        print(f"tasks: {len(tasks)}")
        categories = sorted({task.category for task in tasks})
        print(f"categories: {', '.join(categories)}")
    except BenchmarkError as exc:
        print(f"BENCHMARK ERROR: {exc}")
        return 1
    print()
    print("## Storage")
    db_path = _default_db(config)
    print(f"database: {db_path}")
    try:
        store = ExperimentStore(db_path)
        stats = store.stats()
        print(f"runs recorded: {stats['runs']}")
        print(f"task results recorded: {stats['results']}")
    except Exception as exc:  # noqa: BLE001
        print(f"database unavailable: {exc}")
    print()
    print("## Provider health")
    if config.provider.provider == "mock":
        print("mock provider: always available (offline)")
    else:
        from verifyloop.model_providers import build_provider

        try:
            provider = build_provider(config.provider)
            ok, message = provider.health_check()
            print(f"{config.provider.provider}: {'OK' if ok else 'UNAVAILABLE'} - {message}")
        except Exception as exc:  # noqa: BLE001
            print(f"{config.provider.provider}: ERROR - {exc}")
    return 0


def _which(command: str) -> Optional[str]:
    return shutil.which(command)


# ---------------------------------------------------------------------------
# provider-check
# ---------------------------------------------------------------------------


def cmd_provider_check(args: argparse.Namespace) -> int:
    """Verify a real provider end-to-end, not just that its HTTP port is open."""
    config = load_default_config(args.config, use_env=True)
    provider_config = config.provider
    if args.timeout is not None:
        provider_config = provider_config.model_copy(
            update={"request_timeout_seconds": args.timeout}
        )

    print("VerifyLoop provider check")
    print(f"configuration: {args.config or '(defaults + environment)'}")
    print()

    if provider_config.provider == "mock":
        print(
            "provider is 'mock': always available, no network or model required.\n"
            "To check a real backend, set MODEL_PROVIDER=ollama and "
            "MODEL_NAME=<model>, or use --config config/local_ollama.yaml."
        )
        return 0

    from verifyloop.model_providers import build_provider
    from verifyloop.model_providers.base import ProviderError
    from verifyloop.model_providers.diagnostics import diagnose_provider

    try:
        provider = build_provider(provider_config)
    except ProviderError as exc:
        print(f"configuration error: {exc}")
        return 2

    report = diagnose_provider(provider)
    print(report.render())
    return 0 if report.ok else 1


# ---------------------------------------------------------------------------
# list-tasks / validate
# ---------------------------------------------------------------------------


def cmd_list_tasks(args: argparse.Namespace) -> int:
    config = load_default_config(args.config, use_env=False)
    root = resolve_benchmark_root(config.benchmark.root)
    try:
        manifest, tasks = load_benchmark(root, version=config.benchmark.version)
    except BenchmarkError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(
            [
                {
                    "id": task.id,
                    "title": task.title,
                    "category": task.category,
                    "difficulty": task.difficulty,
                }
                for task in tasks
            ],
            indent=2,
        ))
        return 0
    print(f"benchmark {manifest.name} {manifest.version}: {len(tasks)} tasks")
    print()
    print(f"{'id':<26} {'category':<20} {'difficulty':<10} title")
    print("-" * 100)
    for task in tasks:
        print(f"{task.id:<26} {task.category:<20} {task.difficulty:<10} {task.title}")
    return 0


def cmd_validate_bench(args: argparse.Namespace) -> int:
    script = _repo_root() / "scripts" / "validate_benchmark.py"
    return subprocess.call([sys.executable, str(script)])


# ---------------------------------------------------------------------------
# smoke test
# ---------------------------------------------------------------------------


def cmd_smoke_test(args: argparse.Namespace) -> int:
    script = _repo_root() / "scripts" / "run_smoke_test.py"
    return subprocess.call([sys.executable, str(script)])


# ---------------------------------------------------------------------------
# run
# ---------------------------------------------------------------------------


def cmd_run(args: argparse.Namespace) -> int:
    config = load_config(args.config, use_env=True)
    if args.strategies:
        config = config.model_copy(update={"strategies": args.strategies})
    if args.trials is not None:
        config = config.model_copy(update={"trials": args.trials})
    if args.max_attempts is not None:
        budgets = config.budgets.model_copy(update={"max_attempts": args.max_attempts})
        config = config.model_copy(update={"budgets": budgets})
    if args.task_ids:
        benchmark = config.benchmark.model_copy(update={"task_ids": args.task_ids})
        config = config.model_copy(update={"benchmark": benchmark})
    if args.patch_format:
        config = config.model_copy(update={"patch_format": args.patch_format})

    if config.provider.provider == "mock" and not args.mock:
        print(
            "Refusing to run: the configured provider is 'mock'. This produces no "
            "evidence about real model behaviour.\nUse --mock to run a pipeline "
            "demonstration, or set MODEL_PROVIDER/MODEL_NAME for a real model.",
            file=sys.stderr,
        )
        return 2

    if config.provider.provider != "mock" and config.provider.seed is None:
        print(
            "note: provider seed is unset; generation is not reproducible for this run.",
            file=sys.stderr,
        )

    from verifyloop.evaluation.evaluator import ExperimentRunner, RunnerHooks
    from verifyloop.model_providers.mock import MockResponse

    store = ExperimentStore(_default_db(config))

    def on_start(run_id: str, total: int) -> None:
        print(f"run {run_id}: {total} task runs queued")
        print(f"provider={config.provider.provider} model={config.provider.model}")

    def on_task(task_id: str, strategy: str, trial: int) -> None:
        print(f"  [{trial}] {task_id} :: {strategy} ... ", end="", flush=True)

    def on_done(result) -> None:
        print(
            f"{result.outcome.value} "
            f"(attempts={len(result.attempts)}, calls={result.model_calls}, "
            f"{result.wall_clock_seconds:.1f}s)"
        )

    runner = ExperimentRunner(
        config,
        store=store,
        hooks=RunnerHooks(
            on_run_start=on_start,
            on_task_start=on_task,
            on_task_complete=on_done,
        ),
        mock_responses=_demo_mock_responses(config) if args.mock else None,
    )
    outcome = runner.run()
    print()
    print(f"completed {len(outcome.results)} task runs")
    print(f"manifest: {outcome.manifest_path}")

    results = store.load_results(outcome.run_id)
    summary = build_summary(results)
    paths = export_bundle(
        results, summary, _repo_root() / config.output_dir / "exports", run_id=outcome.run_id
    )
    for label, path in paths.items():
        print(f"{label}: {path}")
    return 0


def _demo_mock_responses(config: ExperimentConfig) -> list:
    """Reference patches for a deterministic pipeline demo.

    Only used with ``--mock``. These are scripted responses, not model output.
    """
    from verifyloop.model_providers.mock import MockResponse

    root = resolve_benchmark_root(config.benchmark.root)
    _, tasks = load_benchmark(
        root,
        version=config.benchmark.version,
        task_ids=config.benchmark.task_ids or None,
    )
    responses = []
    for task in tasks:
        patch = task.read_reference_patch()
        for _ in range(config.budgets.max_attempts):
            responses.append(MockResponse(text=patch))
    return responses


# ---------------------------------------------------------------------------
# export / report
# ---------------------------------------------------------------------------


def cmd_export(args: argparse.Namespace) -> int:
    config = load_default_config(args.config, use_env=False)
    store = ExperimentStore(_default_db(config))
    if args.run_id:
        results = store.load_results(args.run_id)
        run_id = args.run_id
    else:
        runs = store.list_runs(limit=1)
        if not runs:
            print("no runs recorded", file=sys.stderr)
            return 1
        run_id = runs[0]["run_id"]
        results = store.load_results(run_id)
    if not results:
        print(f"no results for run {run_id}", file=sys.stderr)
        return 1
    summary = build_summary(results)
    output = Path(args.output or (_repo_root() / config.output_dir / "exports"))
    paths = export_bundle(results, summary, output, run_id=run_id)
    for label, path in paths.items():
        print(f"{label}: {path}")
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    from verifyloop.reporting.tables import render_report

    config = load_default_config(args.config, use_env=False)
    store = ExperimentStore(_default_db(config))
    if args.run_id:
        run_id = args.run_id
        results = store.load_results(run_id)
    else:
        runs = store.list_runs(limit=1)
        if not runs:
            print("no runs recorded; run an experiment first", file=sys.stderr)
            return 1
        run_id = runs[0]["run_id"]
        results = store.load_results(run_id)
    if not results:
        print(f"no results for run {run_id}", file=sys.stderr)
        return 1
    print(render_report(results, run_id=run_id))
    if args.output:
        Path(args.output).write_text(
            render_report(results, run_id=run_id), encoding="utf-8"
        )
        print(f"\nwritten to {args.output}")
    return 0


# ---------------------------------------------------------------------------
# ui
# ---------------------------------------------------------------------------


def cmd_ui(args: argparse.Namespace) -> int:
    app_path = Path(__file__).resolve().parent / "ui" / "app.py"
    if not app_path.is_file():
        print(f"dashboard not found: {app_path}", file=sys.stderr)
        return 1
    command = [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        str(app_path),
        "--server.port",
        str(args.port),
    ]
    return subprocess.call(command)


# ---------------------------------------------------------------------------
# parser
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="verifyloop",
        description="Evidence-guided test-and-repair loops for small coding agents.",
    )
    parser.add_argument("--version", action="version", version=f"VerifyLoop {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    doctor = subparsers.add_parser("doctor", help="inspect environment and configuration")
    doctor.add_argument("--config", default=None)
    doctor.set_defaults(func=cmd_doctor)

    provider_check = subparsers.add_parser(
        "provider-check",
        help="verify provider connectivity, model presence, and a real generation",
    )
    provider_check.add_argument("--config", default=None)
    provider_check.add_argument(
        "--timeout",
        type=float,
        default=None,
        help="override the configured request timeout in seconds",
    )
    provider_check.set_defaults(func=cmd_provider_check)

    list_tasks = subparsers.add_parser("list-tasks", help="list benchmark tasks")
    list_tasks.add_argument("--config", default=None)
    list_tasks.add_argument("--json", action="store_true")
    list_tasks.set_defaults(func=cmd_list_tasks)

    validate = subparsers.add_parser("validate-bench", help="validate benchmark tasks")
    validate.set_defaults(func=cmd_validate_bench)

    smoke = subparsers.add_parser("smoke-test", help="offline end-to-end pipeline test")
    smoke.set_defaults(func=cmd_smoke_test)

    run = subparsers.add_parser("run", help="execute an experiment")
    run.add_argument("--config", default=None)
    run.add_argument("--strategies", nargs="+", choices=list(STRATEGY_NAMES))
    run.add_argument("--trials", type=int)
    run.add_argument("--max-attempts", type=int)
    run.add_argument("--task-ids", nargs="+")
    run.add_argument(
        "--patch-format", choices=["diff", "edit_json", "edit_json_single"]
    )
    run.add_argument(
        "--mock",
        action="store_true",
        help="allow the mock provider (pipeline demonstration only)",
    )
    run.set_defaults(func=cmd_run)

    export = subparsers.add_parser("export", help="export persisted results")
    export.add_argument("--config", default=None)
    export.add_argument("--run-id", default=None)
    export.add_argument("--output", default=None)
    export.set_defaults(func=cmd_export)

    report = subparsers.add_parser("report", help="render a results report")
    report.add_argument("--config", default=None)
    report.add_argument("--run-id", default=None)
    report.add_argument("--output", default=None)
    report.set_defaults(func=cmd_report)

    ui = subparsers.add_parser("ui", help="launch the Streamlit dashboard")
    ui.add_argument("--port", type=int, default=8501)
    ui.set_defaults(func=cmd_ui)

    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
