"""TRU-003: Canonical TRUTHLOCK decision layer.

Pure, deterministic policy gate between ClaimGraph truth state and proposed SpeechActs.
Implements:
- docs/components/TRUTHLOCK.md
- docs/contracts/INTERFACES.md (Truthlock.validate)
- docs/architecture/INVARIANTS.md (Invariant I6, FR-015)
- docs/architecture/STATE_MACHINES.md (Speech lifecycle gating)

Key invariants:
- Rendered certainty <= minimum certainty supported by all required claims (Invariant I6).
- Never upgrades certainty.
- Pure and deterministic: no I/O, no network, no clock reads, no datetime.now(), no randomness.
- Never mutates caller-owned objects (SpeechAct, ClaimRecord, DivergenceCase, EvidenceRecord, etc.).
- Requires SpeechAct.state == PROPOSED; fails closed on non-PROPOSED lifecycle states.
- Verifies that all supporting evidence required by claims exists in the pinned evidence snapshot.
- Binds factual controlled templates strictly to their required claim states (e.g. CONFIRMED).
- Strictly verifies that asserted speech identity/slots are carried and matched by supporting claims.
- Rejects stale snapshots (through_sequence < authoritative_sequence) with RETRY_STALE_SNAPSHOT.
- Divergence guard: blocks definitive success speech if an unresolved divergence touches the resource.
- Consequential speech strictly requires verified claims and controlled templates.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple, Union

from pydantic import Field, model_validator

from interlock.domain.enums import (
    ClaimCertainty,
    ClaimState,
    DivergenceState,
    SpeechActType,
    SpeechState,
)
from interlock.domain.events import (
    SpeechActApproved,
    SpeechActBlocked,
)
from interlock.domain.models import (
    ClaimRecord,
    DivergenceCase,
    DomainBaseModel,
    EvidenceRecord,
    SpeechAct,
)
from interlock.truth.claims import (
    RULE_APPOINTMENT_BOOKED,
    RULE_APPOINTMENT_CANCELLED,
    RULE_REQUEST_RECEIVED,
    RULE_SLOT_AVAILABLE,
    _match_slot,
    normalize_rule_name,
)
from interlock.truth.speech import (
    CorrectionProposal,
    validate_correction_proposal,
    validate_correction_speech_act,
)


class TruthDecisionStatus(str, Enum):
    """Canonical decision status returned by TRUTHLOCK."""

    APPROVE = "APPROVE"
    BLOCK = "BLOCK"
    RETRY_STALE_SNAPSHOT = "RETRY_STALE_SNAPSHOT"


# Epistemic certainty hierarchy (0 = lowest, 3 = highest) per Invariant I6
CERTAINTY_RANK: Mapping[ClaimCertainty, int] = {
    ClaimCertainty.UNCERTAIN: 0,
    ClaimCertainty.PROGRESS: 1,
    ClaimCertainty.ACKNOWLEDGED: 2,
    ClaimCertainty.CONFIRMED: 3,
}

# Unresolved divergence states that block definitive success speech for a resource
UNRESOLVED_DIVERGENCE_STATES: Set[DivergenceState] = {
    DivergenceState.OPEN,
    DivergenceState.PLANNED,
    DivergenceState.RECONCILING,
    DivergenceState.ESCALATED,
}

SEQUENCE_PINNED_TEMPLATE_IDS: Set[str] = {
    "tmpl_slot_available",
    "tmpl_dispatch_requested",
    "tmpl_receipt_acknowledged",
    "tmpl_booking_confirmed",
    "tmpl_cancellation_confirmed",
    "tmpl_outcome_unknown",
    "tmpl_divergence",
    "tmpl_correction",
}


@dataclass(frozen=True)
class ControlledTemplate:
    """Definition of a canonical controlled output template."""

    template_id: str
    template_pattern: str
    fallback_pattern: Optional[str]
    allowed_act_types: Set[SpeechActType]
    max_certainty: ClaimCertainty
    required_rules: Set[str] = frozenset()
    required_claim_state: Optional[ClaimState] = None

    @property
    def semantic_certainty(self) -> ClaimCertainty:
        """Exact certainty conveyed by this controlled template's wording."""
        return self.max_certainty


# Canonical controlled templates per docs/components/TRUTHLOCK.md table
CONTROLLED_TEMPLATES: Dict[str, ControlledTemplate] = {
    "tmpl_checking": ControlledTemplate(
        template_id="tmpl_checking",
        template_pattern="Checking…",
        fallback_pattern="Checking…",
        allowed_act_types={SpeechActType.PROGRESS, SpeechActType.CLARIFICATION},
        max_certainty=ClaimCertainty.PROGRESS,
    ),
    "tmpl_slot_available": ControlledTemplate(
        template_id="tmpl_slot_available",
        template_pattern="The {slot} slot is currently available.",
        fallback_pattern="The slot is currently available.",
        allowed_act_types={SpeechActType.RESULT, SpeechActType.PROGRESS},
        max_certainty=ClaimCertainty.CONFIRMED,
        required_rules={RULE_SLOT_AVAILABLE},
        required_claim_state=ClaimState.CONFIRMED,
    ),
    "tmpl_dispatch_requested": ControlledTemplate(
        template_id="tmpl_dispatch_requested",
        template_pattern="I’m submitting the {slot} booking.",
        fallback_pattern="I’m submitting the booking.",
        allowed_act_types={SpeechActType.PROGRESS},
        max_certainty=ClaimCertainty.PROGRESS,
    ),
    "tmpl_receipt_acknowledged": ControlledTemplate(
        template_id="tmpl_receipt_acknowledged",
        template_pattern="The service received the request.",
        fallback_pattern="The service received the request.",
        allowed_act_types={SpeechActType.PROGRESS, SpeechActType.RESULT},
        max_certainty=ClaimCertainty.ACKNOWLEDGED,
        required_rules={RULE_REQUEST_RECEIVED},
        required_claim_state=ClaimState.CONFIRMED,
    ),
    "tmpl_booking_confirmed": ControlledTemplate(
        template_id="tmpl_booking_confirmed",
        template_pattern="Confirmed — your {slot} appointment is booked.",
        fallback_pattern="Confirmed — your appointment is booked.",
        allowed_act_types={SpeechActType.RESULT},
        max_certainty=ClaimCertainty.CONFIRMED,
        required_rules={RULE_APPOINTMENT_BOOKED},
        required_claim_state=ClaimState.CONFIRMED,
    ),
    "tmpl_cancellation_confirmed": ControlledTemplate(
        template_id="tmpl_cancellation_confirmed",
        template_pattern="Confirmed — your {slot} appointment is cancelled.",
        fallback_pattern="Confirmed — your appointment is cancelled.",
        allowed_act_types={SpeechActType.RESULT},
        max_certainty=ClaimCertainty.CONFIRMED,
        required_rules={RULE_APPOINTMENT_CANCELLED},
        required_claim_state=ClaimState.CONFIRMED,
    ),
    "tmpl_outcome_unknown": ControlledTemplate(
        template_id="tmpl_outcome_unknown",
        template_pattern="I can’t yet verify whether the booking completed.",
        fallback_pattern="I can’t yet verify whether the booking completed.",
        allowed_act_types={SpeechActType.UNCERTAINTY, SpeechActType.PROGRESS},
        max_certainty=ClaimCertainty.UNCERTAIN,
    ),
    "tmpl_divergence": ControlledTemplate(
        template_id="tmpl_divergence",
        template_pattern="An {observed_slot} booking exists; you requested {desired_slot}. I’m reconciling it.",
        fallback_pattern="An existing booking was found. I’m reconciling it.",
        allowed_act_types={SpeechActType.DIVERGENCE, SpeechActType.PROGRESS},
        max_certainty=ClaimCertainty.PROGRESS,
    ),
    "tmpl_correction": ControlledTemplate(
        template_id="tmpl_correction",
        template_pattern="Correction: I previously said {previous_statement}; current verified state is {current_state}.",
        fallback_pattern="Correction: verified state has changed.",
        allowed_act_types={SpeechActType.CORRECTION},
        max_certainty=ClaimCertainty.CONFIRMED,
    ),
}

