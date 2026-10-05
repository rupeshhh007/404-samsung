"""T-CLM-01, T-INV-I9-P, T-INV-I9-N: exact booking evidence."""

from interlock.domain.enums import ClaimState
from interlock.domain.models import ClaimRecord
from interlock.truth.claims import ClaimEvaluator, RULE_APPOINTMENT_BOOKED


def _claim():
    return ClaimRecord(
        claim_id="booking-claim", predicate="appointment_booked",
        subject={"center_id": "ctr-01"}, object={"requested_slot": "2030-01-15T11:00:00+05:30"},
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
