"""TRU-004: deterministic policy for proposing corrective speech.

The reducer owns speech lifecycle transitions and emits ``RequestSpeechCorrection``
only after audible output has reached ``CORRECTION_REQUIRED``.  This module
consumes that canonical obligation and constructs a new, sequence-pinned
``PROPOSED`` SpeechAct.  It performs no I/O and never mutates reducer state.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional

from pydantic import Field

from interlock.domain.enums import (
    ClaimCertainty,
    ClaimState,
    SpeechActType,
    SpeechState,
)
from interlock.domain.models import ClaimRecord, DomainBaseModel, SessionState, SpeechAct
from interlock.runtime.commands import RequestSpeechCorrection
from interlock.truth.claims import (
    RULE_APPOINTMENT_BOOKED,
    RULE_APPOINTMENT_CANCELLED,
    RULE_REQUEST_RECEIVED,
    RULE_SLOT_AVAILABLE,
    _extract_claim_parameters,
    normalize_rule_name,
)


_CORRECTION_STATE_TEXT = {
    ClaimState.CONTRADICTED: (
        "the previous statement is contradicted by current verified evidence"
    ),
    ClaimState.UNCERTAIN: "the previous statement can no longer be verified",
    ClaimState.STALE: "the previous statement is no longer supported by current evidence",
    ClaimState.SUPERSEDED: "the previous statement is no longer current",
}


def _controlled_text(value: Any) -> Optional[str]:
    """Return one bounded scalar value suitable for a controlled correction template."""

    if isinstance(value, datetime):
        return value.isoformat()
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text or len(text) > 256 or any(character in text for character in "\r\n"):
        return None
    return text


def _first_controlled_text(params: Dict[str, Any], *keys: str) -> Optional[str]:
    for key in keys:
        value = _controlled_text(params.get(key))
        if value is not None:
            return value
    return None


def _render_confirmed_fact(claim: ClaimRecord) -> Optional[str]:
    """Render the minimum fact proven by each canonical ClaimGraph rule."""

    rule = normalize_rule_name(claim.required_evidence_rule)
    params = _extract_claim_parameters(claim)

    if rule == RULE_APPOINTMENT_BOOKED:
        center_id = _controlled_text(params.get("center_id"))
        slot_value = (
            params.get("confirmed_slot")
            or params.get("requested_slot")
            or params.get("slot")
        )
        slot = _controlled_text(slot_value)
        provider_request_id = _first_controlled_text(
            params, "provider_request_id", "request_id"
        )
        provider_booking_id = _first_controlled_text(
            params, "provider_booking_id", "booking_id", "resource_id"
        )
        is_reconciliation = bool(
            params.get("is_reconciliation", False)
            or "plan_id" in params
            or "divergence_id" in params
        )
        if is_reconciliation:
            plan_id = _controlled_text(params.get("plan_id"))
            divergence_id = _controlled_text(params.get("divergence_id"))
            if (
                plan_id is None
                or divergence_id is None
                or provider_booking_id is None
                or center_id is None
                or slot is None
            ):
                return None
        elif provider_request_id is None or center_id is None or slot is None:
            return None
        return f"the appointment at center {center_id} is booked for {slot}"

    if rule == RULE_APPOINTMENT_CANCELLED:
        lineage_identity = _first_controlled_text(
            params,
            "provider_booking_id",
            "provider_request_id",
            "logical_action_id",
        )
        if lineage_identity is None:
            return None
        center_id = _controlled_text(params.get("center_id"))
        slot = _controlled_text(params.get("confirmed_slot") or params.get("slot"))
        if slot is not None and center_id is not None:
            return f"the appointment for {slot} at center {center_id} is cancelled"
        if slot is not None:
            return f"the appointment for {slot} is cancelled"
        if center_id is not None:
            return f"the appointment at center {center_id} is cancelled"
        return "the appointment is cancelled"

    if rule == RULE_SLOT_AVAILABLE:
        slot = _first_controlled_text(params, "slot", "requested_slot")
        center_id = _controlled_text(params.get("center_id"))
        if slot is not None and center_id is not None:
            return f"the {slot} slot at center {center_id} is available"
        if slot is not None:
            return f"the {slot} slot is available"
        if center_id is not None:
            return f"a slot at center {center_id} is available"
        return "a slot is available"

    if rule == RULE_REQUEST_RECEIVED:
        return "the service received the request"

    return None


def _render_current_state(claim: ClaimRecord) -> Optional[str]:
    try:
        claim_state = ClaimState(claim.state)
    except ValueError:
        return None
    if claim_state == ClaimState.CONFIRMED:
        return _render_confirmed_fact(claim)
    return _CORRECTION_STATE_TEXT.get(claim_state)


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


class _CorrectionObligationStatus(str, Enum):
    NONE = "NONE"
    LIVE = "LIVE"
    SATISFIED_HEARD = "SATISFIED_HEARD"
    DEAD_NON_HEARD = "DEAD_NON_HEARD"
    MALFORMED = "MALFORMED"


def _has_complete_approval_proof(speech: SpeechAct) -> bool:
    return bool(
        speech.rendered_text
        and speech.approved_policy_id
        and speech.approved_through_sequence is not None
        and speech.approved_claim_versions
        and set(speech.approved_claim_versions) == set(speech.claim_ids)
    )


def _has_any_approval_proof(speech: SpeechAct) -> bool:
    return bool(
        speech.rendered_text is not None
        or speech.approved_policy_id is not None
        or speech.approved_through_sequence is not None
        or speech.approved_claim_versions
    )


def _classify_correction_child(child: SpeechAct) -> _CorrectionObligationStatus:
    """Classify one historical attempt using reducer-owned lifecycle/heard facts."""

    try:
        child_state = SpeechState(child.state)
    except ValueError:
        return _CorrectionObligationStatus.MALFORMED

    if child.correction_pending and not child.cancellation_pending:
        return _CorrectionObligationStatus.MALFORMED

    if child_state == SpeechState.PROPOSED:
        if (
            child.heard is not None
            or _has_any_approval_proof(child)
            or child.cancellation_pending
            or child.correction_pending
        ):
            return _CorrectionObligationStatus.MALFORMED
        return _CorrectionObligationStatus.LIVE

    if child_state == SpeechState.APPROVED:
        if (
            child.heard is not None
            or not _has_complete_approval_proof(child)
            or child.cancellation_pending
            or child.correction_pending
        ):
            return _CorrectionObligationStatus.MALFORMED
        return _CorrectionObligationStatus.LIVE

    if child_state in {SpeechState.QUEUED, SpeechState.EMITTING}:
        if child.heard is not None or not _has_complete_approval_proof(child):
            return _CorrectionObligationStatus.MALFORMED
        return _CorrectionObligationStatus.LIVE

    if child_state == SpeechState.BLOCKED:
        if (
            child.heard is not None
            or _has_any_approval_proof(child)
            or child.cancellation_pending
            or child.correction_pending
        ):
            return _CorrectionObligationStatus.MALFORMED
        return _CorrectionObligationStatus.DEAD_NON_HEARD

    if child_state == SpeechState.CANCELLED:
        if (
            child.heard is True
            or child.cancellation_pending
            or child.correction_pending
            or (
                _has_any_approval_proof(child)
                and not _has_complete_approval_proof(child)
            )
        ):
            return _CorrectionObligationStatus.MALFORMED
        return _CorrectionObligationStatus.DEAD_NON_HEARD

    if child_state == SpeechState.EMITTED:
        if (
            child.heard is None
            or not _has_complete_approval_proof(child)
            or child.cancellation_pending
            or child.correction_pending
        ):
            return _CorrectionObligationStatus.MALFORMED
        if child.heard is True:
            return _CorrectionObligationStatus.SATISFIED_HEARD
        return _CorrectionObligationStatus.DEAD_NON_HEARD

    if child_state == SpeechState.CORRECTION_REQUIRED:
        if (
            child.heard is not True
            or not _has_complete_approval_proof(child)
            or child.cancellation_pending
            or child.correction_pending
        ):
            return _CorrectionObligationStatus.MALFORMED
        return _CorrectionObligationStatus.SATISFIED_HEARD

    return _CorrectionObligationStatus.MALFORMED


def _correction_obligation_status(
    prior_speech_id: str,
    state: SessionState,
    *,
    exclude_speech_id: Optional[str] = None,
) -> _CorrectionObligationStatus:
    """Classify all sibling attempts without relying on map insertion order."""

    statuses: set[_CorrectionObligationStatus] = set()
    for storage_id, child in sorted(state.speech.items()):
        if (
            child.act_type != SpeechActType.CORRECTION
            or child.supersedes_speech_id != prior_speech_id
            or child.speech_id == exclude_speech_id
        ):
            continue
        if storage_id != child.speech_id:
            return _CorrectionObligationStatus.MALFORMED
        statuses.add(_classify_correction_child(child))

    if _CorrectionObligationStatus.MALFORMED in statuses:
        return _CorrectionObligationStatus.MALFORMED
    if _CorrectionObligationStatus.SATISFIED_HEARD in statuses:
        return _CorrectionObligationStatus.SATISFIED_HEARD
    if _CorrectionObligationStatus.LIVE in statuses:
        return _CorrectionObligationStatus.LIVE
    if _CorrectionObligationStatus.DEAD_NON_HEARD in statuses:
        return _CorrectionObligationStatus.DEAD_NON_HEARD
    return _CorrectionObligationStatus.NONE


def _lineage_is_valid(
    prior_speech: SpeechAct,
    state: SessionState,
    correction_speech_id: str,
) -> bool:
    """Verify existing ancestry without rewriting or following an unbounded graph."""

    seen: set[str] = set()
    current = prior_speech
    for _ in range(len(state.speech) + 1):
        if current.speech_id == correction_speech_id or current.speech_id in seen:
            return False
        seen.add(current.speech_id)

        parent_id = current.supersedes_speech_id
        if parent_id is None:
            return True
        if parent_id == correction_speech_id:
            return False

        parent = state.speech.get(parent_id)
        if parent is None or parent.speech_id != parent_id:
            return False
        current = parent
    return False


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

    current_state_text = _render_current_state(current_claim)
    if current_state_text is None:
        return None

    current_claim_state = ClaimState(current_claim.state)

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

    obligation_status = _correction_obligation_status(
        prior.speech_id,
        state,
        exclude_speech_id=exclude_speech_id,
    )
    if obligation_status not in {
        _CorrectionObligationStatus.NONE,
        _CorrectionObligationStatus.DEAD_NON_HEARD,
    }:
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
        if not _lineage_is_valid(
            context.prior_speech,
            state,
            correction_speech_id,
        ):
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
    if not _lineage_is_valid(context.prior_speech, state, act.speech_id):
        return "Correction lineage is missing, cyclic, or self-referential"
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
        return "Correction wording is not derived from canonical speech and current claim fact"
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
