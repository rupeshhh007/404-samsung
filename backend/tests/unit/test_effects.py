"""T-WLD-01, T-INV-I4-P, T-INV-I4-N: append-only world effects."""

from datetime import datetime, timezone

import pytest

from interlock.domain.enums import (
    ActionType, CancellationPolicy, CancellationState, EffectState, EventSource,
    DivergenceState, EvidenceAuthority, OperationState, RuntimeMode, ToolOutcome,
)
from interlock.domain.models import (
    DivergenceCase, EffectRecord, EventEnvelope, OperationRecord, SessionState,
)
from interlock.execution.descriptors import ToolRegistry
from interlock.execution.effects import EffectInterpretationError, EffectInterpreter
from interlock.runtime.reducer import Reducer
from interlock.testing.fixtures import register_tool_manifests


_NOW = datetime(2030, 1, 1, tzinfo=timezone.utc)


def _state(operation_state):
    operation = OperationRecord(
        operation_id="op", tool_name="appointment.book", intent_revision_id="r1",
        fingerprint="fingerprint", action_type=ActionType.REVERSIBLE,
        cancellation_policy=CancellationPolicy.AT_SAFEPOINT,
        state=operation_state, cancellation_state=CancellationState.NONE,
        effect_state=EffectState.OUTCOME_UNKNOWN, speculative=False,
        logical_action_id="action", idempotency_key="key",
        dispatch_requested_event_id="dispatch",
    )
    return SessionState(session_id="s", last_sequence=1, mode=RuntimeMode.TEST,
                        operations={"op": operation})


def _effect(effect_id="effect", slot="11"):
    return EffectRecord(
        effect_id=effect_id, logical_action_id="action", operation_id="op",
        provider_effect_id="booking", effect_type="appointment.booking",
        subject={"resource": "appointment", "ids": ["booking"]},
        parameters={"confirmed_slot": slot}, state=EffectState.COMMITTED,
        observed_at=_NOW, authority=EvidenceAuthority.AUTHORITATIVE,
        evidence_ids=[f"proof-{effect_id}"],
    )


def _observe(state, effect, mode=RuntimeMode.TEST):
    envelope = EventEnvelope(
        event_id=f"event-{state.last_sequence + 1}", session_id="s",
        sequence=state.last_sequence + 1, event_type="WorldEffectObserved",
        source=EventSource.TOOL, occurred_at=_NOW,
        logical_time=state.last_sequence + 1, payload={"effect": effect},
    )
    return Reducer.reduce(state, envelope, mode=mode)


def test_t_wld_01_t_inv_i4_p_confirmed_effect_updates_ledger():
    state, _ = _observe(_state(OperationState.WAITING), _effect())
    assert state.effects["effect"].state == EffectState.COMMITTED
    assert state.operations["op"].effect_state == EffectState.COMMITTED


def test_t_wld_01_t_inv_i4_n_late_effect_kept_without_reactivating_work():
    state, commands = _observe(_state(OperationState.SUPERSEDED), _effect())
    assert state.effects["effect"].state == EffectState.COMMITTED
    assert state.operations["op"].state == OperationState.SUPERSEDED
    assert state.operations["op"].effect_state == EffectState.COMMITTED
    assert all(command.command_type != "DispatchTool" for command in commands)
    replayed, replay_commands = _observe(_state(OperationState.SUPERSEDED),
                                         _effect(), mode=RuntimeMode.REPLAY)
    assert replayed == state
    assert replay_commands == []

    divergence = DivergenceCase(
        divergence_id="late-booking", desired_fingerprint="desired-12",
        observed_effect_ids=["effect"], kind="STALE_BOOKING_COMMITTED",
        state=DivergenceState.OPEN, detected_by_event_id="event-2",
    )
    visible, divergence_commands = Reducer.reduce(state, EventEnvelope(
        event_id="event-3", session_id="s", sequence=3,
        event_type="DivergenceDetected", source=EventSource.SYSTEM,
        occurred_at=_NOW, logical_time=3, payload={"case": divergence},
        causation_id="event-2",
    ))
    assert visible.divergences["late-booking"].state == DivergenceState.OPEN
    assert visible.divergences["late-booking"].observed_effect_ids == ["effect"]
    assert any(command.command_type == "BuildReconciliationPlan"
               for command in divergence_commands)
    assert visible.speech == {}
    assert not any(command.command_type in {"QueueOutput", "EmitOutput"}
                   for command in divergence_commands)


def test_t_wld_01_conflicting_physical_observations_request_verification():
    first, _ = _observe(_state(OperationState.SUPERSEDED), _effect())
    second, commands = _observe(first, _effect("other", "12"))
    assert set(second.effects) == {"effect", "other"}
    assert any(command.command_type == "VerifyOutcome"
               and command.provider_effect_id == "booking" for command in commands)


def _read_observation(tool_name, result):
    registry = ToolRegistry()
    register_tool_manifests(registry)
    descriptor = registry.get(tool_name)
    operation = OperationRecord(
        operation_id=f"op-{tool_name}", tool_name=tool_name, args={},
        intent_revision_id="r1", fingerprint="fingerprint",
        action_type=descriptor.action_type,
        cancellation_policy=descriptor.cancellation_policy,
        state=OperationState.WAITING, cancellation_state=CancellationState.NONE,
        effect_state=EffectState.OUTCOME_UNKNOWN, speculative=False,
        logical_action_id=f"action-{tool_name}", idempotency_key="key",
        descriptor_capability_hash=registry.capability_hash(tool_name),
        provider_request_id="request-read", dispatch_requested_event_id="dispatch",
    )
    source = EventEnvelope(
        event_id="event-read", session_id="s", sequence=2,
        event_type="ToolResultObserved", source=EventSource.TOOL,
        occurred_at=_NOW, logical_time=2,
        payload={
            "operation_id": operation.operation_id,
            "provider_request_id": "request-read",
            "outcome": ToolOutcome.SUCCEEDED,
            "result": result,
        },
    )
    return EffectInterpreter(registry=registry).observe(
        source, operation=operation, known_effects={}, known_evidence={},
    )


@pytest.mark.parametrize(("tool_name", "result"), [
    ("service.find_centers", {
        "phase": "FINAL", "status": "SERVICE_CENTERS_FOUND",
        "provider_request_id": "request-read", "device_id": "device-1",
        "error_code": "E101", "centers": [],
    }),
    ("appointment.availability", {
        "phase": "FINAL", "status": "AVAILABILITY_FOUND",
        "provider_request_id": "request-read", "center_id": "center-1",
        "available_slots": [],
    }),
])
def test_read_only_empty_collections_are_non_authoritative_evidence(tool_name, result):
    candidates = _read_observation(tool_name, result)

    assert len(candidates) == 1
    assert candidates[0].event_type == "EvidenceRecorded"
    evidence = candidates[0].payload["evidence"]
    assert evidence["kind"] == "tool_read_result"
    assert evidence["authority"] == EvidenceAuthority.NON_AUTHORITATIVE


@pytest.mark.parametrize("result", [
    {
        "phase": "FINAL", "status": "AVAILABILITY_FOUND",
        "provider_request_id": "request-read", "center_id": "center-1",
    },
    {
        "phase": "FINAL", "status": "AVAILABILITY_FOUND",
        "provider_request_id": "request-read", "center_id": "",
        "available_slots": [],
    },
])
def test_read_only_missing_or_empty_required_fields_still_fail(result):
    with pytest.raises(EffectInterpretationError):
        _read_observation("appointment.availability", result)
