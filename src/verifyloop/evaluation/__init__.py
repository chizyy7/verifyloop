"""Evaluation, metrics, and experiment orchestration."""

from __future__ import annotations

from verifyloop.evaluation.metrics import (
    Proportion,
    StrategySummary,
    build_summary,
    compare_strategies,
    mcnemar_exact,
    paired_difference_ci,
    paired_outcomes,
    proportion,
    summarize_strategy,
    wilson_interval,
)

__all__ = [
    "Proportion",
    "StrategySummary",
    "build_summary",
    "compare_strategies",
    "mcnemar_exact",
    "paired_difference_ci",
    "paired_outcomes",
    "proportion",
    "summarize_strategy",
    "wilson_interval",
]
