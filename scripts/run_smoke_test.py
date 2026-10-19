"""End-to-end smoke test with the deterministic mock provider.

This proves the mechanical pipeline works: task load, baseline reproduction, patch
generation, validation, application, test execution, feedback, retry, and independent
evaluation. It is *not* evidence that a real model benefits from evidence-guided
repair.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from verifyloop.benchmark.manifest import load_benchmark  # noqa: E402
from verifyloop.config import load_default_config  # noqa: E402
from verifyloop.controller import ControllerConfig, RepairController  # noqa: E402
from verifyloop.model_providers.mock import MockProvider, MockResponse  # noqa: E402
from verifyloop.strategies import get_strategy  # noqa: E402


def build_controller(task, strategy_name: str, responses, config) -> RepairController:
    provider = MockProvider(responses=responses, model="mock-scripted")
    return RepairController(
        provider=provider,
        strategy=get_strategy(strategy_name),
        config=ControllerConfig(
            budgets=config.budgets,
            allowed_commands=config.execution.allowed_commands,
            patch_format=config.patch_format,
            protected_patterns=config.benchmark.protected_paths,
        ),
        task=task,
    )


def main() -> int:
    config = load_default_config(use_env=False)
    _, tasks = load_benchmark(
        REPO_ROOT / config.benchmark.root,
        version=config.benchmark.version,
        task_ids=["boundary_paginate_001"],
    )
    task = tasks[0]
    reference_patch = task.read_reference_patch()

    scenarios = [
        ("correct patch, one shot", "oneshot", [MockResponse(text=reference_patch)]),
        (
            "wrong patch then correct",
            "evidence_guided",
            [
                MockResponse(
                    text=reference_patch.replace(
                        "    end = start + per_page\n", "    end = start + per_page - 1\n"
                    )
                ),
                MockResponse(text=reference_patch),
            ],
        ),
        (
            "always wrong, exhausted",
            "blind_retry",
            [
                MockResponse(text=reference_patch.replace(
                    "    end = start + per_page\n", "    end = start + per_page - 2\n"
                ))
                for _ in range(3)
            ],
        ),
    ]

    failures = 0
    for label, strategy_name, responses in scenarios:
        controller = build_controller(task, strategy_name, responses, config)
        result = controller.run()
        print(f"[{label}] outcome={result.outcome.value} attempts={len(result.attempts)} "
              f"calls={result.model_calls}")
        if result.outcome.value == "infrastructure_error":
            print("  error:", result.error_message)
            failures += 1
        if label == "correct patch, one shot" and result.outcome.value != "verified_success":
            print("  EXPECTED verified_success")
            failures += 1
        if label == "wrong patch then correct" and result.outcome.value != "verified_success":
            print("  EXPECTED verified_success")
            failures += 1
        if label == "always wrong, exhausted" and result.outcome.value != "failed_tests":
            print("  EXPECTED failed_tests")
            failures += 1

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
