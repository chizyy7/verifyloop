"""Explicit finite-state machine for the repair controller.

The controller is the only component allowed to drive transitions. Illegal
transitions raise ``InvalidTransition`` so a bug in strategy code cannot silently
skip a safety step such as patch validation or independent evaluation.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable, Optional


class State(str, Enum):
    INITIALIZED = "INITIALIZED"
    BASELINE_CHECK = "BASELINE_CHECK"
    CONTEXT_READY = "CONTEXT_READY"
    PATCH_GENERATION = "PATCH_GENERATION"
    PATCH_VALIDATION = "PATCH_VALIDATION"
    FEEDBACK_TESTING = "FEEDBACK_TESTING"
    FAILURE_ANALYSIS = "FAILURE_ANALYSIS"
    REPAIR_GENERATION = "REPAIR_GENERATION"
    FINAL_EVALUATION = "FINAL_EVALUATION"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"
    INVALID_TASK = "INVALID_TASK"


TERMINAL_STATES: frozenset[State] = frozenset(
    {State.COMPLETED, State.FAILED, State.BUDGET_EXHAUSTED, State.INVALID_TASK}
)

#: Legal transitions. Any edge not listed here is a programming error.
TRANSITIONS: dict[State, frozenset[State]] = {
    State.INITIALIZED: frozenset({State.BASELINE_CHECK, State.INVALID_TASK}),
    State.BASELINE_CHECK: frozenset(
        {State.CONTEXT_READY, State.INVALID_TASK, State.FAILED}
    ),
    State.CONTEXT_READY: frozenset(
        {State.PATCH_GENERATION, State.BUDGET_EXHAUSTED, State.FAILED}
    ),
    State.PATCH_GENERATION: frozenset(
        {State.PATCH_VALIDATION, State.REPAIR_GENERATION, State.BUDGET_EXHAUSTED,
         State.FAILED}
    ),
    State.PATCH_VALIDATION: frozenset(
        {State.FEEDBACK_TESTING, State.PATCH_GENERATION, State.REPAIR_GENERATION,
         State.FAILED, State.BUDGET_EXHAUSTED}
    ),
    State.FEEDBACK_TESTING: frozenset(
        {State.FAILURE_ANALYSIS, State.FINAL_EVALUATION, State.FAILED,
         State.BUDGET_EXHAUSTED}
    ),
    State.FAILURE_ANALYSIS: frozenset(
        {State.REPAIR_GENERATION, State.FINAL_EVALUATION, State.BUDGET_EXHAUSTED,
         State.FAILED}
    ),
    State.REPAIR_GENERATION: frozenset(
        {State.PATCH_VALIDATION, State.BUDGET_EXHAUSTED, State.FAILED}
    ),
    State.FINAL_EVALUATION: frozenset({State.COMPLETED, State.FAILED}),
    State.COMPLETED: frozenset(),
    State.FAILED: frozenset(),
    State.BUDGET_EXHAUSTED: frozenset(),
    State.INVALID_TASK: frozenset(),
}


class InvalidTransition(RuntimeError):
    """Raised when a state transition is not permitted by the state machine."""

    def __init__(self, source: State, target: State) -> None:
        super().__init__(f"illegal transition {source.value} -> {target.value}")
        self.source = source
        self.target = target


@dataclass(frozen=True)
class TransitionEvent:
    index: int
    source: State
    target: State
    reason: str
    elapsed_ms: float


@dataclass
class StateMachine:
    """Tracks the controller's state and an auditable transition log."""

    state: State = State.INITIALIZED
    events: list[TransitionEvent] = field(default_factory=list)
    _started_at: float = field(default_factory=time.monotonic)

    def can_transition(self, target: State) -> bool:
        return target in TRANSITIONS[self.state]

    def transition(self, target: State, reason: str = "") -> State:
        if not self.can_transition(target):
            raise InvalidTransition(self.state, target)
        source = self.state
        self.state = target
        self.events.append(
            TransitionEvent(
                index=len(self.events),
                source=source,
                target=target,
                reason=reason,
                elapsed_ms=round((time.monotonic() - self._started_at) * 1000, 3),
            )
        )
        return self.state

    @property
    def is_terminal(self) -> bool:
        return self.state in TERMINAL_STATES

    def visited(self) -> list[State]:
        seen: list[State] = [State.INITIALIZED]
        seen.extend(event.target for event in self.events)
        return seen

    def to_dict(self) -> dict:
        return {
            "state": self.state.value,
            "events": [
                {
                    "index": event.index,
                    "source": event.source.value,
                    "target": event.target.value,
                    "reason": event.reason,
                    "elapsed_ms": event.elapsed_ms,
                }
                for event in self.events
            ],
        }


def validate_transition_table(
    table: Optional[dict[State, Iterable[State]]] = None,
) -> list[str]:
    """Check the transition table for structural problems.

    Returns a list of human-readable problems (empty when the table is sound).
    Used by the test suite and by ``verifyloop doctor``.
    """
    problems: list[str] = []
    resolved = {state: frozenset(targets) for state, targets in (table or TRANSITIONS).items()}

    for state in State:
        if state not in resolved:
            problems.append(f"state {state.value} has no transition entry")

    for state, targets in resolved.items():
        for target in targets:
            if target not in State:
                problems.append(f"{state.value} points at unknown state {target!r}")

    # Every non-terminal state must be able to reach a terminal state.
    for state in State:
        if state in TERMINAL_STATES:
            continue
        if not _reaches_terminal(state, resolved):
            problems.append(f"{state.value} cannot reach a terminal state")

    # Terminal states must be sinks.
    for state in TERMINAL_STATES:
        if resolved.get(state):
            problems.append(f"terminal state {state.value} has outgoing transitions")

    return problems


def _reaches_terminal(
    start: State,
    table: dict[State, frozenset[State]],
) -> bool:
    stack = [start]
    seen: set[State] = set()
    while stack:
        current = stack.pop()
        if current in TERMINAL_STATES:
            return True
        if current in seen:
            continue
        seen.add(current)
        stack.extend(table.get(current, frozenset()))
    return False
