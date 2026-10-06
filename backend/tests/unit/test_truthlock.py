"""T-TRU-01, T-INV-I6-P, T-INV-I6-N: truth-gated output."""

from datetime import datetime, timezone

from interlock.domain.enums import (
    ClaimCertainty, ClaimState, EvidenceAuthority, EvidenceSource,
    SpeechActType, SpeechState,
)
from interlock.domain.models import ClaimRecord, EvidenceRecord, SpeechAct
from interlock.truth.claims import RULE_APPOINTMENT_BOOKED
from interlock.truth.truthlock import Truthlock


def _claim(state):
    return ClaimRecord(
        claim_id="claim", predicate="appointment_booked",
        subject={"center_id": "ctr-01"}, object={"requested_slot": "2030-01-15T11:00:00+05:30"},
        state=state, required_evidence_rule=RULE_APPOINTMENT_BOOKED,
        intent_revision_id="revision", updated_by_event_id="claim-event",
        supporting_evidence_ids=["proof"] if state == ClaimState.CONFIRMED else [],
    )


def _speech():
    return SpeechAct(
        speech_id="speech", act_type=SpeechActType.RESULT,
        template_id="tmpl_booking_confirmed", slots={"slot": "11:00"},
        claim_ids=["claim"], requested_certainty=ClaimCertainty.CONFIRMED,
        state=SpeechState.PROPOSED, created_by_event_id="proposal",
    )


def test_t_tru_01_t_inv_i6_n_pending_claim_blocks_success_phrase():
    decision = Truthlock().validate(
        speech_act=_speech(), claims={"claim": _claim(ClaimState.PENDING)},
        evidence={}, through_sequence=2, authoritative_sequence=2,
    )
    assert not decision.is_approved
    assert decision.rendered_text is None or "Confirmed" not in decision.rendered_text


def test_t_tru_01_t_inv_i6_p_progress_template_can_be_approved():
    progress = SpeechAct(
        speech_id="progress", act_type=SpeechActType.PROGRESS,
        template_id="tmpl_checking", requested_certainty=ClaimCertainty.PROGRESS,
        state=SpeechState.PROPOSED, created_by_event_id="proposal",
    )
    decision = Truthlock().validate(
        speech_act=progress, claims={}, evidence={},
        through_sequence=2, authoritative_sequence=2,
    )
    assert decision.is_approved
    assert decision.create_approval_event().speech_id == "progress"


def test_t_tru_01_t_inv_i6_p_exact_confirmed_claim_approves_confirmed_template():
    claim = _claim(ClaimState.CONFIRMED)
    evidence = EvidenceRecord(
        evidence_id="proof", source=EvidenceSource.TOOL,
        kind="booking_confirmation",
        captured_at=datetime(2030, 1, 1, tzinfo=timezone.utc),
        content_ref="fixture://booking/apt-11", content_hash="sha256:proof",
        authority=EvidenceAuthority.AUTHORITATIVE,
    )
    decision = Truthlock().validate(
        speech_act=_speech(), claims={"claim": claim}, evidence={"proof": evidence},
        through_sequence=2, authoritative_sequence=2,
    )
    assert decision.is_approved
    assert decision.rendered_text == "Confirmed — your 11:00 appointment is booked."
    approval = decision.create_approval_event()
    assert approval.claim_versions == {"claim": "claim-event"}
    assert approval.through_sequence == 2
