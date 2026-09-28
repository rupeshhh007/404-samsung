"""Shared reducer regressions for the append-only world-effect boundary."""

from datetime import datetime, timezone

import pytest

from interlock.domain.enums import (
    ActionType,
    CancellationPolicy,
    CancellationState,
    EffectState,
    EventSource,
    EvidenceAuthority,
    EvidenceSource,
    OperationState,
    RuntimeMode,
)
from interlock.domain.models import (
    EffectRecord,
    EvidenceRecord,
    EventEnvelope,
    MetricsSnapshot,
    OperationRecord,
    SessionState,
)
from interlock.runtime.commands import RecordProtocolViolation, VerifyOutcome
from interlock.runtime.reducer import Reducer


_NOW = datetime(2030, 1, 1, tzinfo=timezone.utc)


def _operation(operation_id: str = "op", logical_action_id: str = "action") -> OperationRecord:
    return OperationRecord(
        operation_id=operation_id,
        tool_name="appointment.book",
        args={},
        intent_revision_id="revision",
        fingerprint="fingerprint",
        action_type=ActionType.REVERSIBLE,
        cancellation_policy=CancellationPolicy.AT_SAFEPOINT,
        state=OperationState.SUPERSEDED,
        cancellation_state=CancellationState.NONE,
        effect_state=EffectState.OUTCOME_UNKNOWN,
        speculative=False,
        logical_action_id=logical_action_id,
        idempotency_key=f"key-{logical_action_id}",
        dispatch_requested_event_id=f"dispatch-{operation_id}",
    )


def _state() -> SessionState:
    return SessionState(
        session_id="session",
        last_sequence=1,
        operations={
            "op": _operation(),
            "cancel-op": _operation("cancel-op", "cancel-action"),
        },
        metrics=MetricsSnapshot(session_id="session", through_sequence=1),
    )


def _effect(
    effect_id: str = "effect-1",
    *,
    provider_effect_id: str = "booking-1",
    slot: str = "11:00",
    state: EffectState = EffectState.COMMITTED,
    operation_id: str = "op",
    logical_action_id: str = "action",
    supersedes_effect_id: str | None = None,
    evidence_ids: list[str] | None = None,
) -> EffectRecord:
    return EffectRecord(
        effect_id=effect_id,
        logical_action_id=logical_action_id,
        operation_id=operation_id,
        provider_effect_id=provider_effect_id,
        effect_type="appointment",
        subject={"resource": "appointment", "ids": [provider_effect_id]},
        parameters={"slot": slot},
        state=state,
        observed_at=_NOW,
        authority=EvidenceAuthority.AUTHORITATIVE,
        evidence_ids=evidence_ids or [f"evidence-{effect_id}"],
        supersedes_effect_id=supersedes_effect_id,
    )


def _reduce(
    state: SessionState,
    effect: EffectRecord,
    *,
    replay: bool = False,
    causation_id: str | None = None,
):
    sequence = state.last_sequence + 1
    envelope = EventEnvelope(
        event_id=f"event-{sequence}",
        session_id="session",
        sequence=sequence,
        event_type="WorldEffectObserved",
        source=EventSource.TOOL,
        occurred_at=_NOW,
        logical_time=sequence,
        payload={"effect": effect},
        causation_id=causation_id,
    )
    return Reducer.reduce(state, envelope, RuntimeMode.REPLAY if replay else RuntimeMode.TEST)


def test_first_late_commit_is_detached_and_does_not_reactivate_operation() -> None:
    state = _state()
    caller_effect = _effect()
    next_state, _ = _reduce(state, caller_effect)

    assert next_state.effects["effect-1"] is not caller_effect
    assert next_state.effects["effect-1"].subject is not caller_effect.subject
    assert next_state.effects["effect-1"].subject["ids"] is not caller_effect.subject["ids"]
    caller_effect.parameters["slot"] = "12:00"
    caller_effect.subject["ids"].append("booking-2")
    assert next_state.effects["effect-1"].parameters == {"slot": "11:00"}
    assert next_state.effects["effect-1"].subject["ids"] == ["booking-1"]
    assert next_state.operations["op"].state == OperationState.SUPERSEDED
    assert next_state.operations["op"].effect_state == EffectState.COMMITTED


def test_exact_duplicate_preserves_existing_record() -> None:
    first, _ = _reduce(_state(), _effect())
    original = first.effects["effect-1"]
    second, commands = _reduce(first, _effect())
    assert second.effects["effect-1"] is original
    assert not any(isinstance(command, RecordProtocolViolation) for command in commands)


