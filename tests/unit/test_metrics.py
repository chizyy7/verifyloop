"""Tests for metrics, statistics, and paired comparison logic."""

from __future__ import annotations

import pytest

from verifyloop.evaluation.metrics import (
    build_summary,
    compare_strategies,
    mcnemar_exact,
    paired_difference_ci,
    paired_outcomes,
    proportion,
    summarize_strategy,
    wilson_interval,
)


def make_result(task: str, strategy: str, outcome: str, trial: int = 0, **extra):
    base = {
        "task_id": task,
        "strategy": strategy,
        "trial": trial,
        "outcome": outcome,
        "attempt_count": 1,
        "model_calls": 1,
        "total_tokens": 100,
        "wall_clock_seconds": 1.0,
        "regression_detected": False,
        "budget_exhausted": False,
        "failure_category": "none",
    }
    base.update(extra)
    return base


def test_wilson_interval_bounds() -> None:
    lower, upper = wilson_interval(0, 10)
    assert lower == 0.0
    assert 0.2 < upper < 0.35


def test_wilson_interval_all_success() -> None:
    lower, upper = wilson_interval(10, 10)
    assert 0.65 < lower < 0.8
    assert upper == 1.0


def test_wilson_interval_rejects_invalid() -> None:
    with pytest.raises(ValueError):
        wilson_interval(11, 10)


def test_proportion_reports_denominator() -> None:
    p = proportion(3, 8)
    assert p.successes == 3
    assert p.total == 8
    assert p.rate == pytest.approx(0.375)
    assert "3/8" in p.describe()


def test_zero_denominator_is_na_not_zero() -> None:
    p = proportion(0, 0)
    assert p.rate is None
    assert "n/a" in p.describe()


def test_mcnemar_no_discordant_pairs() -> None:
    result = mcnemar_exact(0, 0)
    assert result["p_value"] == 1.0


def test_mcnemar_symmetric_counts() -> None:
    result = mcnemar_exact(5, 5)
    assert result["p_value"] == pytest.approx(1.0)


def test_mcnemar_extreme_split_is_significant() -> None:
    result = mcnemar_exact(10, 0)
    assert result["p_value"] < 0.01


def test_paired_difference_ci_contains_point_estimate() -> None:
    pairs = [(1, 0)] * 8 + [(0, 1)] * 2
    ci = paired_difference_ci(pairs, iterations=500)
    assert ci is not None
    assert ci[0] <= 0.6 <= ci[1]


def test_paired_difference_ci_empty() -> None:
    assert paired_difference_ci([]) is None


def test_summarize_strategy_excludes_infrastructure_failures() -> None:
    results = [
        make_result("t1", "oneshot", "verified_success"),
        make_result("t2", "oneshot", "failed_tests"),
        make_result("t3", "oneshot", "infrastructure_error"),
        make_result("t4", "oneshot", "invalid_task"),
    ]
    summary = summarize_strategy(results, "oneshot")
    assert summary.valid_tasks == 2
    assert summary.verified_successes == 1
    assert summary.infrastructure_failures == 1
    assert summary.invalid_tasks == 1


def test_summarize_strategy_counts_regressions() -> None:
    results = [
        make_result("t1", "a", "verified_success", regression_detected=True),
        make_result("t2", "a", "verified_success"),
    ]
    summary = summarize_strategy(results, "a")
    assert summary.regressions == 1
    assert summary.regression_free_successes == 1


def test_paired_outcomes_matches_trials() -> None:
    results = [
        make_result("t1", "a", "verified_success", trial=0),
        make_result("t1", "b", "failed_tests", trial=0),
        make_result("t1", "a", "failed_tests", trial=1),
        make_result("t1", "b", "verified_success", trial=1),
    ]
    pairs = paired_outcomes(results, "a", "b")
    assert len(pairs) == 2
    assert pairs[0][1:] == (1, 0)
    assert pairs[1][1:] == (0, 1)


def test_paired_outcomes_drops_infrastructure() -> None:
    results = [
        make_result("t1", "a", "verified_success"),
        make_result("t1", "b", "infrastructure_error"),
    ]
    assert paired_outcomes(results, "a", "b") == []


def test_compare_strategies_structure() -> None:
    results = [
        make_result("t1", "a", "verified_success"),
        make_result("t1", "b", "failed_tests"),
        make_result("t2", "a", "verified_success"),
        make_result("t2", "b", "verified_success"),
    ]
    comparison = compare_strategies(results, "a", "b")
    assert comparison["pairs"] == 2
    assert comparison["only_a"] == 1
    assert comparison["both_succeeded"] == 1
    assert comparison["difference"] == pytest.approx(0.5)


def test_build_summary_includes_comparisons() -> None:
    results = [
        make_result("t1", "a", "verified_success"),
        make_result("t1", "b", "failed_tests"),
    ]
    summary = build_summary(results)
    assert set(summary["strategies"]) == {"a", "b"}
    assert len(summary["comparisons"]) == 1


def test_visible_only_success_counted_separately() -> None:
    results = [make_result("t1", "a", "visible_only_success")]
    summary = summarize_strategy(results, "a")
    assert summary.verified_successes == 0
    assert summary.visible_only_successes == 1
    assert summary.valid_tasks == 1
