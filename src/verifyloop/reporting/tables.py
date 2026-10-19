"""Markdown table rendering for experiment results."""

from __future__ import annotations

from typing import Any, Sequence

from verifyloop.evaluation.metrics import build_summary


def _fmt(value: Any) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.3f}"
    return str(value)


def comparison_table(summary: dict[str, Any]) -> str:
    rows = [
        ("Strategy", "Verified", "Regression-free", "Visible-only", "Mean attempts",
         "Mean calls", "Mean tokens", "Median wall (s)")
    ]
    lines = [
        "| " + " | ".join(rows[0]) + " |",
        "|" + "|".join(["---"] * len(rows[0])) + "|",
    ]
    for strategy, data in summary.get("strategies", {}).items():
        verified = data.get("verified_successes", 0)
        total = data.get("valid_tasks", 0)
        rate = data.get("verified_rate")
        ci_lower = data.get("verified_ci_lower")
        ci_upper = data.get("verified_ci_upper")
        verified_cell = (
            f"{verified}/{total}"
            if rate is None
            else f"{verified}/{total} ({rate:.0%}, "
                 f"{ci_lower:.0%}-{ci_upper:.0%})"
        )
        regression_free = data.get("regression_free_rate")
        lines.append(
            "| "
            + " | ".join(
                [
                    strategy,
                    verified_cell,
                    "n/a" if regression_free is None else f"{regression_free:.0%}",
                    str(data.get("visible_only_successes", 0)),
                    _fmt(data.get("mean_attempts")),
                    _fmt(data.get("mean_model_calls")),
                    _fmt(data.get("mean_tokens")),
                    _fmt(data.get("median_wall_clock")),
                ]
            )
            + " |"
        )
    return "\n".join(lines)


def paired_table(summary: dict[str, Any]) -> str:
    comparisons = summary.get("comparisons", [])
    if not comparisons:
        return "_No paired comparisons available._"
    lines = [
        "| Comparison | Pairs | Only A | Only B | Difference | 95% CI | McNemar p |",
        "|---|---|---|---|---|---|---|",
    ]
    for comparison in comparisons:
        ci = comparison.get("difference_ci")
        ci_text = "n/a" if not ci else f"[{ci[0]:+.2f}, {ci[1]:+.2f}]"
        difference = comparison.get("difference")
        lines.append(
            "| "
            + " | ".join(
                [
                    f"{comparison['strategy_a']} vs {comparison['strategy_b']}",
                    str(comparison.get("pairs", 0)),
                    str(comparison.get("only_a", 0)),
                    str(comparison.get("only_b", 0)),
                    "n/a" if difference is None else f"{difference:+.2f}",
                    ci_text,
                    f"{comparison.get('mcnemar', {}).get('p_value', 1.0):.4f}",
                ]
            )
            + " |"
        )
    return "\n".join(lines)


def failure_table(summary: dict[str, Any]) -> str:
    lines = ["| Strategy | Failure category | Count |", "|---|---|---|"]
    for strategy, data in summary.get("strategies", {}).items():
        for category, count in data.get("failure_categories", {}).items():
            lines.append(f"| {strategy} | {category} | {count} |")
    if len(lines) == 2:
        return "_No failure data._"
    return "\n".join(lines)


def render_report(results: Sequence[dict[str, Any]], *, run_id: str = "") -> str:
    summary = build_summary(results)
    header = f"# VerifyLoop results report\n\nRun: `{run_id or 'all'}`\n"
    if not results:
        return header + "\n_No results recorded._\n"
    parts = [
        header,
        f"Total task runs: {len(results)}\n",
        "## Strategy comparison\n",
        comparison_table(summary),
        "\n## Paired comparisons\n",
        paired_table(summary),
        "\n## Failure categories\n",
        failure_table(summary),
        "\n## Interpretation status\n",
        "_These are descriptive statistics from the saved results. Statistical "
        "significance is not claimed; see the confidence intervals and pair counts._\n",
    ]
    return "\n".join(parts)
