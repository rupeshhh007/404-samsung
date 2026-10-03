"""TRU-004: output lifecycle boundary and corrective-speech policy.

``OutputRuntime`` consumes reducer-issued output commands and delegates the
external action to an injected ``OutputPort``.  It resolves only detached
reducer-owned snapshots and returns canonical lifecycle facts for journalling;
neither the runtime nor the port mutates authoritative ``SpeechAct`` state.

The reducer owns correction lifecycle transitions and emits
``RequestSpeechCorrection`` only after audible output has reached
``CORRECTION_REQUIRED``.  The correction policy consumes that canonical
obligation and constructs a new, sequence-pinned ``PROPOSED`` SpeechAct.  It
performs no I/O and never mutates reducer state.
"""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
import inspect
from typing import Any, Dict, Optional, Protocol

from pydantic import Field

from interlock.domain.enums import (
    ClaimCertainty,
    ClaimState,
    EventSource,
    RuntimeMode,
    SpeechActType,
    SpeechState,
)
from interlock.domain.models import ClaimRecord, DomainBaseModel, SessionState, SpeechAct
from interlock.runtime.commands import (
    BaseCommand,
    CancelSpeech,
    EmitOutput,
    RequestSpeechCorrection,
)
from interlock.runtime.dispatcher import DispatchContext
from interlock.runtime.journal import EventCandidate
from interlock.truth.claims import (
    RULE_APPOINTMENT_BOOKED,
    RULE_APPOINTMENT_CANCELLED,
    RULE_REQUEST_RECEIVED,
    RULE_SLOT_AVAILABLE,
    _extract_claim_parameters,
    normalize_rule_name,
)


class OutputPort(Protocol):
    """Inward async contract implemented by text/TTS adapters and fakes.

    ``emit`` returns only after the adapter has started the exact approved text;
    the command handler then journals ``SpeechEmissionStarted``.  Completion or
    failure remains an adapter ingress fact.  ``cancel`` is cooperative and
    never claims that output has terminalized.
    """

    async def emit(
        self,
        *,
        session_id: str,
        speech_id: str,
        rendered_text: str,
    ) -> None:
        """Start emitting the persisted approved text for one speech act."""

    async def cancel(self, *, session_id: str, speech_id: str) -> None:
        """Request an output stop without manufacturing a terminal fact."""


class SpeechSnapshotResolver(Protocol):
    """Injected read-only access to a detached reducer-owned speech snapshot."""

    def __call__(self, session_id: str, speech_id: str) -> SpeechAct | None:
        """Return the current detached speech act, or ``None`` when unknown."""


class OutputRuntimeErrorCode(str, Enum):
    """Stable fail-closed categories for the TRU-004 output boundary."""

    INVALID_COMMAND = "INVALID_COMMAND"
    UNKNOWN_SPEECH = "UNKNOWN_SPEECH"
    INVALID_SPEECH_SNAPSHOT = "INVALID_SPEECH_SNAPSHOT"
    EMISSION_NOT_AUTHORIZED = "EMISSION_NOT_AUTHORIZED"
    CANCELLATION_NOT_AUTHORIZED = "CANCELLATION_NOT_AUTHORIZED"
    COMMAND_CAPACITY_EXHAUSTED = "COMMAND_CAPACITY_EXHAUSTED"


