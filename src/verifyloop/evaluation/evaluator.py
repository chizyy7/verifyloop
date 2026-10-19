"""Experiment runner: orchestrates strategies × tasks × trials under one config.

Fairness properties enforced here:

* the same task snapshot, prompt text, patch rules, and test commands are used for
  every strategy;
* the task order is either the manifest order or a seeded shuffle, and the seed is
  recorded;
* every trial/strategy/task result is persisted, including failures;
* a reproducibility manifest is written once, before results are produced.
"""

from __future__ import annotations

import hashlib
import json
import platform
import random
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional, Sequence

import pydantic

from verifyloop import __version__
from verifyloop.benchmark.manifest import LoadedTask, load_benchmark
from verifyloop.config import ExperimentConfig
from verifyloop.controller import ControllerConfig, RepairController
from verifyloop.model_providers.base import ModelProvider
from verifyloop.model_providers.mock import MockProvider, MockResponse
from verifyloop.model_providers import build_provider
from verifyloop.models import TaskResult
from verifyloop.storage.database import ExperimentStore, RunRecord, utc_now
from verifyloop.strategies import get_strategy


@dataclass
class RunnerHooks:
    """Optional callbacks for progress reporting in the CLI and dashboard."""

    on_run_start: Optional[Callable[[str, int], None]] = None
    on_task_start: Optional[Callable[[str, str, int], None]] = None
    on_task_complete: Optional[Callable[[TaskResult], None]] = None
    should_cancel: Optional[Callable[[], bool]] = None


@dataclass
class ExperimentOutcome:
    run_id: str
    results: list[TaskResult] = field(default_factory=list)
    manifest_path: Optional[Path] = None
    cancelled: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "result_count": len(self.results),
            "manifest_path": str(self.manifest_path) if self.manifest_path else None,
            "cancelled": self.cancelled,
        }


def software_versions() -> dict[str, str]:
    return {
        "verifyloop": __version__,
        "python": sys.version.split()[0],
        "python_implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "pydantic": pydantic.VERSION,
    }


def build_reproducibility_manifest(
    config: ExperimentConfig,
    *,
    run_id: str,
    tasks: Sequence[LoadedTask],
    manifest_meta: dict[str, Any],
    provider_description: dict[str, Any],
    seed: int,
) -> dict[str, Any]:
    """Everything another researcher needs to reproduce this run."""
    task_hashes = {
        task.id: hashlib.sha256(task.reference_patch_path.read_bytes()).hexdigest()
        for task in tasks
    }
    return {
        "run_id": run_id,
        "experiment_name": config.name,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "benchmark": {
            "name": manifest_meta.get("name", ""),
            "version": manifest_meta.get("version", config.benchmark.version),
            "task_count": len(tasks),
            "task_ids": [task.id for task in tasks],
            "reference_fix_hashes": task_hashes,
            "description": manifest_meta.get("description", ""),
        },
        "provider": provider_description,
        "strategies": list(config.strategies),
        "trials": config.trials,
        "task_order": config.task_order,
        "task_order_seed": seed,
        "patch_format": config.patch_format,
        "budgets": config.budgets.model_dump(mode="json"),
        "execution": {
            "allowed_commands": list(config.execution.allowed_commands),
        },
        "protected_paths": list(config.benchmark.protected_paths),
        "software": software_versions(),
        "config": config.redacted_dict(),
        "notes": config.notes,
        "limitations": [
            "Synthetic benchmark; not production incidents.",
            "Single machine, CPU-only inference; no GPU.",
            "Process isolation is resource/scope control, not a security sandbox.",
            "Token counts use provider-reported usage when available and a character "
            "estimate otherwise; the estimator is recorded per attempt.",
        ],
    }