TEMPLATE_ALIASES: Dict[str, str] = {
    "preparation_pending": "tmpl_checking",
    "checking": "tmpl_checking",
    "slot_available": "tmpl_slot_available",
    "dispatch_requested": "tmpl_dispatch_requested",
    "receipt_acknowledged": "tmpl_receipt_acknowledged",
    "booking_confirmed": "tmpl_booking_confirmed",
    "appointment_booked": "tmpl_booking_confirmed",
    "cancellation_confirmed": "tmpl_cancellation_confirmed",
    "appointment_cancelled": "tmpl_cancellation_confirmed",
    "outcome_unknown": "tmpl_outcome_unknown",
    "booking_uncertain": "tmpl_outcome_unknown",
    "divergence": "tmpl_divergence",
    "reconciling": "tmpl_divergence",
    "correction": "tmpl_correction",
}


def _extract_claim_params(claim: ClaimRecord) -> Dict[str, Any]:
    """Extract standard identity and slot parameters from claim subject and object."""
    params: Dict[str, Any] = {}
    for source in (claim.subject, claim.object):
        if isinstance(source, dict):
            for k, v in source.items():
                if v is not None and k not in params:
                    params[k] = v
    if "case_id" in params and "divergence_id" not in params:
        params["divergence_id"] = params["case_id"]
    return params


def _canonicalize_records(
    records: Any,
    record_type: type,
    id_attribute: str,
    label: str,
) -> Tuple[Dict[str, Any], Optional[str]]:
    """Index records by their model identity and reject ambiguous duplicates."""
    if records is None:
        return {}, None

    if isinstance(records, Mapping):
        values = list(records.values())
    elif isinstance(records, Sequence) and not isinstance(records, (str, bytes)):
        values = list(records)
    else:
        return {}, f"{label} snapshot must be a mapping or sequence"

    invalid_types = sorted(
        {type(record).__name__ for record in values if not isinstance(record, record_type)}
    )
    if invalid_types:
        return {}, f"{label} snapshot contains invalid record types: {invalid_types}"

    grouped: Dict[str, List[Any]] = {}
    for record in values:
        canonical_id = getattr(record, id_attribute)
        grouped.setdefault(canonical_id, []).append(record)

    conflicting_ids = sorted(
        canonical_id
        for canonical_id, candidates in grouped.items()
        if any(candidate != candidates[0] for candidate in candidates[1:])
    )
    if conflicting_ids:
        return (
            {},
            f"{label} snapshot contains conflicting records for canonical IDs: {conflicting_ids}",
        )

    return {
        canonical_id: candidates[0]
        for canonical_id, candidates in sorted(grouped.items())
    }, None


def _claim_slot_for_template(template_id: str, claim: ClaimRecord) -> Optional[Any]:
    """Extract the slot asserted by the claim type that supports a template."""
    params = _extract_claim_params(claim)
    if template_id == "tmpl_slot_available":
        return params.get("slot") or params.get("requested_slot") or params.get("confirmed_slot")
    return params.get("confirmed_slot") or params.get("slot") or params.get("requested_slot")


def _matching_claims_disagree(
    template_id: str, claims: Sequence[ClaimRecord]
) -> Optional[str]:
    """Return the first canonical factual field on which template claims disagree."""
    extractors = {
        "center_id": lambda claim: (
            _extract_claim_params(claim).get("center_id")
            or _extract_claim_params(claim).get("center")
        ),
        "provider_booking_id": lambda claim: (
            _extract_claim_params(claim).get("provider_booking_id")
            or _extract_claim_params(claim).get("booking_id")
        ),
        "provider_request_id": lambda claim: (
            _extract_claim_params(claim).get("provider_request_id")
            or _extract_claim_params(claim).get("request_id")
        ),
        "slot": lambda claim: _claim_slot_for_template(template_id, claim),
    }

    ordered_claims = sorted(claims, key=lambda claim: claim.claim_id)
    for field, extractor in extractors.items():
        values = [extractor(claim) for claim in ordered_claims]
        present = [value for value in values if value is not None]
        if len(present) < 2:
            continue
        first = present[0]
        if field == "slot":
            disagrees = any(not _match_slot(first, value) for value in present[1:])
        else:
            disagrees = any(str(first) != str(value) for value in present[1:])
        if disagrees:
            return field
    return None


def _render_template(
    template: ControlledTemplate,
    slots: Mapping[str, Any],
    supported_slot: Optional[Any] = None,
) -> str:
    """Render a controlled template with typed slots supported by the claim snapshot."""
    pattern = template.template_pattern

    if "{slot}" in pattern:
        # Only render factual slot if supported by the claim snapshot
        slot_val = supported_slot or slots.get("slot") or slots.get("confirmed_slot") or slots.get("requested_slot")
        if slot_val:
            pattern = pattern.replace("{slot}", str(slot_val))
        elif template.fallback_pattern:
            pattern = template.fallback_pattern
        else:
            pattern = pattern.replace(" {slot}", "").replace("{slot} ", "").replace("{slot}", "")

    if "{observed_slot}" in pattern or "{desired_slot}" in pattern:
        obs_slot = slots.get("observed_slot") or slots.get("observed")
        des_slot = slots.get("desired_slot") or slots.get("desired")
        if obs_slot and des_slot:
            pattern = pattern.replace("{observed_slot}", str(obs_slot)).replace("{desired_slot}", str(des_slot))
        elif template.fallback_pattern:
            pattern = template.fallback_pattern

    if "{previous_statement}" in pattern or "{current_state}" in pattern:
        prev = slots.get("previous_statement", "")
        curr = slots.get("current_state", "")
        if prev and curr:
            pattern = pattern.replace("{previous_statement}", str(prev)).replace("{current_state}", str(curr))
        elif template.fallback_pattern:
            pattern = template.fallback_pattern

    return pattern


