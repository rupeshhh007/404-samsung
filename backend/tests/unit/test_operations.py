"""T-UNK-01, T-IDM-01, T-INV-I13-P, T-INV-I13-N:
timeout is not proof of failure.
"""

from datetime import datetime, timezone

import pytest

from interlock.domain.enums import (
    Authorization, EffectState, EventSource, IntentMaturity, OperationState,
    RuntimeMode,
)
from interlock.domain.models import EventEnvelope, IntentRevision, SessionState
from interlock.execution.descriptors import ToolRegistry
from interlock.execution.operations import OperationError, OperationManager
from interlock.intelligence.intent_graph import bind_dependencies, dependency_fingerprint
from interlock.runtime.reducer import Reducer
from interlock.testing.fixtures import register_tool_manifests


def _operation():
    registry = ToolRegistry()
    register_tool_manifests(registry)
    values = {"center_id": "center-1", "requested_slot": "2026-01-01T11:00:00Z"}
    bindings = bind_dependencies(values, values.keys())
    revision = IntentRevision(
        revision_id="r1", intent_id="intent", values=values,
        maturity=IntentMaturity.COMMITTED, authorization=Authorization.AUTHORIZED,
        created_by_event_id="event", dependency_fingerprint=dependency_fingerprint(bindings),
    )
    operation = OperationManager(registry).create_operation(
        operation_id="op", session_id="s", intent_goal_id="intent",
        intent_revision=revision, bindings=bindings, tool_name="appointment.book",
        arguments=values, existing_operation_ids=set(), known_idempotency_digests={},
    )
    return operation, revision, registry


def test_t_idm_01_operation_identity_and_speculative_write_rejected():
    operation, revision, registry = _operation()
    assert operation.state == OperationState.CREATED
    assert operation.idempotency_key == operation.args["idempotency_key"]
    with pytest.raises(OperationError):
        OperationManager(registry).create_operation(
            operation_id="other", session_id="s", intent_goal_id="intent",
            intent_revision=revision, bindings=bind_dependencies(revision, revision.values),
            tool_name="appointment.book", arguments=revision.values,
            existing_operation_ids=set(), known_idempotency_digests={}, speculative=True,
        )


def test_t_unk_01_t_inv_i13_n_post_dispatch_timeout_remains_unknown():
    operation, _, _ = _operation()
    operation.state = OperationState.WAITING
    operation.effect_state = EffectState.IN_FLIGHT
    operation.provider_request_id = "provider-request"
    operation.dispatch_requested_event_id = "dispatch-event"
    state = SessionState(session_id="s", last_sequence=1, mode=RuntimeMode.TEST,
                         operations={"op": operation})
    timeout = EventEnvelope(
        event_id="timeout", session_id="s", sequence=2,
        event_type="ToolTimedOut", source=EventSource.TOOL,
        occurred_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        logical_time=2, payload={"operation_id": "op", "after_dispatch": True},
    )
    updated, commands = Reducer.reduce(state, timeout)
    assert updated.operations["op"].state == OperationState.TIMED_OUT
    assert updated.operations["op"].effect_state == EffectState.OUTCOME_UNKNOWN
    assert any(command.command_type == "VerifyOutcome" for command in commands)
    assert not any(command.command_type == "DispatchTool" for command in commands)


def test_t_inv_i13_p_correlated_terminal_failure_resolves_unknown_effect():
    operation, _, _ = _operation()
    operation.state = OperationState.TIMED_OUT
    operation.effect_state = EffectState.OUTCOME_UNKNOWN
    operation.provider_request_id = "provider-request"
    operation.dispatch_requested_event_id = "dispatch-event"
    state = SessionState(session_id="s", last_sequence=2, mode=RuntimeMode.TEST,
                         operations={"op": operation})
    failed = EventEnvelope(
        event_id="failed-result", session_id="s", sequence=3,
        event_type="ToolResultObserved", source=EventSource.TOOL,
        occurred_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        logical_time=3,
        payload={"operation_id": "op", "provider_request_id": "provider-request",
                 "outcome": "FAILED", "result": {"status": "BOOKING_FAILED"}},
    )
    updated, commands = Reducer.reduce(state, failed)
    assert updated.operations["op"].state == OperationState.TIMED_OUT
    assert updated.operations["op"].effect_state == EffectState.FAILED
    assert not any(command.command_type == "DispatchTool" for command in commands)