def test_conflicting_observation_id_cannot_overwrite() -> None:
    first, _ = _reduce(_state(), _effect())
    second, commands = _reduce(first, _effect(slot="11:30"))
    assert second.effects["effect-1"] is first.effects["effect-1"]
    assert second.effects["effect-1"].parameters == {"slot": "11:00"}
    assert any(
        isinstance(command, RecordProtocolViolation)
        and command.code == "IMMUTABLE_EFFECT_VIOLATION"
        for command in commands
    )
    assert second.last_sequence == 3


def test_same_physical_effect_conflict_preserves_both_and_targets_verification() -> None:
    first, _ = _reduce(_state(), _effect())
    second, commands = _reduce(first, _effect("effect-2", slot="11:30"))
    assert {key: value.parameters["slot"] for key, value in second.effects.items()} == {
        "effect-1": "11:00",
        "effect-2": "11:30",
    }
    assert any(
        isinstance(command, VerifyOutcome)
        and command.provider_effect_id == "booking-1"
        for command in commands
    )
    assert second.operations["op"].state == OperationState.SUPERSEDED


def test_authoritative_commit_failure_conflict_verifies_in_either_order() -> None:
    for first_state, second_state in (
        (EffectState.COMMITTED, EffectState.FAILED),
        (EffectState.FAILED, EffectState.COMMITTED),
    ):
        first, _ = _reduce(_state(), _effect(state=first_state))
        second, commands = _reduce(first, _effect("effect-2", state=second_state))
        assert len(second.effects) == 2
        assert any(
            isinstance(command, VerifyOutcome)
            and command.provider_effect_id == "booking-1"
            for command in commands
        )
        assert second.operations["op"].state == OperationState.SUPERSEDED


def test_distinct_physical_effects_for_one_action_are_not_deduplicated() -> None:
    first, _ = _reduce(_state(), _effect())
    second, commands = _reduce(
        first, _effect("effect-2", provider_effect_id="booking-2")
    )
    assert len(second.effects) == 2
    targets = {
        (command.operation_id, command.provider_effect_id)
        for command in commands
        if isinstance(command, VerifyOutcome)
    }
    assert targets == {("op", "booking-1"), ("op", "booking-2")}


def test_three_physical_effects_are_individually_targetable() -> None:
    state, _ = _reduce(_state(), _effect())
    state, _ = _reduce(state, _effect("effect-2", provider_effect_id="booking-2"))
    state, commands = _reduce(
        state, _effect("effect-3", provider_effect_id="booking-3")
    )
    assert len(state.effects) == 3
    assert {
        command.provider_effect_id
        for command in commands
        if isinstance(command, VerifyOutcome)
    } == {"booking-1", "booking-2", "booking-3"}


@pytest.mark.parametrize("verified_slot", ["11:00", "11:30"])
def test_scoped_verification_retains_conflict_history_without_reverifying(
    verified_slot: str,
) -> None:
    state, _ = _reduce(_state(), _effect())
    state, commands = _reduce(state, _effect("effect-2", slot="11:30"))
    assert any(isinstance(command, VerifyOutcome) for command in commands)
    evidence = EvidenceRecord(
        evidence_id="verification-evidence",
        source=EvidenceSource.TOOL,
        kind="world_effect_verification",
        captured_at=_NOW,
        content_ref="provider-readback-1",
        content_hash="readback-hash-1",
        authority=EvidenceAuthority.AUTHORITATIVE,
        provenance={
            "provider_effect_id": "booking-1",
            "verification_request_event_id": "event-3",
            "provider_request_id": "readback-request-1",
            "verification_of_effect_ids": ["effect-1", "effect-2"],
        },
    )
    sequence = state.last_sequence + 1
    evidence_event = EventEnvelope(
        event_id=f"event-{sequence}",
        session_id="session",
        sequence=sequence,
        event_type="EvidenceRecorded",
        source=EventSource.TOOL,
        occurred_at=_NOW,
        logical_time=sequence,
        payload={"evidence": evidence},
        causation_id="event-3",
    )
    state, _ = Reducer.reduce(state, evidence_event, RuntimeMode.TEST)
    state, commands = _reduce(
        state,
        _effect("effect-3", slot=verified_slot, evidence_ids=["verification-evidence"]),
        causation_id="event-3",
    )
    assert set(state.effects) == {"effect-1", "effect-2", "effect-3"}
    assert state.effects["effect-1"].parameters == {"slot": "11:00"}
    assert state.effects["effect-2"].parameters == {"slot": "11:30"}
    assert state.effects["effect-3"].parameters == {"slot": verified_slot}
    assert state.operations["op"].state == OperationState.SUPERSEDED
    assert not any(isinstance(command, VerifyOutcome) for command in commands)

    state, commands = _reduce(state, _effect("effect-4", slot="12:00"))
    assert any(isinstance(command, VerifyOutcome) for command in commands)


