"""Tests for the repair-controller state machine."""

from __future__ import annotations

import pytest

from verifyloop.state_machine import (
    TRANSITIONS,
    InvalidTransition,
    State,
    StateMachine,
    validate_transition_table,
)


def test_happy_path_is_legal() -> None:
    machine = StateMachine()
    path = [
        State.BASELINE_CHECK,
        State.CONTEXT_READY,
        State.PATCH_GENERATION,
        State.PATCH_VALIDATION,
        State.FEEDBACK_TESTING,
        State.FINAL_EVALUATION,
        State.COMPLETED,
    ]
    for state in path:
        machine.transition(state, reason="test")
    assert machine.state is State.COMPLETED
    assert machine.is_terminal
    assert len(machine.events) == len(path)


def test_repair_loop_is_legal() -> None:
    machine = StateMachine()
    for state in [
        State.BASELINE_CHECK,
        State.CONTEXT_READY,
        State.PATCH_GENERATION,
        State.PATCH_VALIDATION,
        State.FEEDBACK_TESTING,
        State.FAILURE_ANALYSIS,
        State.REPAIR_GENERATION,
        State.PATCH_VALIDATION,
        State.FEEDBACK_TESTING,
        State.FINAL_EVALUATION,
        State.COMPLETED,
    ]:
        machine.transition(state)
    assert machine.state is State.COMPLETED


def test_illegal_transition_raises_and_does_not_mutate() -> None:
    machine = StateMachine()
    with pytest.raises(InvalidTransition):
        machine.transition(State.COMPLETED)
    assert machine.state is State.INITIALIZED
    assert machine.events == []


def test_cannot_skip_validation() -> None:
    machine = StateMachine()
    machine.transition(State.BASELINE_CHECK)
    machine.transition(State.CONTEXT_READY)
    machine.transition(State.PATCH_GENERATION)
    with pytest.raises(InvalidTransition):
        machine.transition(State.FEEDBACK_TESTING)


def test_terminal_states_are_sinks() -> None:
    machine = StateMachine()
    machine.transition(State.INVALID_TASK)
    assert machine.is_terminal
    for target in State:
        assert not machine.can_transition(target)


def test_events_record_reason_and_order() -> None:
    machine = StateMachine()
    machine.transition(State.BASELINE_CHECK, reason="baseline")
    machine.transition(State.CONTEXT_READY, reason="context")
    payload = machine.to_dict()
    assert [event["target"] for event in payload["events"]] == [
        "BASELINE_CHECK",
        "CONTEXT_READY",
    ]
    assert payload["events"][0]["reason"] == "baseline"
    assert payload["events"][0]["index"] == 0


def test_visited_includes_initial() -> None:
    machine = StateMachine()
    machine.transition(State.BASELINE_CHECK)
    assert machine.visited() == [State.INITIALIZED, State.BASELINE_CHECK]


def test_transition_table_is_structurally_sound() -> None:
    assert validate_transition_table() == []


def test_transition_table_detects_dead_end_cycle() -> None:
    table = {state: set(targets) for state, targets in TRANSITIONS.items()}
    # ANALYSIS <-> REPAIR with no exit: neither can ever reach a terminal state.
    table[State.FAILURE_ANALYSIS] = {State.REPAIR_GENERATION}
    table[State.REPAIR_GENERATION] = {State.FAILURE_ANALYSIS}
    problems = validate_transition_table(table)
    assert any("FAILURE_ANALYSIS" in problem for problem in problems)
    assert any("REPAIR_GENERATION" in problem for problem in problems)


def test_transition_table_detects_terminal_with_outgoing_edge() -> None:
    table = {state: set(targets) for state, targets in TRANSITIONS.items()}
    table[State.COMPLETED] = {State.PATCH_GENERATION}
    problems = validate_transition_table(table)
    assert any("terminal state COMPLETED" in problem for problem in problems)
