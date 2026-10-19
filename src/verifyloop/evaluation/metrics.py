"""Metrics and statistical summaries computed from persisted results.

Every rate is reported with its numerator and denominator. Confidence intervals are
Wilson score intervals, which behave sensibly for the small samples this study can
afford. Paired comparisons use exact McNemar tests on discordant pairs.

Nothing here invents data. If a denominator is zero the rate is ``None``, not 0%.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

from verifyloop.models import Outcome


@dataclass
class Proportion:
    successes: int
    total: int
    lower: float | None = None
    upper: float | None = None

    @property
    def rate(self) -> float | None:
        return self.successes / self.total if self.total else None

    def describe(self) -> str:
        if self.total == 0:
            return "n/a (0/0)"
        assert self.rate is not None
        if self.lower is None or self.upper is None:
            return f"{self.successes}/{self.total} ({self.rate:.1%})"
        return (
            f"{self.successes}/{self.total} ({self.rate:.1%}, "
            f"95% CI {self.lower:.1%}-{self.upper:.1%})"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "successes": self.successes,
            "total": self.total,
            "rate": self.rate,
            "ci_lower": self.lower,
            "ci_upper": self.upper,
        }


def wilson_interval(successes: int, total: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval for a binomial proportion."""
    if total <= 0:
        return (0.0, 1.0)
    if successes < 0 or successes > total:
        raise ValueError("successes must be within [0, total]")
    phat = successes / total
    denominator = 1 + z * z / total
    centre = phat + z * z / (2 * total)
    margin = z * math.sqrt((phat * (1 - phat) + z * z / (4 * total)) / total)
    lower = (centre - margin) / denominator
    upper = (centre + margin) / denominator
    return (max(0.0, lower), min(1.0, upper))


def proportion(successes: int, total: int) -> Proportion:
    lower, upper = wilson_interval(successes, total)
    return Proportion(successes=successes, total=total, lower=lower, upper=upper)


def mcnemar_exact(b: int, c: int) -> dict[str, Any]:
    """Exact McNemar test on discordant pair counts.

    ``b`` = pairs where condition A succeeded and B failed.
    ``c`` = pairs where A failed and B succeeded.
    """
    n = b + c
    if n == 0:
        return {
            "b": b,
            "c": c,
            "p_value": 1.0,
            "note": "no discordant pairs",
        }
    # Two-sided exact binomial test with p=0.5.
    tail = sum(math.comb(n, k) for k in range(0, min(b, c) + 1)) / (2**n)
    p_value = min(1.0, 2 * tail)
    return {
        "b": b,
        "c": c,
        "p_value": p_value,
        "note": "exact binomial, two-sided",
    }


def paired_difference_ci(
    pairs: Sequence[tuple[int, int]], *, iterations: int = 2000, seed: int = 0
) -> tuple[float, float] | None:
    """Paired bootstrap CI for the difference in success rate (A - B).

    ``pairs`` is a sequence of ``(a_success, b_success)`` 0/1 tuples.
    Returns ``None`` when there are no pairs.
    """
    if not pairs:
        return None
    import random

    rng = random.Random(seed)
    differences: list[float] = []
    n = len(pairs)
    for _ in range(iterations):
        sample = [pairs[rng.randrange(n)] for _ in range(n)]
        a = sum(pair[0] for pair in sample) / n
        b = sum(pair[1] for pair in sample) / n
        differences.append(a - b)
    differences.sort()
    lower = differences[int(0.025 * iterations)]
    upper = differences[int(0.975 * iterations) - 1]
    return (lower, upper)


@dataclass
class StrategySummary:
    strategy: str
    valid_tasks: int = 0
    verified_successes: int = 0
    visible_only_successes: int = 0
    regressions: int = 0
    budget_exhausted: int = 0
    patch_rejections: int = 0
    infrastructure_failures: int = 0
    invalid_tasks: int = 0
    attempt_counts: list[int] = field(default_factory=list)
    model_calls: list[int] = field(default_factory=list)
    total_tokens: list[int] = field(default_factory=list)
    wall_clock: list[float] = field(default_factory=list)
    failure_categories: dict[str, int] = field(default_factory=dict)

    @property
    def verified_proportion(self) -> Proportion:
        return proportion(self.verified_successes, self.valid_tasks)

    @property
    def regression_free_successes(self) -> int:
        return self.verified_successes - self.regressions

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy": self.strategy,
            "valid_tasks": self.valid_tasks,
            "verified_successes": self.verified_successes,
            "verified_rate": self.verified_proportion.rate,
            "verified_ci_lower": self.verified_proportion.lower,
            "verified_ci_upper": self.verified_proportion.upper,
            "visible_only_successes": self.visible_only_successes,
            "regressions": self.regressions,
            "regression_free_rate": (
                self.regression_free_successes / self.valid_tasks
                if self.valid_tasks
                else None
            ),
            "budget_exhausted": self.budget_exhausted,
            "patch_rejections": self.patch_rejections,
            "infrastructure_failures": self.infrastructure_failures,
            "invalid_tasks": self.invalid_tasks,
            "mean_attempts": _mean(self.attempt_counts),
            "median_attempts": _median(self.attempt_counts),
            "mean_model_calls": _mean(self.model_calls),
            "mean_tokens": _mean(self.total_tokens),
            "median_wall_clock": _median(self.wall_clock),
            "mean_wall_clock": _mean(self.wall_clock),
            "failure_categories": dict(sorted(self.failure_categories.items())),
        }