def test_later_unscoped_claim_does_not_suppress_verification() -> None:
    state, _ = _reduce(_state(), _effect())
    state, _ = _reduce(state, _effect("effect-2", slot="11:30"))
    state, commands = _reduce(
        state, _effect("effect-3"), causation_id="event-3"
    )
    assert len(state.effects) == 3
    assert any(isinstance(command, VerifyOutcome) for command in commands)


def test_incomplete_verification_provenance_still_requests_verification() -> None:
    state, _ = _reduce(_state(), _effect())
    state, _ = _reduce(state, _effect("effect-2", slot="11:30"))
    evidence = EvidenceRecord(
        evidence_id="incomplete-verification",
        source=EvidenceSource.TOOL,
        kind="world_effect_verification",
        captured_at=_NOW,
        content_ref="provider-readback-2",
        content_hash="readback-hash-2",
        authority=EvidenceAuthority.AUTHORITATIVE,
        provenance={
            "provider_effect_id": "booking-1",
            "verification_request_event_id": "event-3",
            "provider_request_id": "readback-request-2",
            "verification_of_effect_ids": ["effect-1"],
        },
    )
    sequence = state.last_sequence + 1
    state, _ = Reducer.reduce(
        state,
        EventEnvelope(
            event_id=f"event-{sequence}",
            session_id="session",
            sequence=sequence,
            event_type="EvidenceRecorded",
            source=EventSource.TOOL,
            occurred_at=_NOW,
            logical_time=sequence,
            payload={"evidence": evidence},
            causation_id="event-3",
        ),
        RuntimeMode.TEST,
    )
    state, commands = _reduce(
        state,
        _effect("effect-3", evidence_ids=["incomplete-verification"]),
        causation_id="event-3",
    )
    assert set(state.effects) == {"effect-1", "effect-2", "effect-3"}
    assert any(isinstance(command, VerifyOutcome) for command in commands)


def test_weak_later_uncertainty_cannot_downgrade_committed_truth() -> None:
    first, _ = _reduce(_state(), _effect())
    uncertain = _effect("effect-2", state=EffectState.OUTCOME_UNKNOWN)
    uncertain.authority = EvidenceAuthority.NON_AUTHORITATIVE
    second, commands = _reduce(first, uncertain)
    assert second.operations["op"].effect_state == EffectState.COMMITTED
    assert second.effects["effect-1"].state == EffectState.COMMITTED
    assert not any(isinstance(command, VerifyOutcome) for command in commands)


def test_compensation_appends_history_and_updates_original_effect_dimension() -> None:
    first, _ = _reduce(_state(), _effect())
    compensation = _effect(
        "effect-cancel",
        state=EffectState.COMPENSATED,
        operation_id="cancel-op",
        logical_action_id="cancel-action",
        supersedes_effect_id="effect-1",
    )
    second, _ = _reduce(first, compensation)
    assert second.effects["effect-1"].state == EffectState.COMMITTED
    assert second.effects["effect-cancel"].state == EffectState.COMPENSATED
    assert second.operations["op"].effect_state == EffectState.COMPENSATED
    assert second.operations["op"].state == OperationState.SUPERSEDED


def test_commit_after_confirmed_compensation_requests_physical_verification() -> None:
    committed, _ = _reduce(_state(), _effect())
    compensated, _ = _reduce(
        committed,
        _effect(
            "effect-cancel",
            state=EffectState.COMPENSATED,
            operation_id="cancel-op",
            logical_action_id="cancel-action",
            supersedes_effect_id="effect-1",
        ),
    )
    next_state, commands = _reduce(compensated, _effect("effect-2"))
    assert set(next_state.effects) == {"effect-1", "effect-cancel", "effect-2"}
    assert next_state.effects["effect-cancel"].state == EffectState.COMPENSATED
    assert next_state.operations["op"].state == OperationState.SUPERSEDED
    assert any(
        isinstance(command, VerifyOutcome)
        and command.provider_effect_id == "booking-1"
        for command in commands
    )


def test_unmatched_compensation_and_operation_are_rejected() -> None:
    state = _state()
    bad_compensation = _effect(
        "effect-cancel",
        state=EffectState.COMPENSATED,
        operation_id="cancel-op",
        logical_action_id="cancel-action",
        supersedes_effect_id="missing",
    )
    next_state, commands = _reduce(state, bad_compensation)
    assert next_state.effects == {}
    assert any(
        isinstance(command, RecordProtocolViolation)
        and command.code == "INVALID_EFFECT_COMPENSATION"
        for command in commands
    )

    bad_operation = _effect(operation_id="absent")
    next_state, commands = _reduce(state, bad_operation)
    assert next_state.effects == {}
    assert any(
        isinstance(command, RecordProtocolViolation)
        and command.code == "INVALID_EFFECT_CORRELATION"
        for command in commands
    )


