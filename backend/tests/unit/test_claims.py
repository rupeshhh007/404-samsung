"""T-CLM-01, T-INV-I9-P, T-INV-I9-N: exact booking evidence."""

from datetime import datetime, timezone

from interlock.domain.enums import (
    ClaimState, DivergenceState, EffectState, EvidenceAuthority, EvidenceSource,
    PlanState, PlanStepKind, PlanStepState,
)
from interlock.domain.models import (
    ClaimRecord, DivergenceCase, EffectRecord, EvidenceRecord,
    PlanStep, ReconciliationPlan,
)
from interlock.truth.claims import ClaimEvaluator, RULE_APPOINTMENT_BOOKED


def _claim():
    return ClaimRecord(
        claim_id="booking-claim", predicate="appointment_booked",
        subject={"center_id": "ctr-01"},
        object={"requested_slot": "2030-01-15T11:00:00+05:30",
                "provider_request_id": "req-11", "provider_booking_id": "apt-11",
                "operation_id": "op-11"},
        state=ClaimState.PENDING, required_evidence_rule=RULE_APPOINTMENT_BOOKED,
        intent_revision_id="revision", updated_by_event_id="claim-created",
    )


def test_t_clm_01_t_inv_i9_n_no_effect_cannot_confirm():
    transitions = ClaimEvaluator().evaluate(
        _claim(), effects={}, evidence={}, sequence=1,
        active_intent_revision_id="revision",
    )
    assert all(item.to_state != ClaimState.CONFIRMED for item in transitions)


def test_t_clm_01_pending_claim_cannot_be_serialized_as_confirmed_without_proof():
    from pydantic import ValidationError
    import pytest
    with pytest.raises(ValidationError):
        _claim().model_copy(update={"state": ClaimState.CONFIRMED}).__class__.model_validate(
            {**_claim().model_dump(), "state": ClaimState.CONFIRMED})


def _booking_fact(slot="2030-01-15T11:00:00+05:30", *, evidence_id="confirmation"):
    evidence = EvidenceRecord(
        evidence_id=evidence_id, source=EvidenceSource.TOOL,
        kind="booking_confirmation", captured_at=datetime(2030, 1, 1, tzinfo=timezone.utc),
        content_ref="event:result", content_hash="sha256:result",
        authority=EvidenceAuthority.AUTHORITATIVE,
        provenance={"tool_name": "appointment.book", "provider_effect_id": "apt-11",
                    "provider_request_id": "req-11", "operation_id": "op-11"},
    )
    effect = EffectRecord(
        effect_id=f"effect-{evidence_id}", logical_action_id="action-11",
        operation_id="op-11", provider_effect_id="apt-11",
        effect_type="appointment.booking",
        subject={"resource": "appointment", "ids": ["apt-11"], "center_id": "ctr-01"},
        parameters={"requested_slot": slot, "confirmed_slot": slot},
        state=EffectState.COMMITTED,
        observed_at=datetime(2030, 1, 1, tzinfo=timezone.utc),
        authority=EvidenceAuthority.AUTHORITATIVE, evidence_ids=[evidence_id],
    )
    return effect, evidence


def test_t_clm_01_t_inv_i9_p_exact_authoritative_confirmation_confirms():
    effect, evidence = _booking_fact()
    transitions = ClaimEvaluator().evaluate(
        _claim(), effects={effect.effect_id: effect},
        evidence={evidence.evidence_id: evidence}, sequence=2,
        active_intent_revision_id="revision",
    )
    assert len(transitions) == 1
    assert transitions[0].to_state == ClaimState.CONFIRMED
    assert transitions[0].evidence_ids == ["confirmation"]


def test_t_clm_01_t_inv_i9_n_receipt_and_mismatched_confirmation_never_confirm():
    receipt = EvidenceRecord(
        evidence_id="receipt", source=EvidenceSource.TOOL, kind="request_received",
        captured_at=datetime(2030, 1, 1, tzinfo=timezone.utc),
        content_ref="event:ack", content_hash="sha256:ack",
        authority=EvidenceAuthority.NON_AUTHORITATIVE,
        provenance={"provider_request_id": "req-11"},
    )
    receipt_result = ClaimEvaluator().evaluate(
        _claim(), effects={}, evidence={"receipt": receipt}, sequence=2,
        active_intent_revision_id="revision",
    )
    assert all(item.to_state != ClaimState.CONFIRMED for item in receipt_result)

    effect, evidence = _booking_fact("2030-01-15T12:00:00+05:30", evidence_id="wrong")
    mismatch = ClaimEvaluator().evaluate(
        _claim(), effects={effect.effect_id: effect}, evidence={"wrong": evidence},
        sequence=3, active_intent_revision_id="revision",
    )
    assert len(mismatch) == 1
    assert mismatch[0].to_state == ClaimState.CONTRADICTED
    assert mismatch[0].to_state != ClaimState.CONFIRMED


def test_t_clm_01_reconciliation_requires_completed_exact_verify_final():
    claim = _claim().model_copy(update={
        "object": {**_claim().object, "is_reconciliation": True,
                   "plan_id": "plan", "divergence_id": "div"}
    })
    effect, original = _booking_fact()
    verification = EvidenceRecord(
        evidence_id="verify", source=EvidenceSource.TOOL,
        kind="world_effect_verification",
        captured_at=datetime(2030, 1, 2, tzinfo=timezone.utc),
        content_ref="event:verify", content_hash="sha256:verify",
        authority=EvidenceAuthority.AUTHORITATIVE,
        provenance={"tool_name": "appointment.get", "provider_effect_id": "apt-11",
                    "center_id": "ctr-01",
                    "confirmed_slot": "2030-01-15T11:00:00+05:30"},
    )
    verified = effect.model_copy(update={"effect_id": "effect-verify",
                                         "evidence_ids": ["verify"]})
    divergence = DivergenceCase(
        divergence_id="div", desired_fingerprint="desired",
        observed_effect_ids=["effect-confirmation", "effect-verify"],
        kind="BOOKING_MISMATCH", state=DivergenceState.RESOLVED,
        detected_by_event_id="detected",
    )

    def plan(step_state):
        return ReconciliationPlan(
            plan_id="plan", divergence_id="div", based_on_intent_revision_id="revision",
            provider_capability_hash="sha256:capability", state=PlanState.RUNNING,
            steps=[PlanStep(step_id="verify-final", kind=PlanStepKind.VERIFY_FINAL,
                            tool_name="appointment.get",
                            arguments={"provider_booking_id": "apt-11"},
                            state=step_state)],
        )

    pending = ClaimEvaluator().evaluate(
        claim, effects={verified.effect_id: verified},
        evidence={"verify": verification}, sequence=4,
        active_intent_revision_id="revision", plans={"plan": plan(PlanStepState.PENDING)},
        divergences={"div": divergence}, active_plan_id="plan",
    )
    assert len(pending) == 0 or all(item.to_state != ClaimState.CONFIRMED for item in pending)

    confirmed = ClaimEvaluator().evaluate(
        claim, effects={verified.effect_id: verified},
        evidence={"verify": verification}, sequence=5,
        active_intent_revision_id="revision", plans={"plan": plan(PlanStepState.SUCCEEDED)},
        divergences={"div": divergence}, active_plan_id="plan",
    )
    assert len(confirmed) == 1
    assert confirmed[0].to_state == ClaimState.CONFIRMED
    assert "verify" in confirmed[0].evidence_ids
