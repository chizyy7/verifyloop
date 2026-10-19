"""Strategy definitions.

A strategy answers exactly one question: *given the outcome of attempt N, what prompt
do I send for attempt N+1?* It does not execute tests, apply patches, or evaluate
success — the controller owns those steps so all strategies are compared under
identical mechanics.

This separation is what makes the comparison fair: the only difference between the
conditions is the information content of the retry prompt.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass
from typing import Sequence

from verifyloop.feedback.analyzer import FailureEvidence, summarize_statuses
from verifyloop.feedback.formatter import (
    format_blind_retry_prompt,
    format_concise_report,
    format_evidence_report,
    format_initial_prompt,
    format_patch_rejection,
    format_repair_prompt,
)
from verifyloop.models import TestReport


@dataclass
class StrategyContext:
    """Inputs a strategy may use to build a retry prompt."""

    task_description: str
    expected_behavior: str
    repository_context: str
    patch_format: str
    attempt: int  # the attempt that just failed (1-based)
    max_attempts: int
    evidence: FailureEvidence | None = None
    test_report: TestReport | None = None
    rejection_reason: str = ""


class Strategy(abc.ABC):
    """A prompt policy for initial and repair attempts."""

    name: str = "base"
    description: str = ""
    #: Whether this condition receives structured test evidence on retry.
    uses_evidence: bool = False

    def initial_prompt(self, context: StrategyContext) -> str:
        return format_initial_prompt(
            context.task_description,
            context.expected_behavior,
            context.repository_context,
            context.patch_format,
        )

    @abc.abstractmethod
    def retry_prompt(self, context: StrategyContext) -> str:
        """Build the prompt for the next attempt."""

    def should_retry(self, context: StrategyContext) -> bool:
        """Default: retry while attempts remain."""
        return context.attempt < context.max_attempts

    def describe(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "uses_evidence": self.uses_evidence,
        }


class OneShotStrategy(Strategy):
    """Single attempt; the model never sees any outcome."""

    name = "oneshot"
    description = "One patch attempt with repository context only."
    uses_evidence = False

    def retry_prompt(self, context: StrategyContext) -> str:
        raise RuntimeError("one-shot strategy never retries")

    def should_retry(self, context: StrategyContext) -> bool:
        return False


class BlindRetryStrategy(Strategy):
    """Repeated attempts told only that the previous one failed."""

    name = "blind_retry"
    description = (
        "Up to N attempts. Retry prompt states only that the attempt failed, with no "
        "diagnosis, test names, messages, or regression information."
    )
    uses_evidence = False

    def retry_prompt(self, context: StrategyContext) -> str:
        if context.rejection_reason:
            # A patch that never ran is not a test failure. Even the blind condition
            # must be told the patch was unusable, or it cannot make progress at all.
            return format_patch_rejection(
                context.attempt, context.rejection_reason, context.patch_format
            )
        return format_blind_retry_prompt(context.attempt, context.patch_format)


class EvidenceGuidedStrategy(Strategy):
    """Structured failure report with targeted repair instructions."""

    name = "evidence_guided"
    description = (
        "Up to N attempts. Each retry receives a structured report: per-test statuses, "
        "clipped failure messages, traceback excerpts, regression indicators, changed "
        "files, and remaining budget. Hidden evaluation results are never included."
    )
    uses_evidence = True

    def retry_prompt(self, context: StrategyContext) -> str:
        if context.rejection_reason:
            return format_patch_rejection(
                context.attempt, context.rejection_reason, context.patch_format
            )
        if context.evidence is None:
            return format_blind_retry_prompt(context.attempt, context.patch_format)
        return format_repair_prompt(
            format_evidence_report(context.evidence), context.patch_format
        )


class ConciseFeedbackStrategy(Strategy):
    """Ablation control: pass/fail statuses only, no messages or tracebacks."""

    name = "concise_feedback"
    description = (
        "Ablation condition. Retry receives per-test pass/fail names but no failure "
        "messages, tracebacks, or regression indicators."
    )
    uses_evidence = True

    def retry_prompt(self, context: StrategyContext) -> str:
        if context.rejection_reason:
            return format_patch_rejection(
                context.attempt, context.rejection_reason, context.patch_format
            )
        if context.evidence is None or context.test_report is None:
            return format_blind_retry_prompt(context.attempt, context.patch_format)
        return format_repair_prompt(
            format_concise_report(
                context.evidence, summarize_statuses(context.test_report)
            ),
            context.patch_format,
        )


_REGISTRY: dict[str, type[Strategy]] = {
    OneShotStrategy.name: OneShotStrategy,
    BlindRetryStrategy.name: BlindRetryStrategy,
    EvidenceGuidedStrategy.name: EvidenceGuidedStrategy,
    ConciseFeedbackStrategy.name: ConciseFeedbackStrategy,
}


def get_strategy(name: str) -> Strategy:
    try:
        return _REGISTRY[name]()
    except KeyError as exc:
        raise ValueError(
            f"unknown strategy {name!r}; available: {', '.join(sorted(_REGISTRY))}"
        ) from exc


def available_strategies() -> Sequence[str]:
    return tuple(sorted(_REGISTRY))
