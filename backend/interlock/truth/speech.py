"""TRU-004: deterministic policy for proposing corrective speech.

The reducer owns speech lifecycle transitions and emits ``RequestSpeechCorrection``
only after audible output has reached ``CORRECTION_REQUIRED``.  This module
consumes that canonical obligation and constructs a new, sequence-pinned
``PROPOSED`` SpeechAct.  It performs no I/O and never mutates reducer state.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional

from pydantic import Field

from interlock.domain.enums import (
    ClaimCertainty,
    ClaimState,
    SpeechActType,
    SpeechState,
)
from interlock.domain.models import ClaimRecord, DomainBaseModel, SessionState, SpeechAct
from interlock.runtime.commands import RequestSpeechCorrection


_CORRECTION_STATE_TEXT = {
    ClaimState.CONTRADICTED: (
        "the previous statement is contradicted by current verified evidence"
    ),
    ClaimState.UNCERTAIN: "the previous statement can no longer be verified",
    ClaimState.STALE: "the previous statement is no longer supported by current evidence",
    ClaimState.SUPERSEDED: "the previous statement is no longer current",
}


class CorrectionProposal(DomainBaseModel):
    """Canonical Owner-D proposal and its current ClaimGraph proof."""

    request: RequestSpeechCorrection
    speech_act: SpeechAct
    through_sequence: int = Field(..., ge=1)
    claim_versions: Dict[str, str] = Field(default_factory=dict)


@dataclass(frozen=True)
class _CorrectionContext:
    prior_speech: SpeechAct
    current_claim: ClaimRecord
    current_state_text: str


def _resolve_context(
    request: RequestSpeechCorrection,
    state: SessionState,
    *,
    exclude_speech_id: Optional[str] = None,
) -> Optional[_CorrectionContext]:
    """Resolve a correction obligation against authoritative reducer state."""

    if request.session_id != state.session_id or state.last_sequence < 1:
        return None

    prior = state.speech.get(request.speech_id)
    if prior is None or prior.speech_id != request.speech_id:
        return None
    if prior.state != SpeechState.CORRECTION_REQUIRED or prior.heard is not True:
        return None
    if prior.act_type == SpeechActType.CORRECTION:
        # ADR-018 does not explicitly authorize correction-of-correction chains.
        return None
    if (
        not prior.rendered_text
        or not prior.approved_policy_id
        or prior.approved_through_sequence is None
        or not prior.approved_claim_versions
    ):
        return None

    triggering_claim_id = request.triggering_claim_id
    if (
        triggering_claim_id not in prior.claim_ids
        or triggering_claim_id not in prior.approved_claim_versions
    ):
        return None

    current_claim = state.claims.get(triggering_claim_id)
    if current_claim is None or current_claim.claim_id != triggering_claim_id:
        return None
    if (
        current_claim.updated_by_event_id
        == prior.approved_claim_versions[triggering_claim_id]
    ):
        return None

    try:
        current_claim_state = ClaimState(current_claim.state)
    except ValueError:
        return None
    current_state_text = _CORRECTION_STATE_TEXT.get(current_claim_state)
    if current_state_text is None:
        return None

    evidence_ids = tuple(current_claim.supporting_evidence_ids)
    if (
        current_claim_state in (ClaimState.CONTRADICTED, ClaimState.UNCERTAIN)
        and not evidence_ids
    ):
        return None
    for evidence_id in evidence_ids:
        evidence = state.evidence.get(evidence_id)
        if evidence is None or evidence.evidence_id != evidence_id:
            return None

    corrections = [
        speech
        for speech in state.speech.values()
        if speech.act_type == SpeechActType.CORRECTION
        and speech.supersedes_speech_id == prior.speech_id
        and speech.speech_id != exclude_speech_id
    ]
    if corrections:
        return None

    return _CorrectionContext(
        prior_speech=prior,
        current_claim=current_claim,
        current_state_text=current_state_text,
    )


class CorrectionPolicy:
    """Create a truth-bound correction proposal from a reducer obligation."""

    def propose(
        self,
        request: RequestSpeechCorrection,
        state: SessionState,
        *,
        correction_speech_id: str,
    ) -> Optional[CorrectionProposal]:
        """Return one new correction proposal, or ``None`` when proof is insufficient."""

        if not correction_speech_id or correction_speech_id in state.speech:
            return None

        context = _resolve_context(request, state)
        if context is None:
            return None

        current_claim = context.current_claim
        speech_act = SpeechAct(
            speech_id=correction_speech_id,
            act_type=SpeechActType.CORRECTION,
            template_id="tmpl_correction",
            slots={
                "previous_statement": context.prior_speech.rendered_text,
                "current_state": context.current_state_text,
            },
            claim_ids=[current_claim.claim_id],
            requested_certainty=ClaimCertainty.CONFIRMED,
            state=SpeechState.PROPOSED,
            created_by_event_id=current_claim.updated_by_event_id,
            supersedes_speech_id=context.prior_speech.speech_id,
        )
        return CorrectionProposal(
            request=request.model_copy(deep=True),
            speech_act=speech_act,
            through_sequence=state.last_sequence,
            claim_versions={
                current_claim.claim_id: current_claim.updated_by_event_id,
            },
        )


def validate_correction_proposal(
    proposal: CorrectionProposal,
    state: Optional[SessionState],
) -> Optional[str]:
    """Return a fail-closed reason, or ``None`` for exact canonical linkage."""

    if state is None:
        return "Canonical correction validation requires authoritative SessionState"

    context = _resolve_context(
        proposal.request,
        state,
        exclude_speech_id=proposal.speech_act.speech_id,
    )
    if context is None:
        return "Correction request does not resolve to a unique canonical obligation"

    act = proposal.speech_act
    stored = state.speech.get(act.speech_id)
    if stored is not None and stored != act:
        return "Correction speech ID conflicts with a different stored SpeechAct"
    expected_versions = {
        context.current_claim.claim_id: context.current_claim.updated_by_event_id,
    }
    if proposal.through_sequence != state.last_sequence:
        return "Correction proposal sequence does not match authoritative state"
    if proposal.claim_versions != expected_versions:
        return "Correction proposal claim versions do not match current ClaimGraph"
    if act.state != SpeechState.PROPOSED:
        return "Correction SpeechAct must start in PROPOSED"
    if act.act_type != SpeechActType.CORRECTION or act.template_id != "tmpl_correction":
        return "Correction SpeechAct must use the canonical correction template"
    if act.supersedes_speech_id != context.prior_speech.speech_id:
        return "Correction lineage does not match the prior emitted speech"
    if act.claim_ids != [context.current_claim.claim_id]:
        return "Correction claim IDs do not match the triggering current claim"
    if act.requested_certainty != ClaimCertainty.CONFIRMED:
        return "Correction certainty does not match the controlled template"
    if act.created_by_event_id != context.current_claim.updated_by_event_id:
        return "Correction creation event does not match the current claim version"
    if act.slots != {
        "previous_statement": context.prior_speech.rendered_text,
        "current_state": context.current_state_text,
    }:
        return "Correction wording is not derived from canonical speech and claim state"
    if any(
        value is not None
        for value in (
            act.rendered_text,
            act.approved_policy_id,
            act.approved_through_sequence,
            act.heard,
        )
    ) or act.approved_claim_versions or act.cancellation_pending or act.correction_pending:
        return "Correction proposal contains lifecycle proof reserved for reducer approval"
    return None


def validate_correction_speech_act(
    speech_act: SpeechAct,
    state: Optional[SessionState],
) -> Optional[str]:
    """Validate a reducer-stored correction by re-deriving all canonical operands."""

    if state is None:
        return "Canonical correction validation requires authoritative SessionState"
    stored = state.speech.get(speech_act.speech_id)
    if stored is None or stored != speech_act:
        return "Correction SpeechAct is not the canonical reducer-stored proposal"
    if not speech_act.supersedes_speech_id or len(speech_act.claim_ids) != 1:
        return "Correction SpeechAct lacks unique prior-speech and triggering-claim linkage"

    request = RequestSpeechCorrection(
        session_id=state.session_id,
        speech_id=speech_act.supersedes_speech_id,
        triggering_claim_id=speech_act.claim_ids[0],
    )
    claim = state.claims.get(speech_act.claim_ids[0])
    if claim is None:
        return "Correction triggering claim is absent from authoritative state"
    proposal = CorrectionProposal(
        request=request,
        speech_act=speech_act,
        through_sequence=state.last_sequence,
        claim_versions={claim.claim_id: claim.updated_by_event_id},
    )
    return validate_correction_proposal(proposal, state)
