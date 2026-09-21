"""Focused reducer regressions for reordered and contradictory provider events."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from interlock.domain.enums import (
    ActionType,
    CancellationPolicy,
    CancellationState,
    EffectState,
    EventSource,
    OperationState,
    RuntimeMode,
    ToolOutcome,
)
from interlock.domain.events import ToolDispatchAccepted, ToolResultObserved
from interlock.domain.models import (
    EventEnvelope,
    MetricsSnapshot,
    OperationRecord,
    SessionState,
)
from interlock.runtime.commands import RecordProtocolViolation
from interlock.runtime.reducer import Reducer


def _operation(
    *,
    state: OperationState,
    effect_state: EffectState,
) -> OperationRecord:
    return OperationRecord(
        operation_id="op-1",
        tool_name="appointment.book",
        args={},
        intent_revision_id="revision-1",
        bindings=[],
        fingerprint="fingerprint-1",
        action_type=ActionType.REVERSIBLE,
        cancellation_policy=CancellationPolicy.AT_SAFEPOINT,
        state=state,
        cancellation_state=CancellationState.ACKNOWLEDGED,
        effect_state=effect_state,
        speculative=False,
        logical_action_id="action-1",
        idempotency_key="key-1",
        provider_request_id="provider-1",
        dispatch_requested_event_id="dispatch-event-1",
    )


def _state(operation: OperationRecord) -> SessionState:
    return SessionState(
        session_id="session-1",
        last_sequence=1,
        mode=RuntimeMode.TEST,
        operations={operation.operation_id: operation},
        metrics=MetricsSnapshot(session_id="session-1", through_sequence=1),
    )


def _envelope(event_type: str, payload: dict[str, object]) -> EventEnvelope:
    return EventEnvelope(
        event_id="event-2",
        session_id="session-1",
        sequence=2,
        event_type=event_type,
        source=EventSource.TOOL,
        occurred_at=datetime(2030, 1, 1, tzinfo=timezone.utc),
        logical_time=2,
        payload=payload,
    )


def _result_envelope(outcome: ToolOutcome) -> EventEnvelope:
    payload = ToolResultObserved(
        operation_id="op-1",
        provider_request_id="provider-1",
        outcome=outcome,
        result={},
    )
    return _envelope(
        "ToolResultObserved",
        payload.model_dump(mode="python"),
    )


def _dispatch_accepted_envelope() -> EventEnvelope:
    payload = ToolDispatchAccepted(
        operation_id="op-1",
        provider_request_id="provider-1",
    )
    return _envelope(
        "ToolDispatchAccepted",
        payload.model_dump(mode="python"),
    )


def _reduce(
    state: SessionState,
    envelope: EventEnvelope,
    *,
    mode: RuntimeMode | None = None,
) -> tuple[SessionState, list[object]]:
    reduced, commands = Reducer.reduce(state, envelope, mode=mode)
    assert reduced is not None
    return reduced, list(commands)


def _violations(commands: list[object]) -> list[RecordProtocolViolation]:
    return [
        command
        for command in commands
        if isinstance(command, RecordProtocolViolation)
    ]


@pytest.mark.parametrize(
    "operation_state",
    [OperationState.CANCELLED, OperationState.SUPERSEDED],
)
def test_late_success_commits_unestablished_effect_without_reactivating_operation(
    operation_state: OperationState,
) -> None:
    initial = _state(
        _operation(
            state=operation_state,
            effect_state=EffectState.NOT_STARTED,
        )
    )

    reduced, commands = _reduce(initial, _result_envelope(ToolOutcome.SUCCEEDED))

    operation = reduced.operations["op-1"]
    assert operation.state == operation_state
    assert operation.effect_state == EffectState.COMMITTED
    assert _violations(commands) == []


@pytest.mark.parametrize(
    ("effect_state", "outcome", "expected_effect_state"),
    [
        (EffectState.NOT_STARTED, ToolOutcome.SUCCEEDED, EffectState.COMMITTED),
        (EffectState.NOT_STARTED, ToolOutcome.FAILED, EffectState.FAILED),
        (
            EffectState.NOT_STARTED,
            ToolOutcome.UNKNOWN,
            EffectState.OUTCOME_UNKNOWN,
        ),
        (EffectState.IN_FLIGHT, ToolOutcome.SUCCEEDED, EffectState.COMMITTED),
        (EffectState.IN_FLIGHT, ToolOutcome.FAILED, EffectState.FAILED),
        (
            EffectState.IN_FLIGHT,
            ToolOutcome.UNKNOWN,
            EffectState.OUTCOME_UNKNOWN,
        ),
    ],
)
def test_unestablished_effect_accepts_authoritative_result(
    effect_state: EffectState,
    outcome: ToolOutcome,
    expected_effect_state: EffectState,
) -> None:
    initial = _state(
        _operation(
            state=OperationState.CANCELLED,
            effect_state=effect_state,
        )
    )

    reduced, commands = _reduce(initial, _result_envelope(outcome))

    assert reduced.operations["op-1"].effect_state == expected_effect_state
    assert _violations(commands) == []


@pytest.mark.parametrize(
    "operation_state",
    [OperationState.CANCELLED, OperationState.SUPERSEDED],
)
@pytest.mark.parametrize("outcome", [ToolOutcome.FAILED, ToolOutcome.UNKNOWN])
def test_contradictory_result_cannot_overwrite_committed_effect(
    operation_state: OperationState,
    outcome: ToolOutcome,
) -> None:
    initial = _state(
        _operation(
            state=operation_state,
            effect_state=EffectState.COMMITTED,
        )
    )

    reduced, commands = _reduce(initial, _result_envelope(outcome))

    assert reduced is initial
    assert reduced.operations["op-1"].effect_state == EffectState.COMMITTED
    assert [violation.code for violation in _violations(commands)] == [
        "INVALID_OPERATION_TRANSITION"
    ]


def test_duplicate_success_is_idempotent_for_committed_effect() -> None:
    initial = _state(
        _operation(
            state=OperationState.CANCELLED,
            effect_state=EffectState.COMMITTED,
        )
    )

    reduced, commands = _reduce(initial, _result_envelope(ToolOutcome.SUCCEEDED))

    assert reduced.operations["op-1"].effect_state == EffectState.COMMITTED
    assert _violations(commands) == []


@pytest.mark.parametrize(
    ("outcome", "expected_effect_state"),
    [
        (ToolOutcome.SUCCEEDED, EffectState.COMMITTED),
        (ToolOutcome.FAILED, EffectState.FAILED),
    ],
)
def test_late_result_resolves_unknown_effect(
    outcome: ToolOutcome,
    expected_effect_state: EffectState,
) -> None:
    initial = _state(
        _operation(
            state=OperationState.TIMED_OUT,
            effect_state=EffectState.OUTCOME_UNKNOWN,
        )
    )

    reduced, commands = _reduce(initial, _result_envelope(outcome))

    operation = reduced.operations["op-1"]
    assert operation.state == OperationState.TIMED_OUT
    assert operation.effect_state == expected_effect_state
    assert _violations(commands) == []


def test_duplicate_unknown_result_is_idempotent() -> None:
    initial = _state(
        _operation(
            state=OperationState.TIMED_OUT,
            effect_state=EffectState.OUTCOME_UNKNOWN,
        )
    )

    reduced, commands = _reduce(initial, _result_envelope(ToolOutcome.UNKNOWN))

    assert reduced.operations["op-1"].effect_state == EffectState.OUTCOME_UNKNOWN
    assert _violations(commands) == []


def test_duplicate_failure_is_idempotent_for_failed_effect() -> None:
    initial = _state(
        _operation(
            state=OperationState.FAILED,
            effect_state=EffectState.FAILED,
        )
    )

    reduced, commands = _reduce(initial, _result_envelope(ToolOutcome.FAILED))

    assert reduced.operations["op-1"].effect_state == EffectState.FAILED
    assert _violations(commands) == []


@pytest.mark.parametrize("outcome", [ToolOutcome.SUCCEEDED, ToolOutcome.UNKNOWN])
def test_contradictory_result_cannot_overwrite_failed_effect(
    outcome: ToolOutcome,
) -> None:
    initial = _state(
        _operation(
            state=OperationState.FAILED,
            effect_state=EffectState.FAILED,
        )
    )

    reduced, commands = _reduce(initial, _result_envelope(outcome))

    assert reduced is initial
    assert reduced.operations["op-1"].effect_state == EffectState.FAILED
    assert [violation.code for violation in _violations(commands)] == [
        "INVALID_OPERATION_TRANSITION"
    ]


@pytest.mark.parametrize(
    ("outcome", "reports_contradiction"),
    [
        (ToolOutcome.SUCCEEDED, False),
        (ToolOutcome.FAILED, True),
        (ToolOutcome.UNKNOWN, True),
    ],
)
def test_normal_result_callback_cannot_downgrade_compensated_effect(
    outcome: ToolOutcome,
    reports_contradiction: bool,
) -> None:
    initial = _state(
        _operation(
            state=OperationState.SUCCEEDED,
            effect_state=EffectState.COMPENSATED,
        )
    )

    reduced, commands = _reduce(initial, _result_envelope(outcome))

    assert reduced.operations["op-1"].effect_state == EffectState.COMPENSATED
    assert bool(_violations(commands)) is reports_contradiction


@pytest.mark.parametrize(
    ("operation_state", "effect_state"),
    [
        (OperationState.WAITING, EffectState.IN_FLIGHT),
        (OperationState.SUCCEEDED, EffectState.COMMITTED),
        (OperationState.FAILED, EffectState.FAILED),
        (OperationState.TIMED_OUT, EffectState.OUTCOME_UNKNOWN),
        (OperationState.SUCCEEDED, EffectState.COMPENSATED),
    ],
)
def test_late_dispatch_acceptance_preserves_established_effect_state(
    operation_state: OperationState,
    effect_state: EffectState,
) -> None:
    initial = _state(
        _operation(state=operation_state, effect_state=effect_state)
    )

    reduced, commands = _reduce(initial, _dispatch_accepted_envelope())

    operation = reduced.operations["op-1"]
    assert operation.state == operation_state
    assert operation.effect_state == effect_state
    assert _violations(commands) == []


def test_normal_dispatch_acceptance_moves_effect_in_flight() -> None:
    initial = _state(
        _operation(
            state=OperationState.DISPATCHED,
            effect_state=EffectState.NOT_STARTED,
        )
    )

    reduced, commands = _reduce(initial, _dispatch_accepted_envelope())

    operation = reduced.operations["op-1"]
    assert operation.state == OperationState.WAITING
    assert operation.effect_state == EffectState.IN_FLIGHT
    assert _violations(commands) == []


@pytest.mark.parametrize(
    "effect_state",
    [
        EffectState.COMMITTED,
        EffectState.FAILED,
        EffectState.OUTCOME_UNKNOWN,
        EffectState.COMPENSATED,
    ],
)
def test_dispatch_acceptance_never_downgrades_established_effect(
    effect_state: EffectState,
) -> None:
    initial = _state(
        _operation(
            state=OperationState.DISPATCHED,
            effect_state=effect_state,
        )
    )

    reduced, commands = _reduce(initial, _dispatch_accepted_envelope())

    assert reduced.operations["op-1"].effect_state == effect_state
    assert _violations(commands) == []


def test_replay_suppresses_contradiction_command_without_mutating_state() -> None:
    initial = _state(
        _operation(
            state=OperationState.SUCCEEDED,
            effect_state=EffectState.COMMITTED,
        )
    )

    reduced, commands = _reduce(
        initial,
        _result_envelope(ToolOutcome.FAILED),
        mode=RuntimeMode.REPLAY,
    )

    assert reduced is initial
    assert reduced.operations["op-1"].effect_state == EffectState.COMMITTED
    assert commands == []
