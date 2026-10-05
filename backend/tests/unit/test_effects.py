"""T-WLD-01, T-INV-I4-P, T-INV-I4-N: append-only world effects."""

from datetime import datetime, timezone

from interlock.domain.enums import (
    ActionType, CancellationPolicy, CancellationState, EffectState, EventSource,
    EvidenceAuthority, OperationState, RuntimeMode,
)
from interlock.domain.models import EffectRecord, EventEnvelope, OperationRecord, SessionState
from interlock.runtime.reducer import Reducer


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


def test_t_wld_01_conflicting_physical_observations_request_verification():
    first, _ = _observe(_state(OperationState.SUPERSEDED), _effect())
    second, commands = _observe(first, _effect("other", "12"))
    assert set(second.effects) == {"effect", "other"}
    assert any(command.command_type == "VerifyOutcome"
               and command.provider_effect_id == "booking" for command in commands)