def test_duplicate_and_conflicting_compensation_observations() -> None:
    committed, _ = _reduce(_state(), _effect())
    first_compensation = _effect(
        "effect-cancel-1",
        state=EffectState.COMPENSATED,
        operation_id="cancel-op",
        logical_action_id="cancel-action",
        supersedes_effect_id="effect-1",
    )
    compensated, _ = _reduce(committed, first_compensation)
    duplicate, commands = _reduce(compensated, first_compensation)
    assert duplicate.effects["effect-cancel-1"] is compensated.effects["effect-cancel-1"]
    assert not any(isinstance(command, VerifyOutcome) for command in commands)

    conflicting = _effect(
        "effect-cancel-2",
        slot="11:30",
        state=EffectState.COMPENSATED,
        operation_id="cancel-op",
        logical_action_id="cancel-action",
        supersedes_effect_id="effect-1",
    )
    uncertain, commands = _reduce(duplicate, conflicting)
    assert len(uncertain.effects) == 3
    assert uncertain.effects["effect-1"].state == EffectState.COMMITTED
    assert any(
        isinstance(command, VerifyOutcome)
        and command.provider_effect_id == "booking-1"
        for command in commands
    )


def test_unknown_compensation_requests_targeted_verification() -> None:
    committed, _ = _reduce(_state(), _effect())
    unknown = _effect(
        "effect-cancel-unknown",
        state=EffectState.OUTCOME_UNKNOWN,
        operation_id="cancel-op",
        logical_action_id="cancel-action",
        supersedes_effect_id="effect-1",
    )
    unknown.authority = EvidenceAuthority.NON_AUTHORITATIVE
    next_state, commands = _reduce(committed, unknown)
    assert next_state.effects["effect-1"].state == EffectState.COMMITTED
    assert next_state.operations["op"].effect_state == EffectState.COMMITTED
    assert any(
        isinstance(command, VerifyOutcome)
        and command.provider_effect_id == "booking-1"
        for command in commands
    )


def test_failed_compensation_preserves_committed_booking() -> None:
    committed, _ = _reduce(_state(), _effect())
    failed = _effect(
        "effect-cancel-failed",
        state=EffectState.FAILED,
        operation_id="cancel-op",
        logical_action_id="cancel-action",
        supersedes_effect_id="effect-1",
    )
    next_state, commands = _reduce(committed, failed)
    assert next_state.effects["effect-1"].state == EffectState.COMMITTED
    assert next_state.effects["effect-cancel-failed"].state == EffectState.FAILED
    assert next_state.operations["op"].effect_state == EffectState.COMMITTED
    assert any(
        isinstance(command, VerifyOutcome)
        and command.provider_effect_id == "booking-1"
        for command in commands
    )


def test_late_timeout_cannot_downgrade_authoritative_commit() -> None:
    committed, _ = _reduce(_state(), _effect())
    envelope = EventEnvelope(
        event_id="event-timeout",
        session_id="session",
        sequence=committed.last_sequence + 1,
        event_type="ToolTimedOut",
        source=EventSource.TOOL,
        occurred_at=_NOW,
        logical_time=3,
        payload={"operation_id": "op", "after_dispatch": True},
    )
    next_state, commands = Reducer.reduce(committed, envelope, RuntimeMode.TEST)
    assert next_state.operations["op"].state == OperationState.SUPERSEDED
    assert next_state.operations["op"].effect_state == EffectState.COMMITTED
    assert not any(isinstance(command, VerifyOutcome) for command in commands)


def test_operation_only_verification_remains_backward_compatible() -> None:
    command = VerifyOutcome(session_id="session", operation_id="op")
    assert command.provider_effect_id is None


def test_invalid_effect_cannot_leak_raw_payload_in_violation_digest() -> None:
    state = _state()
    envelope = EventEnvelope(
        event_id="event-invalid",
        session_id="session",
        sequence=2,
        event_type="WorldEffectObserved",
        source=EventSource.TOOL,
        occurred_at=_NOW,
        logical_time=2,
        payload={"effect": {"effect_id": "sensitive-provider-token"}},
    )
    next_state, commands = Reducer.reduce(state, envelope, RuntimeMode.TEST)
    assert next_state is state
    assert len(commands) == 1
    assert isinstance(commands[0], RecordProtocolViolation)
    assert commands[0].code == "REDUCER_TRANSITION_ERROR"
    assert "sensitive-provider-token" not in commands[0].digest


def test_replay_is_deterministic_and_emits_no_commands() -> None:
    effects = (_effect(), _effect("effect-2", slot="11:30"))
    first = _state()
    second = _state()
    for effect in effects:
        first, commands = _reduce(first, effect, replay=True)
        assert commands == []
        second, commands = _reduce(second, effect, replay=True)
        assert commands == []
    assert first.model_dump(mode="json") == second.model_dump(mode="json")
