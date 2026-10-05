"""T-SPK-01: heard speech and claim invalidation create a correction obligation."""

from datetime import datetime, timezone

from interlock.domain.enums import (
    ClaimCertainty, ClaimState, EventSource, RuntimeMode, SpeechActType, SpeechState,
)
from interlock.domain.models import ClaimRecord, EventEnvelope, SessionState, SpeechAct
from interlock.runtime.reducer import Reducer
from interlock.truth.speech import CorrectionPolicy, validate_correction_proposal


_NOW = datetime(2030, 1, 1, tzinfo=timezone.utc)


def _event(sequence, kind, payload):
    return EventEnvelope(
        event_id=f"event-{sequence}", session_id="s", sequence=sequence,
        event_type=kind, source=EventSource.OUTPUT_ADAPTER,
        occurred_at=_NOW, logical_time=sequence, payload=payload,
    )


def _state():
    claim = ClaimRecord(
        claim_id="claim", predicate="appointment_booked", state=ClaimState.CONFIRMED,
        required_evidence_rule="appointment_booked", supporting_evidence_ids=["proof"],
        intent_revision_id="revision", updated_by_event_id="claim-v1",
    )
    speech = SpeechAct(
        speech_id="speech", act_type=SpeechActType.RESULT,
        template_id="tmpl_booking_confirmed", claim_ids=["claim"],
        requested_certainty=ClaimCertainty.CONFIRMED, state=SpeechState.EMITTING,
        created_by_event_id="proposed", rendered_text="Confirmed — booked.",
        approved_policy_id="truthlock.v1", approved_through_sequence=1,
        approved_claim_versions={"claim": "claim-v1"},
    )
    return SessionState(session_id="s", last_sequence=1, mode=RuntimeMode.TEST,
                        claims={"claim": claim}, speech={"speech": speech})


def test_t_spk_01_heard_then_invalidation_requires_correction():
    heard, _ = Reducer.reduce(_state(), _event(2, "SpeechEmissionFinished",
                                              {"speech_id": "speech", "heard": True}))
    assert heard.speech["speech"].state == SpeechState.EMITTED
    assert heard.speech["speech"].heard is True
    invalidated, commands = Reducer.reduce(
        heard, _event(3, "ClaimStateChanged", {
            "claim_id": "claim", "from_state": "CONFIRMED", "to_state": "STALE",
            "evidence_ids": [], "reason": "provider conflict",
        }),
    )
    assert invalidated.speech["speech"].state == SpeechState.CORRECTION_REQUIRED
    requests = [command for command in commands
                if command.command_type == "RequestSpeechCorrection"
                and command.speech_id == "speech"]
    assert len(requests) == 1
    proposal = CorrectionPolicy().propose(
        requests[0], invalidated, correction_speech_id="correction",
    )
    assert proposal is not None
    assert proposal.speech_act.supersedes_speech_id == "speech"
    assert proposal.speech_act.state == SpeechState.PROPOSED
    assert proposal.claim_versions == {"claim": "event-3"}
    assert validate_correction_proposal(proposal, invalidated) is None


def test_t_spk_01_unheard_failure_does_not_claim_heard_output():
    failed, commands = Reducer.reduce(
        _state(), _event(2, "SpeechEmissionFailed", {
            "speech_id": "speech", "error_code": "OUTPUT_FAILED", "heard": False,
        }),
    )
    assert failed.speech["speech"].heard is False
    assert all(command.command_type != "RequestSpeechCorrection" for command in commands)


def test_t_spk_01_explicit_cancellation_stays_unheard_without_correction():
    pending, cancellation_commands = Reducer.reduce(
        _state(), _event(2, "SpeechCancellationRequested", {"speech_id": "speech"}),
    )
    assert pending.speech["speech"].state == SpeechState.EMITTING
    assert pending.speech["speech"].cancellation_pending is True
    assert pending.speech["speech"].correction_pending is False
    assert any(command.command_type == "CancelSpeech"
               for command in cancellation_commands)
    cancelled, terminal_commands = Reducer.reduce(
        pending, _event(3, "SpeechEmissionFailed", {
            "speech_id": "speech", "error_code": "CANCELLED", "heard": False,
        }),
    )
    assert cancelled.speech["speech"].state == SpeechState.CANCELLED
    assert cancelled.speech["speech"].heard is False
    assert cancelled.speech["speech"].correction_pending is False
    assert all(command.command_type != "RequestSpeechCorrection"
               for command in cancellation_commands + terminal_commands)