class ExperimentRunner:
    """Executes a configured experiment and persists every result."""

    def __init__(
        self,
        config: ExperimentConfig,
        *,
        store: ExperimentStore,
        output_dir: Path | None = None,
        hooks: RunnerHooks | None = None,
        mock_responses: Sequence[MockResponse] | None = None,
        provider: ModelProvider | None = None,
    ) -> None:
        self.config = config
        self.store = store
        self.output_dir = Path(output_dir or config.output_dir)
        self.hooks = hooks or RunnerHooks()
        self._mock_responses = list(mock_responses or [])
        self._provider = provider
        self._cancelled = False

    def request_cancel(self) -> None:
        self._cancelled = True

    def run(self) -> ExperimentOutcome:
        run_id = f"run-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
        seed = self.config.provider.seed or 0
        manifest_meta, tasks = load_benchmark(
            self.config.benchmark.root,
            version=self.config.benchmark.version,
            task_ids=self.config.benchmark.task_ids or None,
        )
        tasks = list(tasks)

        if self.config.task_order == "shuffled":
            random.Random(seed).shuffle(tasks)

        provider = self._provider or self._make_provider()
        provider_description = provider.describe()

        manifest = build_reproducibility_manifest(
            self.config,
            run_id=run_id,
            tasks=tasks,
            manifest_meta=manifest_meta.model_dump(mode="json"),
            provider_description=provider_description,
            seed=seed,
        )

        self.output_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = self.output_dir / f"{run_id}.manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

        self.store.create_run(
            RunRecord(
                run_id=run_id,
                experiment_name=self.config.name,
                benchmark_version=manifest_meta.version,
                provider=provider_description.get("provider", "unknown"),
                model=provider_description.get("model", "unknown"),
                strategies=list(self.config.strategies),
                trials=self.config.trials,
                created_at=utc_now(),
                status="running",
                config=self.config.redacted_dict(),
                manifest=manifest,
                notes=self.config.notes,
            )
        )

        total_units = len(tasks) * len(self.config.strategies) * self.config.trials
        if self.hooks.on_run_start:
            self.hooks.on_run_start(run_id, total_units)

        outcome = ExperimentOutcome(run_id=run_id, manifest_path=manifest_path)

        try:
            for trial in range(self.config.trials):
                for task in tasks:
                    for strategy_name in self.config.strategies:
                        if self._should_stop():
                            outcome.cancelled = True
                            self.store.update_run_status(run_id, "cancelled", finished=True)
                            return outcome
                        if self.hooks.on_task_start:
                            self.hooks.on_task_start(task.id, strategy_name, trial)

                        result = self._run_one(
                            provider, task, strategy_name, trial, run_id
                        )
                        self.store.save_result(result)
                        outcome.results.append(result)
                        if self.hooks.on_task_complete:
                            self.hooks.on_task_complete(result)
        finally:
            if not outcome.cancelled:
                self.store.update_run_status(run_id, "completed", finished=True)

        return outcome

    def _make_provider(self) -> ModelProvider:
        if self.config.provider.provider == "mock":
            return MockProvider(
                responses=self._mock_responses,
                model=self.config.provider.model,
                repeat_last=True,
                default_response=MockResponse(
                    text="```diff\n--- a/nonexistent.py\n+++ b/nonexistent.py\n"
                    "@@ -1,1 +1,1 @@\n-x\n+y\n```"
                ),
            )
        return build_provider(self.config.provider)

    def _run_one(
        self,
        provider: ModelProvider,
        task: LoadedTask,
        strategy_name: str,
        trial: int,
        run_id: str,
    ) -> TaskResult:
        controller = RepairController(
            provider=provider,
            strategy=get_strategy(strategy_name),
            config=ControllerConfig(
                budgets=self.config.budgets,
                allowed_commands=self.config.execution.allowed_commands,
                workspace_root=(
                    Path(self.config.execution.workspace_root)
                    if self.config.execution.workspace_root
                    else None
                ),
                keep_workspaces=self.config.execution.keep_workspaces,
                patch_format=self.config.patch_format,
                protected_patterns=self.config.benchmark.protected_paths,
            ),
            task=task,
            trial=trial,
            run_id=run_id,
        )
        return controller.run()

    def _should_stop(self) -> bool:
        if self._cancelled:
            return True
        if self.hooks.should_cancel and self.hooks.should_cancel():
            return True
        return False
