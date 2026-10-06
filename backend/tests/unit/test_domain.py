"""T-DOM-01: strict canonical domain serialization."""

import pytest
from pydantic import ValidationError

from interlock.domain.enums import (
    ActionType, CancellationPolicy, CancellationState, EffectState, OperationState,
)
from interlock.domain.models import OperationRecord


def test_t_dom_01_operation_round_trip_and_illegal_fields():
    operation = OperationRecord(
        operation_id="op-1", tool_name="lookup", intent_revision_id="rev-1",
        fingerprint="fingerprint", action_type=ActionType.READ_ONLY,
        cancellation_policy=CancellationPolicy.IMMEDIATE,
        state=OperationState.CREATED, cancellation_state=CancellationState.NONE,
        effect_state=EffectState.NOT_STARTED, speculative=False,
        logical_action_id="action-1", idempotency_key="key-1",
    )
    assert OperationRecord.model_validate_json(operation.model_dump_json()) == operation
    with pytest.raises(ValidationError):
        OperationRecord.model_validate({**operation.model_dump(), "unexpected": True})
    with pytest.raises(ValidationError):
        OperationRecord.model_validate({**operation.model_dump(), "speculative": True,
                                        "action_type": ActionType.IRREVERSIBLE})


def test_t_dom_01_core_entities_round_trip_and_invalid_combinations_rejected():
    from datetime import datetime, timezone
    from interlock.domain.enums import (
        Authorization, ClaimState, DivergenceState,
        EvidenceAuthority, EvidenceSource, IntentMaturity,
        SpeechActType, SpeechState,
    )
    from interlock.domain.models import (
        ClaimRecord, DivergenceCase, EffectRecord, EvidenceRecord,
        IntentRevision, ScenarioStep, SpeechAct,
    )

    _now = datetime(2030, 1, 1, 12, 0, tzinfo=timezone.utc)

    # IntentRevision
    rev = IntentRevision(
        revision_id="rev-1", intent_id="intent-1",
        maturity=IntentMaturity.COMMITTED, authorization=Authorization.AUTHORIZED,
        created_by_event_id="evt-1", dependency_fingerprint="fp-1",
        values={"slot": "12:00"},
    )
    assert IntentRevision.model_validate_json(rev.model_dump_json()) == rev
    with pytest.raises(ValidationError):
        IntentRevision.model_validate({**rev.model_dump(), "unknown_prop": 123})
    with pytest.raises(ValidationError):
        IntentRevision.model_validate({**rev.model_dump(), "maturity": "INVALID_MATURITY"})

    # EffectRecord: COMMITTED requires AUTHORITATIVE and nonempty evidence_ids
    effect = EffectRecord(
        effect_id="eff-1", logical_action_id="act-1", operation_id="op-1",
        provider_effect_id="apt-12", effect_type="booking",
        state=EffectState.COMMITTED, observed_at=_now,
        authority=EvidenceAuthority.AUTHORITATIVE, evidence_ids=["ev-1"],
    )
    assert EffectRecord.model_validate_json(effect.model_dump_json()) == effect
    with pytest.raises(ValidationError):
        EffectRecord.model_validate({**effect.model_dump(), "authority": EvidenceAuthority.NON_AUTHORITATIVE})
    with pytest.raises(ValidationError):
        EffectRecord.model_validate({**effect.model_dump(), "evidence_ids": []})
    with pytest.raises(ValidationError):
        EffectRecord.model_validate({**effect.model_dump(), "extra_field": "disallowed"})

    # EvidenceRecord
    ev = EvidenceRecord(
        evidence_id="ev-1", source=EvidenceSource.TOOL, kind="booking_confirmation",
        captured_at=_now, content_ref="fixture://booking/apt-12", content_hash="sha256:hash",
        authority=EvidenceAuthority.AUTHORITATIVE,
    )
    assert EvidenceRecord.model_validate_json(ev.model_dump_json()) == ev
    with pytest.raises(ValidationError):
        EvidenceRecord.model_validate({**ev.model_dump(), "source": "INVALID_SOURCE"})
    with pytest.raises(ValidationError):
        EvidenceRecord.model_validate({**ev.model_dump(), "illegal": True})

    # ClaimRecord: CONFIRMED requires supporting_evidence_ids
    claim = ClaimRecord(
        claim_id="clm-1", predicate="appointment.booked",
        state=ClaimState.CONFIRMED, required_evidence_rule="RULE_APPOINTMENT_BOOKED",
        supporting_evidence_ids=["ev-1"], intent_revision_id="rev-1",
        updated_by_event_id="evt-2",
    )
    assert ClaimRecord.model_validate_json(claim.model_dump_json()) == claim
    with pytest.raises(ValidationError):
        ClaimRecord.model_validate({**claim.model_dump(), "supporting_evidence_ids": []})
    with pytest.raises(ValidationError):
        ClaimRecord.model_validate({**claim.model_dump(), "bad": 99})

    # SpeechAct
    speech = SpeechAct(
        speech_id="sp-1", act_type=SpeechActType.RESULT, template_id="tpl-1",
        requested_certainty="CONFIRMED", state=SpeechState.PROPOSED,
        created_by_event_id="evt-3",
    )
    assert SpeechAct.model_validate_json(speech.model_dump_json()) == speech
    with pytest.raises(ValidationError):
        SpeechAct.model_validate({**speech.model_dump(), "act_type": "UNKNOWN_ACT"})
    with pytest.raises(ValidationError):
        SpeechAct.model_validate({**speech.model_dump(), "extra": "forbidden"})

    # DivergenceCase
    div = DivergenceCase(
        divergence_id="div-1", desired_fingerprint="fp-12", observed_effect_ids=["eff-1"],
        kind="STALE_BOOKING_COMMITTED", state=DivergenceState.OPEN,
        detected_by_event_id="evt-4",
    )
    assert DivergenceCase.model_validate_json(div.model_dump_json()) == div
    with pytest.raises(ValidationError):
        DivergenceCase.model_validate({**div.model_dump(), "state": "NONEXISTENT_STATE"})

    # ScenarioStep: exactly one of input, advance_to, assert_
    step_input = ScenarioStep(input={"text": "hello"})
    assert step_input.input == {"text": "hello"}
    step_advance = ScenarioStep(advance_to=500)
    assert step_advance.advance_to == 500
    with pytest.raises(ValidationError):
        ScenarioStep(input={"text": "hi"}, advance_to=500)
    with pytest.raises(ValidationError):
        ScenarioStep()