def _mean(values: Sequence[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _median(values: Sequence[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


def summarize_strategy(results: Iterable[dict[str, Any]], strategy: str) -> StrategySummary:
    summary = StrategySummary(strategy=strategy)
    for result in results:
        if result.get("strategy") != strategy:
            continue
        outcome = result.get("outcome")
        if outcome == Outcome.INVALID_TASK.value:
            summary.invalid_tasks += 1
            continue
        if outcome == Outcome.INFRASTRUCTURE_ERROR.value:
            summary.infrastructure_failures += 1
            continue

        summary.valid_tasks += 1
        if outcome == Outcome.VERIFIED_SUCCESS.value:
            summary.verified_successes += 1
        if outcome == Outcome.VISIBLE_ONLY_SUCCESS.value:
            summary.visible_only_successes += 1
        if outcome == Outcome.PATCH_REJECTED.value:
            summary.patch_rejections += 1
        if result.get("regression_detected"):
            summary.regressions += 1
        if result.get("budget_exhausted"):
            summary.budget_exhausted += 1

        summary.attempt_counts.append(int(result.get("attempt_count", 0)))
        summary.model_calls.append(int(result.get("model_calls", 0)))
        summary.total_tokens.append(int(result.get("total_tokens", 0)))
        summary.wall_clock.append(float(result.get("wall_clock_seconds", 0.0)))
        category = result.get("failure_category", "unknown")
        summary.failure_categories[category] = (
            summary.failure_categories.get(category, 0) + 1
        )
    return summary


def paired_outcomes(
    results: Sequence[dict[str, Any]], strategy_a: str, strategy_b: str
) -> list[tuple[str, int, int]]:
    """Return ``(task_key, a_success, b_success)`` for tasks present in both.

    The task key includes the trial so repeated trials are paired correctly.
    Tasks with an infrastructure failure or invalid status in either condition are
    dropped from the paired comparison (and remain visible in the summaries).
    """
    indexed: dict[tuple[str, int], dict[str, dict[str, Any]]] = {}
    for result in results:
        key = (result.get("task_id", ""), int(result.get("trial", 0)))
        indexed.setdefault(key, {})[result.get("strategy", "")] = result

    pairs: list[tuple[str, int, int]] = []
    for key, by_strategy in sorted(indexed.items()):
        a = by_strategy.get(strategy_a)
        b = by_strategy.get(strategy_b)
        if not a or not b:
            continue
        excluded = {
            Outcome.INVALID_TASK.value,
            Outcome.INFRASTRUCTURE_ERROR.value,
        }
        if a.get("outcome") in excluded or b.get("outcome") in excluded:
            continue
        pairs.append(
            (
                f"{key[0]}#{key[1]}",
                int(a.get("outcome") == Outcome.VERIFIED_SUCCESS.value),
                int(b.get("outcome") == Outcome.VERIFIED_SUCCESS.value),
            )
        )
    return pairs


def compare_strategies(
    results: Sequence[dict[str, Any]], strategy_a: str, strategy_b: str
) -> dict[str, Any]:
    """Paired comparison of two strategies on the same tasks and trials."""
    pairs = paired_outcomes(results, strategy_a, strategy_b)
    both = sum(1 for _, a, b in pairs if a == 1 and b == 1)
    only_a = sum(1 for _, a, b in pairs if a == 1 and b == 0)
    only_b = sum(1 for _, a, b in pairs if a == 0 and b == 1)
    neither = sum(1 for _, a, b in pairs if a == 0 and b == 0)
    mcnemar = mcnemar_exact(only_a, only_b)
    ci = paired_difference_ci([(a, b) for _, a, b in pairs])
    return {
        "strategy_a": strategy_a,
        "strategy_b": strategy_b,
        "pairs": len(pairs),
        "both_succeeded": both,
        "only_a": only_a,
        "only_b": only_b,
        "neither": neither,
        "difference": (only_a - only_b) / len(pairs) if pairs else None,
        "difference_ci": ci,
        "mcnemar": mcnemar,
    }


def build_summary(results: Sequence[dict[str, Any]]) -> dict[str, Any]:
    strategies = sorted({result.get("strategy", "") for result in results})
    summaries = {
        strategy: summarize_strategy(results, strategy).to_dict()
        for strategy in strategies
    }
    comparisons = []
    for index, first in enumerate(strategies):
        for second in strategies[index + 1:]:
            comparisons.append(compare_strategies(results, first, second))
    return {
        "total_results": len(results),
        "strategies": summaries,
        "comparisons": comparisons,
    }