class TruthDecision(DomainBaseModel):
    """Immutable result of a TRUTHLOCK validation."""

    status: TruthDecisionStatus
    speech_id: str
    rendered_text: Optional[str] = None
    template_id: Optional[str] = None
    policy_id: str = "truthlock.v1"
    reason: Optional[str] = None
    max_certainty: Optional[ClaimCertainty] = None
    downgraded_speech_act: Optional[SpeechAct] = None
    through_sequence: Optional[int] = None
    claim_versions: Dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_approval_pin(self) -> "TruthDecision":
        if self.status == TruthDecisionStatus.APPROVE and self.through_sequence is None:
            raise ValueError("TruthDecision with APPROVE status must have non-null through_sequence")
        return self

    @property
    def is_approved(self) -> bool:
        return self.status == TruthDecisionStatus.APPROVE

    @property
    def is_blocked(self) -> bool:
        return self.status == TruthDecisionStatus.BLOCK

    @property
    def is_retry_stale(self) -> bool:
        return self.status == TruthDecisionStatus.RETRY_STALE_SNAPSHOT

    def create_approval_event(self) -> SpeechActApproved:
        """Create the canonical SpeechActApproved event for the reducer."""
        if self.status != TruthDecisionStatus.APPROVE:
            raise ValueError(f"Cannot create SpeechActApproved from decision status '{self.status}'")
        if not self.rendered_text:
            raise ValueError("Cannot create SpeechActApproved without rendered_text")
        if self.through_sequence is None:
            raise ValueError("Cannot create SpeechActApproved without through_sequence pin")
        return SpeechActApproved(
            speech_id=self.speech_id,
            rendered_text=self.rendered_text,
            policy_id=self.policy_id,
            through_sequence=self.through_sequence,
            claim_versions=self.claim_versions,
        )

    def create_blocked_event(self) -> SpeechActBlocked:
        """Create the canonical SpeechActBlocked event for the reducer."""
        if self.status != TruthDecisionStatus.BLOCK:
            raise ValueError(f"Cannot create SpeechActBlocked from decision status '{self.status}'")
        return SpeechActBlocked(
            speech_id=self.speech_id,
            reason=self.reason or "SpeechAct blocked by TRUTHLOCK policy",
            max_certainty=self.max_certainty or ClaimCertainty.UNCERTAIN,
        )


class TruthlockRequest(DomainBaseModel):
    """Optional structured request container for Truthlock.validate."""

    speech_act: SpeechAct
    claims: Mapping[str, ClaimRecord] = {}
    evidence: Mapping[str, EvidenceRecord] = {}
    through_sequence: Optional[int] = None
    authoritative_sequence: Optional[int] = None
    divergences: Mapping[str, DivergenceCase] = {}
    policy_version: str = "truthlock.v1"
    as_of: Optional[datetime] = None