class OutputRuntimeError(ValueError):
    """An output command failed before a trustworthy lifecycle fact existed."""

    def __init__(self, code: OutputRuntimeErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code


class OutputPortFailure(Exception):
    """Typed adapter terminal failure with explicit heard semantics.

    An adapter must use this only when it can truthfully establish all fields.
    Ambiguous transport exceptions remain dispatcher failures and do not invent
    a ``heard`` value.
    """

    def __init__(
        self,
        error_code: str,
        *,
        heard: bool,
        retryable: bool = False,
    ) -> None:
        if not isinstance(error_code, str) or not error_code:
            raise ValueError("error_code must be a non-empty string")
        if type(heard) is not bool:
            raise TypeError("heard must be a boolean")
        if type(retryable) is not bool:
            raise TypeError("retryable must be a boolean")
        super().__init__("output adapter reported a terminal failure")
        self.error_code = error_code
        self.heard = heard
        self.retryable = retryable


class OutputRuntime:
    """Dispatcher handlers for reducer-authorized output commands.

    Reservations use the dispatcher's originating event identity, matching the
    existing command identity convention.  They prevent handler re-entry from
    repeating an external call while leaving all authoritative lifecycle state
    in the reducer.
    """

    def __init__(
        self,
        *,
        speech_resolver: SpeechSnapshotResolver,
        port: OutputPort,
        retained_command_limit: int = 1024,
    ) -> None:
        if not callable(speech_resolver):
            raise TypeError("speech_resolver must be callable")
        if not callable(getattr(port, "emit", None)) or not callable(
            getattr(port, "cancel", None)
        ):
            raise TypeError("port must implement emit and cancel")
        if type(retained_command_limit) is not int or retained_command_limit < 1:
            raise ValueError("retained_command_limit must be at least 1")
        self._speech_resolver = speech_resolver
        self._port = port
        self._retained_command_limit = retained_command_limit
        self._reservations: OrderedDict[
            tuple[str, str, str, str], bool
        ] = OrderedDict()
        self._reservations_lock = asyncio.Lock()

    async def handle_emit_output(
        self,
        command: BaseCommand,
        context: DispatchContext,
    ) -> EventCandidate | None:
        """Emit only reducer-queued, persisted approved text exactly once."""

        if not isinstance(command, EmitOutput):
            raise OutputRuntimeError(
                OutputRuntimeErrorCode.INVALID_COMMAND,
                "expected EmitOutput",
            )
        if context.runtime_mode == RuntimeMode.REPLAY:
            return None

        speech = self._resolve(command.session_id, command.speech_id)
        identity = self._command_identity(command, context)
        if not await self._reserve(identity):
            return None
        try:
            self._validate_emit_snapshot(speech)
        except Exception:
            await self._release(identity)
            raise

        try:
            await self._port.emit(
                session_id=command.session_id,
                speech_id=speech.speech_id,
                rendered_text=speech.rendered_text or "",
            )
        except OutputPortFailure as failure:
            return self._failure_candidate(command, context, failure)
        finally:
            await self._complete(identity)

        return self._candidate(
            command,
            context,
            event_type="SpeechEmissionStarted",
            payload={"speech_id": speech.speech_id},
            identity="started",
        )

    async def handle_cancel_speech(
        self,
        command: BaseCommand,
        context: DispatchContext,
    ) -> EventCandidate | None:
        """Request cooperative cancellation without claiming terminal state."""

        if not isinstance(command, CancelSpeech):
            raise OutputRuntimeError(
                OutputRuntimeErrorCode.INVALID_COMMAND,
                "expected CancelSpeech",
            )
        if context.runtime_mode == RuntimeMode.REPLAY:
            return None

        speech = self._resolve(command.session_id, command.speech_id)

        # The current reducer may emit CancelSpeech after cancelling an APPROVED
        # act before dispatch.  No adapter action is needed because no output was
        # started; accepting this as a no-op preserves the canonical boundary.
        if speech.state == SpeechState.CANCELLED:
            return None
        if speech.state not in (SpeechState.QUEUED, SpeechState.EMITTING) or not (
            speech.cancellation_pending
        ):
            raise OutputRuntimeError(
                OutputRuntimeErrorCode.CANCELLATION_NOT_AUTHORIZED,
                "speech is not reducer-authorized for cooperative cancellation",
            )

        identity = self._command_identity(command, context)
        if not await self._reserve(identity):
            return None
        try:
            await self._port.cancel(
                session_id=command.session_id,
                speech_id=speech.speech_id,
            )
        except OutputPortFailure as failure:
            return self._failure_candidate(command, context, failure)
        finally:
            await self._complete(identity)
        return None

    def _resolve(self, session_id: str, speech_id: str) -> SpeechAct:
        try:
            resolved = self._speech_resolver(session_id, speech_id)
        except Exception as exc:
            raise OutputRuntimeError(
                OutputRuntimeErrorCode.UNKNOWN_SPEECH,
                "speech snapshot could not be resolved",
            ) from exc
        if inspect.isawaitable(resolved):
            raise OutputRuntimeError(
                OutputRuntimeErrorCode.INVALID_SPEECH_SNAPSHOT,
                "speech resolver must be synchronous and read-only",
            )
        if resolved is None:
            raise OutputRuntimeError(
                OutputRuntimeErrorCode.UNKNOWN_SPEECH,
                "speech is unknown",
            )
        if not isinstance(resolved, SpeechAct):
            raise OutputRuntimeError(
                OutputRuntimeErrorCode.INVALID_SPEECH_SNAPSHOT,
                "resolver returned an invalid speech snapshot",
            )
        speech = resolved.model_copy(deep=True)
        if speech.speech_id != speech_id:
            raise OutputRuntimeError(
                OutputRuntimeErrorCode.INVALID_SPEECH_SNAPSHOT,
                "resolved speech does not match command",
            )
        return speech

    @staticmethod
    def _validate_emit_snapshot(speech: SpeechAct) -> None:
        approval_is_complete = bool(
            speech.rendered_text
            and speech.approved_policy_id
            and speech.approved_through_sequence is not None
            and set(speech.approved_claim_versions) == set(speech.claim_ids)
        )
        if (
            speech.state != SpeechState.QUEUED
            or speech.heard is not None
            or speech.cancellation_pending
            or speech.correction_pending
            or not approval_is_complete
        ):
            raise OutputRuntimeError(
                OutputRuntimeErrorCode.EMISSION_NOT_AUTHORIZED,
                "speech is not a current reducer-queued approved output",
            )

    @staticmethod
    def _command_identity(
        command: EmitOutput | CancelSpeech,
        context: DispatchContext,
    ) -> tuple[str, str, str, str]:
        origin = context.origin_event_id or f"unscoped:{command.speech_id}"
        return (
            command.command_type,
            command.session_id,
            command.speech_id,
            origin,
        )

    async def _reserve(self, identity: tuple[str, str, str, str]) -> bool:
        async with self._reservations_lock:
            if identity in self._reservations:
                self._reservations.move_to_end(identity)
                return False
            while len(self._reservations) >= self._retained_command_limit:
                removable = next(
                    (
                        candidate
                        for candidate, active in self._reservations.items()
                        if not active
                    ),
                    None,
                )
                if removable is None:
                    raise OutputRuntimeError(
                        OutputRuntimeErrorCode.COMMAND_CAPACITY_EXHAUSTED,
                        "output command reservation capacity is exhausted",
                    )
                self._reservations.pop(removable)
            self._reservations[identity] = True
            return True

    async def _release(self, identity: tuple[str, str, str, str]) -> None:
        async with self._reservations_lock:
            self._reservations.pop(identity, None)

    async def _complete(self, identity: tuple[str, str, str, str]) -> None:
        async with self._reservations_lock:
            if identity in self._reservations:
                self._reservations[identity] = False
                self._reservations.move_to_end(identity)

    @staticmethod
    def _candidate(
        command: EmitOutput | CancelSpeech,
        context: DispatchContext,
        *,
        event_type: str,
        payload: Dict[str, Any],
        identity: str,
    ) -> EventCandidate:
        origin = context.origin_event_id or "unscoped"
        return EventCandidate(
            event_type=event_type,
            session_id=command.session_id,
            source=EventSource.OUTPUT_ADAPTER,
            payload=payload,
            logical_time=context.logical_time,
            correlation_id=context.correlation_id,
            causation_id=context.origin_event_id,
            dedupe_key=(
                f"output-runtime:{event_type}:{command.speech_id}:{origin}:{identity}"
            ),
        )

    def _failure_candidate(
        self,
        command: EmitOutput | CancelSpeech,
        context: DispatchContext,
        failure: OutputPortFailure,
    ) -> EventCandidate:
        return self._candidate(
            command,
            context,
            event_type="SpeechEmissionFailed",
            payload={
                "speech_id": command.speech_id,
                "error_code": failure.error_code,
                "heard": failure.heard,
                "retryable": failure.retryable,
            },
            identity=f"failed:{failure.error_code}",
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