class Truthlock:
    """Canonical TRUTHLOCK policy layer (TRU-003).

    Gates proposed SpeechActs against sequence-pinned ClaimGraph snapshots,
    supporting evidence records, divergence states, and controlled templates.
    Pure, deterministic, no I/O, no wall-clock dependencies.
    """

    def __init__(self, policy_id: str = "truthlock.v1") -> None:
        self.policy_id = policy_id

    def validate(
        self,
        request: Union[TruthlockRequest, SpeechAct, Mapping[str, Any], Any] = None,
        *args: Any,
        speech_act: Optional[Union[SpeechAct, Mapping[str, Any]]] = None,
        claims: Optional[Union[Mapping[str, ClaimRecord], Sequence[ClaimRecord]]] = None,
        evidence: Optional[Union[Mapping[str, EvidenceRecord], Sequence[EvidenceRecord]]] = None,
        through_sequence: Optional[int] = None,
        authoritative_sequence: Optional[int] = None,
        divergences: Optional[Union[Mapping[str, DivergenceCase], Sequence[DivergenceCase]]] = None,
        policy_version: Optional[str] = None,
        as_of: Optional[datetime] = None,
        **kwargs: Any,
    ) -> TruthDecision:
        """Validate a SpeechAct against sequence-pinned truth state.

        Decision order (docs/components/TRUTHLOCK.md):
        1. Validate SpeechAct schema; enforce SpeechAct.state == PROPOSED.
        2. Reject stale snapshot (through_sequence < authoritative_sequence) -> RETRY_STALE_SNAPSHOT.
        3. Resolve exact claim versions; verify existence and valid lifecycle states.
        4. Validate that all supporting evidence required by claims exists in evidence snapshot.
        5. Strictly support asserted speech template identity/slots against claims (fail closed).
        6. Divergence guard: reject definitive success speech tied to an unresolved divergence.
        7. Compute minimum allowed certainty across all required claims (Invariant I6).
        8. Verify template is registered, allowed for act type, and matches required claim state.
        9. Fill only typed slots supported by the claim snapshot and return APPROVE.
        """
        # --- 1. Unpack and normalize arguments ---
        act = speech_act
        claims_input = claims
        divergences_input = divergences
        evidence_input = evidence
        pinned_seq = through_sequence
        auth_seq = authoritative_sequence
        pol_ver = policy_version or self.policy_id
        evaluation_time = as_of
        correction_proposal: Optional[CorrectionProposal] = None
        session_state = kwargs.get("state") or kwargs.get("session_state")

        # If request object/dict passed as first positional arg
        if request is not None:
            if isinstance(request, CorrectionProposal):
                correction_proposal = request
                act = request.speech_act
                if pinned_seq is None:
                    pinned_seq = request.through_sequence
            elif isinstance(request, SpeechAct):
                act = request
            elif hasattr(request, "speech_act") and hasattr(request, "claims"):
                act = getattr(request, "speech_act")
                claims_input = getattr(request, "claims", claims_input)
                divergences_input = getattr(request, "divergences", divergences_input)
                evidence_input = getattr(request, "evidence", evidence_input)
                if pinned_seq is None:
                    pinned_seq = getattr(request, "through_sequence", None)
                if auth_seq is None:
                    auth_seq = getattr(request, "authoritative_sequence", None)
                if evaluation_time is None:
                    evaluation_time = getattr(request, "as_of", None)
                if hasattr(request, "policy_version"):
                    pol_ver = getattr(request, "policy_version") or pol_ver
            elif isinstance(request, Mapping) and "speech_act" in request:
                act = request["speech_act"]
                claims_input = request.get("claims", claims_input)
                divergences_input = request.get("divergences", divergences_input)
                evidence_input = request.get("evidence", evidence_input)
                if pinned_seq is None:
                    pinned_seq = request.get("through_sequence")
                if auth_seq is None:
                    auth_seq = request.get("authoritative_sequence")
                if evaluation_time is None:
                    evaluation_time = request.get("as_of")
                if "policy_version" in request:
                    pol_ver = request.get("policy_version") or pol_ver
            elif isinstance(request, Mapping) and "speech_id" in request and "template_id" in request:
                act = request

        # Parse additional positional args if any
        for arg in args:
            if isinstance(arg, int) and pinned_seq is None:
                pinned_seq = arg
            elif isinstance(arg, Mapping):
                sample = next(iter(arg.values())) if arg else None
                if isinstance(sample, ClaimRecord) and claims_input is None:
                    claims_input = arg
                elif isinstance(sample, DivergenceCase) and divergences_input is None:
                    divergences_input = arg
                elif isinstance(sample, EvidenceRecord) and evidence_input is None:
                    evidence_input = arg

        # Parse kwargs
        if session_state is not None:
            if auth_seq is None and hasattr(session_state, "last_sequence"):
                auth_seq = session_state.last_sequence
            if pinned_seq is None and hasattr(session_state, "last_sequence"):
                pinned_seq = session_state.last_sequence
            if divergences_input is None and hasattr(session_state, "divergences"):
                divergences_input = session_state.divergences
            if claims_input is None and hasattr(session_state, "claims"):
                claims_input = session_state.claims
            if evidence_input is None and hasattr(session_state, "evidence"):
                evidence_input = session_state.evidence

        if "evidence" in kwargs and evidence_input is None:
            evidence_input = kwargs["evidence"]

        # Validate SpeechAct
        if act is None:
            raise ValueError("No SpeechAct provided for TRUTHLOCK validation")
        if not isinstance(act, SpeechAct):
            if isinstance(act, Mapping):
                act = SpeechAct.model_validate(act)
            else:
                raise TypeError(f"Expected SpeechAct, got {type(act).__name__}")

        speech_id = act.speech_id
        resolved_pinned_seq = pinned_seq

        # Review Blocker 3: Require SpeechAct.state == PROPOSED
        if act.state != SpeechState.PROPOSED:
            return TruthDecision(
                status=TruthDecisionStatus.BLOCK,
                speech_id=speech_id,
                reason=f"SpeechAct state must be PROPOSED to be validated, but got '{act.state}'",
                max_certainty=ClaimCertainty.UNCERTAIN,
                policy_id=pol_ver,
                through_sequence=resolved_pinned_seq,
            )

        template_key = TEMPLATE_ALIASES.get(act.template_id, act.template_id)
        is_factual_consequential = (
            act.act_type == SpeechActType.RESULT
            or act.requested_certainty
            in (ClaimCertainty.CONFIRMED, ClaimCertainty.ACKNOWLEDGED)
            or template_key
            in (
                "tmpl_booking_confirmed",
                "tmpl_cancellation_confirmed",
                "tmpl_slot_available",
                "tmpl_receipt_acknowledged",
            )
        )
        requires_sequence_context = (
            is_factual_consequential
            or bool(act.claim_ids)
            or template_key in SEQUENCE_PINNED_TEMPLATE_IDS
            or act.act_type
            in {
                SpeechActType.FAILURE,
                SpeechActType.UNCERTAINTY,
                SpeechActType.DIVERGENCE,
                SpeechActType.CORRECTION,
            }
        )

        # Canonical model IDs, never caller-owned mapping keys, define snapshot identity.
        claims_map, claims_error = _canonicalize_records(
            claims_input, ClaimRecord, "claim_id", "Claim"
        )
        evidence_map, evidence_error = _canonicalize_records(
            evidence_input, EvidenceRecord, "evidence_id", "Evidence"
        )
        divergences_map, divergences_error = _canonicalize_records(
            divergences_input, DivergenceCase, "divergence_id", "Divergence"
        )

        # --- 2. Snapshot Pinning & Sequence Context Check ---
        if pinned_seq is None:
            return TruthDecision(
                status=TruthDecisionStatus.BLOCK,
                speech_id=speech_id,
                reason="Speech validation requires through_sequence snapshot pin",
                max_certainty=ClaimCertainty.UNCERTAIN,
                policy_id=pol_ver,
                through_sequence=None,
            )
        if auth_seq is None:
            auth_seq = pinned_seq
        if (
            resolved_pinned_seq is not None
            and auth_seq is not None
            and resolved_pinned_seq < auth_seq
        ):
            return TruthDecision(
                status=TruthDecisionStatus.RETRY_STALE_SNAPSHOT,
                speech_id=speech_id,
                reason=(
                    f"Pinned snapshot sequence {resolved_pinned_seq} is stale relative to "
                    f"authoritative sequence {auth_seq}"
                ),
                max_certainty=act.requested_certainty,
                policy_id=pol_ver,
                through_sequence=resolved_pinned_seq,
            )
        if (
            resolved_pinned_seq is not None
            and auth_seq is not None
            and resolved_pinned_seq > auth_seq
        ):
            return TruthDecision(
                status=TruthDecisionStatus.BLOCK,
                speech_id=speech_id,
                reason=(
                    f"Pinned snapshot sequence {resolved_pinned_seq} is ahead of "
                    f"authoritative sequence {auth_seq}"
                ),
                max_certainty=ClaimCertainty.UNCERTAIN,
                policy_id=pol_ver,
                through_sequence=resolved_pinned_seq,
            )

        snapshot_errors = sorted(
            error
            for error in (claims_error, evidence_error, divergences_error)
            if error is not None
        )
        if snapshot_errors:
            return TruthDecision(
                status=TruthDecisionStatus.BLOCK,
                speech_id=speech_id,
                reason="; ".join(snapshot_errors),
                max_certainty=ClaimCertainty.UNCERTAIN,
                policy_id=pol_ver,
                through_sequence=resolved_pinned_seq,
            )

        # A current sequence pin does not prove that an authorized write is
        # actually being submitted. TRU-003 currently receives no canonical
        # operation or ToolDispatchRequested snapshot, so caller slots cannot
        # support this consequential process-state wording.
        if template_key == "tmpl_dispatch_requested":
            return TruthDecision(
                status=TruthDecisionStatus.BLOCK,
                speech_id=speech_id,
                reason=(
                    "Template 'tmpl_dispatch_requested' requires authoritative "
                    "dispatch-state context that is not present in the TRUTHLOCK input"
                ),
                max_certainty=ClaimCertainty.UNCERTAIN,
                policy_id=pol_ver,
                through_sequence=resolved_pinned_seq,
            )

        # TRU-003 has no canonical world-effect/desired-intent slot binding for
        # detailed divergence wording. Caller-provided slots are not evidence.
        if template_key == "tmpl_divergence":
            return TruthDecision(
                status=TruthDecisionStatus.BLOCK,
                speech_id=speech_id,
                reason=(
                    "Template 'tmpl_divergence' requires canonical observed_slot and "
                    "desired_slot bindings that are not present in the TRUTHLOCK input"
                ),
                max_certainty=ClaimCertainty.UNCERTAIN,
                policy_id=pol_ver,
                through_sequence=resolved_pinned_seq,
            )

        canonical_correction = False
        if template_key == "tmpl_correction":
            correction_error = (
                validate_correction_speech_act(act, session_state)
                if correction_proposal is None
                else validate_correction_proposal(correction_proposal, session_state)
            )
            if correction_error is not None:
                return TruthDecision(
                    status=TruthDecisionStatus.BLOCK,
                    speech_id=speech_id,
                    reason=correction_error,
                    max_certainty=ClaimCertainty.UNCERTAIN,
                    policy_id=pol_ver,
                    through_sequence=resolved_pinned_seq,
                )
            canonical_correction = True

        # --- 3. Resolve exact claim versions & lifecycle states ---
        if not act.claim_ids:
            if is_factual_consequential:
                return TruthDecision(
                    status=TruthDecisionStatus.BLOCK,
                    speech_id=speech_id,
                    reason="Consequential speech requires claim_ids, but none provided",
                    max_certainty=ClaimCertainty.UNCERTAIN,
                    policy_id=pol_ver,
                    through_sequence=resolved_pinned_seq,
                )
            resolved_claims: List[ClaimRecord] = []
        else:
            resolved_claims = []
            for cid in sorted(act.claim_ids):
                if cid not in claims_map:
                    return TruthDecision(
                        status=TruthDecisionStatus.BLOCK,
                        speech_id=speech_id,
                        reason=f"Required claim '{cid}' not found in snapshot",
                        max_certainty=ClaimCertainty.UNCERTAIN,
                        policy_id=pol_ver,
                        through_sequence=resolved_pinned_seq,
                    )
                claim = claims_map[cid]

                # Fail-closed lifecycle checks per ClaimState
                if claim.state == ClaimState.CONTRADICTED and not canonical_correction:
                    return TruthDecision(
                        status=TruthDecisionStatus.BLOCK,
                        speech_id=speech_id,
                        reason=f"Required claim '{cid}' is CONTRADICTED",
                        max_certainty=ClaimCertainty.UNCERTAIN,
                        policy_id=pol_ver,
                        through_sequence=resolved_pinned_seq,
                    )
                if claim.state == ClaimState.STALE and not canonical_correction:
                    return TruthDecision(
                        status=TruthDecisionStatus.BLOCK,
                        speech_id=speech_id,
                        reason=f"Required claim '{cid}' is STALE",
                        max_certainty=ClaimCertainty.UNCERTAIN,
                        policy_id=pol_ver,
                        through_sequence=resolved_pinned_seq,
                    )
                if claim.state == ClaimState.SUPERSEDED and not canonical_correction:
                    return TruthDecision(
                        status=TruthDecisionStatus.BLOCK,
                        speech_id=speech_id,
                        reason=f"Required claim '{cid}' is SUPERSEDED",
                        max_certainty=ClaimCertainty.UNCERTAIN,
                        policy_id=pol_ver,
                        through_sequence=resolved_pinned_seq,
                    )
                if claim.state == ClaimState.PROPOSED:
                    return TruthDecision(
                        status=TruthDecisionStatus.BLOCK,
                        speech_id=speech_id,
                        reason=f"Required claim '{cid}' is PROPOSED and not yet evaluated",
                        max_certainty=ClaimCertainty.UNCERTAIN,
                        policy_id=pol_ver,
                        through_sequence=resolved_pinned_seq,
                    )
                if claim.state == ClaimState.PENDING:
                    if is_factual_consequential or act.requested_certainty in (
                        ClaimCertainty.CONFIRMED,
                        ClaimCertainty.ACKNOWLEDGED,
                    ):
                        return TruthDecision(
                            status=TruthDecisionStatus.BLOCK,
                            speech_id=speech_id,
                            reason=f"Required claim '{cid}' is PENDING; outcome not yet verified",
                            max_certainty=ClaimCertainty.PROGRESS,
                            policy_id=pol_ver,
                            through_sequence=resolved_pinned_seq,
                            downgraded_speech_act=self._create_downgrade(act, ClaimCertainty.PROGRESS),
                        )
                if claim.state == ClaimState.UNCERTAIN and not canonical_correction:
                    if act.requested_certainty != ClaimCertainty.UNCERTAIN or is_factual_consequential:
                        return TruthDecision(
                            status=TruthDecisionStatus.BLOCK,
                            speech_id=speech_id,
                            reason=f"Required claim '{cid}' is UNCERTAIN",
                            max_certainty=ClaimCertainty.UNCERTAIN,
                            policy_id=pol_ver,
                            through_sequence=resolved_pinned_seq,
                            downgraded_speech_act=self._create_downgrade(act, ClaimCertainty.UNCERTAIN),
                        )

                resolved_claims.append(claim)

        if canonical_correction:
            for cl in resolved_claims:
                canonical_claim = session_state.claims.get(cl.claim_id)
                if canonical_claim is None or canonical_claim != cl:
                    return TruthDecision(
                        status=TruthDecisionStatus.BLOCK,
                        speech_id=speech_id,
                        reason=(
                            f"Correction claim '{cl.claim_id}' does not exactly match the "
                            "authoritative reducer state"
                        ),
                        max_certainty=ClaimCertainty.UNCERTAIN,
                        policy_id=pol_ver,
                        through_sequence=resolved_pinned_seq,
                    )

        # --- 4. Review Blocker 1: Validate supporting evidence in pinned snapshot ---
        for cl in resolved_claims:
            if canonical_correction and cl.state != ClaimState.CONFIRMED:
                continue
            if cl.state == ClaimState.CONFIRMED or is_factual_consequential:
                # Every supporting_evidence_id required by the claim must exist in evidence snapshot
                missing_eids = [
                    eid for eid in cl.supporting_evidence_ids if eid not in evidence_map
                ]
                if missing_eids:
                    return TruthDecision(
                        status=TruthDecisionStatus.BLOCK,
                        speech_id=speech_id,
                        reason=(
                            f"Required claim '{cl.claim_id}' is missing supporting evidence in snapshot: "
                            f"{missing_eids}"
                        ),
                        max_certainty=ClaimCertainty.UNCERTAIN,
                        policy_id=pol_ver,
                        through_sequence=resolved_pinned_seq,
                    )

                for eid in cl.supporting_evidence_ids:
                    ev = evidence_map[eid]
                    if canonical_correction:
                        canonical_evidence = session_state.evidence.get(eid)
                        if canonical_evidence is None or canonical_evidence != ev:
                            return TruthDecision(
                                status=TruthDecisionStatus.BLOCK,
                                speech_id=speech_id,
                                reason=(
                                    f"Correction evidence '{eid}' does not exactly match the "
                                    "authoritative reducer state"
                                ),
                                max_certainty=ClaimCertainty.UNCERTAIN,
                                policy_id=pol_ver,
                                through_sequence=resolved_pinned_seq,
                            )
                    if ev.expires_at is None:
                        continue
                    if evaluation_time is None:
                        return TruthDecision(
                            status=TruthDecisionStatus.BLOCK,
                            speech_id=speech_id,
                            reason=(
                                f"Supporting evidence '{eid}' has freshness metadata, but no "
                                "deterministic as_of evaluation point was supplied"
                            ),
                            max_certainty=ClaimCertainty.UNCERTAIN,
                            policy_id=pol_ver,
                            through_sequence=resolved_pinned_seq,
                        )
                    try:
                        expired = ev.expires_at <= evaluation_time
                    except TypeError:
                        return TruthDecision(
                            status=TruthDecisionStatus.BLOCK,
                            speech_id=speech_id,
                            reason=(
                                f"Supporting evidence '{eid}' freshness cannot be compared to "
                                "the supplied deterministic as_of evaluation point"
                            ),
                            max_certainty=ClaimCertainty.UNCERTAIN,
                            policy_id=pol_ver,
                            through_sequence=resolved_pinned_seq,
                        )
                    if expired:
                        return TruthDecision(
                            status=TruthDecisionStatus.BLOCK,
                            speech_id=speech_id,
                            reason=f"Supporting evidence '{eid}' expired at {ev.expires_at}",
                            max_certainty=ClaimCertainty.UNCERTAIN,
                            policy_id=pol_ver,
                            through_sequence=resolved_pinned_seq,
                        )

        # --- 5. Strictly bind template facts to claims of the template's claim type ---
        supported_claim_slot: Optional[Any] = None
        identity_template = CONTROLLED_TEMPLATES.get(template_key)
        template_supporting_claims = (
            sorted(
                (
                    cl
                    for cl in resolved_claims
                    if normalize_rule_name(cl.required_evidence_rule)
                    in identity_template.required_rules
                ),
                key=lambda cl: cl.claim_id,
            )
            if identity_template is not None and identity_template.required_rules
            else []
        )

        disagreement = _matching_claims_disagree(
            template_key, template_supporting_claims
        )
        if disagreement is not None:
            return TruthDecision(
                status=TruthDecisionStatus.BLOCK,
                speech_id=speech_id,
                reason=(
                    f"Claims supporting template '{template_key}' disagree on factual field "
                    f"'{disagreement}'"
                ),
                max_certainty=ClaimCertainty.UNCERTAIN,
                policy_id=pol_ver,
                through_sequence=resolved_pinned_seq,
            )

        if template_supporting_claims:
            supported_claim_slot = _claim_slot_for_template(
                template_key, template_supporting_claims[0]
            )

        if is_factual_consequential and template_supporting_claims:
            speech_center = act.slots.get("center_id") or act.slots.get("center")
            speech_booking = act.slots.get("provider_booking_id") or act.slots.get("booking_id")
            speech_slot = (
                act.slots.get("slot")
                or act.slots.get("confirmed_slot")
                or act.slots.get("requested_slot")
            )

            for cl in template_supporting_claims:
                params = _extract_claim_params(cl)
                claim_center = params.get("center_id") or params.get("center")
                claim_booking = params.get("provider_booking_id") or params.get("booking_id")
                claim_slot = _claim_slot_for_template(template_key, cl)

                # If speech asserts center_id, supporting claim must carry it and match exactly
                if speech_center is not None:
                    if claim_center is None:
                        return TruthDecision(
                            status=TruthDecisionStatus.BLOCK,
                            speech_id=speech_id,
                            reason=(
                                f"Speech asserts center '{speech_center}', but supporting claim "
                                f"'{cl.claim_id}' lacks center"
                            ),
                            max_certainty=ClaimCertainty.UNCERTAIN,
                            policy_id=pol_ver,
                            through_sequence=resolved_pinned_seq,
                        )
                    if str(speech_center) != str(claim_center):
                        return TruthDecision(
                            status=TruthDecisionStatus.BLOCK,
                            speech_id=speech_id,
                            reason=(
                                f"Identity mismatch: center '{speech_center}' does not match claim "
                                f"center '{claim_center}'"
                            ),
                            max_certainty=ClaimCertainty.UNCERTAIN,
                            policy_id=pol_ver,
                            through_sequence=resolved_pinned_seq,
                        )

                # If speech asserts provider_booking_id, supporting claim must carry it and match exactly
                if speech_booking is not None:
                    if claim_booking is None:
                        return TruthDecision(
                            status=TruthDecisionStatus.BLOCK,
                            speech_id=speech_id,
                            reason=(
                                f"Speech asserts provider_booking_id '{speech_booking}', but supporting "
                                f"claim '{cl.claim_id}' lacks provider_booking_id"
                            ),
                            max_certainty=ClaimCertainty.UNCERTAIN,
                            policy_id=pol_ver,
                            through_sequence=resolved_pinned_seq,
                        )
                    if str(speech_booking) != str(claim_booking):
                        return TruthDecision(
                            status=TruthDecisionStatus.BLOCK,
                            speech_id=speech_id,
                            reason=(
                                f"Identity mismatch: booking '{speech_booking}' does not match claim "
                                f"booking '{claim_booking}'"
                            ),
                            max_certainty=ClaimCertainty.UNCERTAIN,
                            policy_id=pol_ver,
                            through_sequence=resolved_pinned_seq,
                        )

                # If speech asserts slot, supporting claim must carry it and match exactly
                if speech_slot is not None:
                    if claim_slot is None:
                        return TruthDecision(
                            status=TruthDecisionStatus.BLOCK,
                            speech_id=speech_id,
                            reason=(
                                f"Speech asserts slot '{speech_slot}', but supporting claim "
                                f"'{cl.claim_id}' lacks slot"
                            ),
                            max_certainty=ClaimCertainty.UNCERTAIN,
                            policy_id=pol_ver,
                            through_sequence=resolved_pinned_seq,
                        )
                    if not _match_slot(speech_slot, claim_slot):
                        return TruthDecision(
                            status=TruthDecisionStatus.BLOCK,
                            speech_id=speech_id,
                            reason=(
                                f"Slot mismatch: speech slot '{speech_slot}' does not match claim "
                                f"slot '{claim_slot}'"
                            ),
                            max_certainty=ClaimCertainty.UNCERTAIN,
                            policy_id=pol_ver,
                            through_sequence=resolved_pinned_seq,
                        )

        # --- 6. Divergence Guard ---
        div_decision = (
            None
            if canonical_correction
            else self._check_divergence_guard(
                act,
                resolved_claims,
                divergences_map,
                pol_ver,
                resolved_pinned_seq,
            )
        )
        if div_decision is not None:
            return div_decision

        # --- 7. Compute minimum allowed certainty across all required claims (Invariant I6) ---
        if canonical_correction:
            effective_ceiling = ClaimCertainty.CONFIRMED
        elif not resolved_claims:
            effective_ceiling = ClaimCertainty.PROGRESS if not is_factual_consequential else ClaimCertainty.UNCERTAIN
        else:
            supported_certainties: List[ClaimCertainty] = []
            for cl in resolved_claims:
                if cl.state == ClaimState.CONFIRMED:
                    rule = normalize_rule_name(cl.required_evidence_rule)
                    if rule == RULE_REQUEST_RECEIVED:
                        supported_certainties.append(ClaimCertainty.ACKNOWLEDGED)
                    else:
                        supported_certainties.append(ClaimCertainty.CONFIRMED)
                elif cl.state == ClaimState.PENDING:
                    supported_certainties.append(ClaimCertainty.PROGRESS)
                else:
                    supported_certainties.append(ClaimCertainty.UNCERTAIN)

            effective_ceiling = min(supported_certainties, key=lambda c: CERTAINTY_RANK[c])

        if CERTAINTY_RANK[act.requested_certainty] > CERTAINTY_RANK[effective_ceiling]:
            return TruthDecision(
                status=TruthDecisionStatus.BLOCK,
                speech_id=speech_id,
                reason=(
                    f"Requested certainty '{act.requested_certainty}' exceeds maximum supported "
                    f"certainty '{effective_ceiling}'"
                ),
                max_certainty=effective_ceiling,
                policy_id=pol_ver,
                through_sequence=resolved_pinned_seq,
                downgraded_speech_act=self._create_downgrade(act, effective_ceiling),
            )

        # --- 8. Review Blocker 2: Template semantics must require the correct claim state ---
        if template_key not in CONTROLLED_TEMPLATES:
            return TruthDecision(
                status=TruthDecisionStatus.BLOCK,
                speech_id=speech_id,
                reason=f"Unsupported or unknown template_id '{act.template_id}'",
                max_certainty=effective_ceiling,
                policy_id=pol_ver,
                through_sequence=resolved_pinned_seq,
            )

        template = CONTROLLED_TEMPLATES[template_key]

        if act.act_type not in template.allowed_act_types:
            return TruthDecision(
                status=TruthDecisionStatus.BLOCK,
                speech_id=speech_id,
                reason=f"SpeechAct act_type '{act.act_type}' not permitted for template '{template_key}'",
                max_certainty=effective_ceiling,
                policy_id=pol_ver,
                through_sequence=resolved_pinned_seq,
            )

        if (
            CERTAINTY_RANK[template.semantic_certainty]
            > CERTAINTY_RANK[act.requested_certainty]
        ):
            return TruthDecision(
                status=TruthDecisionStatus.BLOCK,
                speech_id=speech_id,
                reason=(
                    f"Template '{template_key}' renders semantic certainty "
                    f"'{template.semantic_certainty}', which exceeds requested certainty "
                    f"'{act.requested_certainty}'"
                ),
                max_certainty=act.requested_certainty,
                policy_id=pol_ver,
                through_sequence=resolved_pinned_seq,
                downgraded_speech_act=self._create_downgrade(
                    act, act.requested_certainty
                ),
            )

        # Template rule and minimum claim state binding
        if template.required_rules:
            matching_claims = [
                cl for cl in resolved_claims
                if normalize_rule_name(cl.required_evidence_rule) in template.required_rules
            ]
            if not matching_claims:
                return TruthDecision(
                    status=TruthDecisionStatus.BLOCK,
                    speech_id=speech_id,
                    reason=(
                        f"Template '{template_key}' requires claims matching rules "
                        f"{sorted(template.required_rules)}"
                    ),
                    max_certainty=effective_ceiling,
                    policy_id=pol_ver,
                    through_sequence=resolved_pinned_seq,
                )

            # Review Blocker 2: Required claim state check (e.g. must be CONFIRMED)
            if template.required_claim_state is not None:
                non_compliant_claims = [
                    cl for cl in matching_claims
                    if cl.state != template.required_claim_state
                ]
                if non_compliant_claims:
                    return TruthDecision(
                        status=TruthDecisionStatus.BLOCK,
                        speech_id=speech_id,
                        reason=(
                            f"Template '{template_key}' requires claim matching "
                            f"{sorted(template.required_rules)} to be in state "
                            f"'{template.required_claim_state}', but got '{non_compliant_claims[0].state}'"
                        ),
                        max_certainty=effective_ceiling,
                        policy_id=pol_ver,
                        through_sequence=resolved_pinned_seq,
                        downgraded_speech_act=self._create_downgrade(act, ClaimCertainty.PROGRESS),
                    )

        # --- 9. Render approved text with typed slots supported by claim snapshot ---
        rendered_text = _render_template(template, act.slots, supported_claim_slot)
        resolved_claim_versions = {
            cl.claim_id: cl.updated_by_event_id for cl in resolved_claims
        }

        return TruthDecision(
            status=TruthDecisionStatus.APPROVE,
            speech_id=speech_id,
            rendered_text=rendered_text,
            template_id=template_key,
            policy_id=pol_ver,
            max_certainty=effective_ceiling,
            through_sequence=resolved_pinned_seq,
            claim_versions=resolved_claim_versions,
        )

    def _check_divergence_guard(
        self,
        speech_act: SpeechAct,
        required_claims: Sequence[ClaimRecord],
        divergences: Mapping[str, DivergenceCase],
        policy_id: str,
        through_sequence: Optional[int],
    ) -> Optional[TruthDecision]:
        """Block definitive success unless canonical divergence context is safe."""
        is_definitive_success = (
            speech_act.act_type == SpeechActType.RESULT
            or speech_act.requested_certainty == ClaimCertainty.CONFIRMED
        )
        if not is_definitive_success or not divergences:
            return None

        unresolved_values = {
            state.value for state in UNRESOLVED_DIVERGENCE_STATES
        }
        unresolved = {
            divergence_id: divergence
            for divergence_id, divergence in sorted(divergences.items())
            if (
                divergence.state.value
                if isinstance(divergence.state, Enum)
                else str(divergence.state)
            )
            in unresolved_values
        }
        if not unresolved:
            return None

        # A caller-selected ID can identify an unresolved case to block, but it
        # cannot prove that other unresolved cases are unrelated to the target.
        speech_divergence_id = (
            speech_act.slots.get("divergence_id")
            or speech_act.slots.get("case_id")
        )
        if (
            speech_divergence_id is not None
            and str(speech_divergence_id) in unresolved
        ):
            divergence_id = str(speech_divergence_id)
            return self._unresolved_divergence_decision(
                speech_act,
                divergence_id,
                unresolved[divergence_id],
                policy_id,
                through_sequence,
            )

        # A divergence ID carried by a required canonical claim is the only
        # current TRUTHLOCK-local positive resource/case correlation.
        claim_divergence_ids: Set[str] = set()
        for claim in required_claims:
            params = _extract_claim_params(claim)
            divergence_id = params.get("divergence_id") or params.get("case_id")
            if divergence_id is not None:
                claim_divergence_ids.add(str(divergence_id))

        for divergence_id in sorted(claim_divergence_ids):
            if divergence_id not in divergences:
                return TruthDecision(
                    status=TruthDecisionStatus.BLOCK,
                    speech_id=speech_act.speech_id,
                    reason=(
                        f"Required claim references divergence '{divergence_id}', but that "
                        "case is absent from the pinned divergence snapshot"
                    ),
                    max_certainty=ClaimCertainty.UNCERTAIN,
                    policy_id=policy_id,
                    through_sequence=through_sequence,
                )
            if divergence_id in unresolved:
                return self._unresolved_divergence_decision(
                    speech_act,
                    divergence_id,
                    unresolved[divergence_id],
                    policy_id,
                    through_sequence,
                )

        if claim_divergence_ids:
            return None

        # observed_effect_ids are local EffectRecord.effect_id values. Without
        # an authoritative EffectRecord snapshot, provider booking identities
        # cannot be mapped to them and unresolved cases cannot be proven unrelated.
        unresolved_ids = sorted(unresolved)
        return TruthDecision(
            status=TruthDecisionStatus.BLOCK,
            speech_id=speech_act.speech_id,
            reason=(
                "Definitive success cannot be correlated safely against unresolved "
                f"divergence cases {unresolved_ids} without authoritative EffectRecord context"
            ),
            max_certainty=ClaimCertainty.UNCERTAIN,
            policy_id=policy_id,
            through_sequence=through_sequence,
            downgraded_speech_act=self._create_downgrade(
                speech_act, ClaimCertainty.UNCERTAIN
            ),
        )

    def _unresolved_divergence_decision(
        self,
        speech_act: SpeechAct,
        divergence_id: str,
        divergence: DivergenceCase,
        policy_id: str,
        through_sequence: Optional[int],
    ) -> TruthDecision:
        """Create a deterministic block for one canonically identified case."""
        state_value = (
            divergence.state.value
            if isinstance(divergence.state, Enum)
            else str(divergence.state)
        )
        return TruthDecision(
            status=TruthDecisionStatus.BLOCK,
            speech_id=speech_act.speech_id,
            reason=(
                f"Required resource touches unresolved divergence '{divergence_id}' "
                f"in state '{state_value}'"
            ),
            max_certainty=ClaimCertainty.UNCERTAIN,
            policy_id=policy_id,
            through_sequence=through_sequence,
            downgraded_speech_act=self._create_downgrade(
                speech_act, ClaimCertainty.UNCERTAIN
            ),
        )

    def _create_downgrade(
        self, original: SpeechAct, safe_certainty: ClaimCertainty
    ) -> Optional[SpeechAct]:
        """Produce a new, safe downgraded SpeechAct preserving lineage without mutating original."""
        if safe_certainty == ClaimCertainty.PROGRESS:
            return SpeechAct(
                speech_id=f"{original.speech_id}_downgrade",
                act_type=SpeechActType.PROGRESS,
                template_id="tmpl_checking",
                slots=dict(original.slots),
                claim_ids=list(original.claim_ids),
                requested_certainty=ClaimCertainty.PROGRESS,
                state=SpeechState.PROPOSED,
                created_by_event_id=original.created_by_event_id,
                supersedes_speech_id=original.speech_id,
            )
        elif safe_certainty == ClaimCertainty.ACKNOWLEDGED:
            return SpeechAct(
                speech_id=f"{original.speech_id}_downgrade",
                act_type=SpeechActType.PROGRESS,
                template_id="tmpl_receipt_acknowledged",
                slots=dict(original.slots),
                claim_ids=list(original.claim_ids),
                requested_certainty=ClaimCertainty.ACKNOWLEDGED,
                state=SpeechState.PROPOSED,
                created_by_event_id=original.created_by_event_id,
                supersedes_speech_id=original.speech_id,
            )
        elif safe_certainty == ClaimCertainty.UNCERTAIN:
            return SpeechAct(
                speech_id=f"{original.speech_id}_downgrade",
                act_type=SpeechActType.UNCERTAINTY,
                template_id="tmpl_outcome_unknown",
                slots=dict(original.slots),
                claim_ids=list(original.claim_ids),
                requested_certainty=ClaimCertainty.UNCERTAIN,
                state=SpeechState.PROPOSED,
                created_by_event_id=original.created_by_event_id,
                supersedes_speech_id=original.speech_id,
            )
        return None

    def create_approval_event(self, decision: TruthDecision) -> SpeechActApproved:
        """Create SpeechActApproved event from an approved TruthDecision."""
        return decision.create_approval_event()

    def create_blocked_event(self, decision: TruthDecision) -> SpeechActBlocked:
        """Create SpeechActBlocked event from a blocked TruthDecision."""
        return decision.create_blocked_event()


__all__ = [
    "TruthDecisionStatus",
    "TruthDecision",
    "TruthlockRequest",
    "ControlledTemplate",
    "CONTROLLED_TEMPLATES",
    "TEMPLATE_ALIASES",
    "Truthlock",
    "CERTAINTY_RANK",
    "UNRESOLVED_DIVERGENCE_STATES",
]
