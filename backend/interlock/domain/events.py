"""Canonical event payload contracts for INTERLOCK.

Implements all 30 canonical event types and payload schemas defined in
EVENT_MODEL.md and related component specifications.
"""

from typing import Any, Dict, List, Optional, Union
from pydantic import Field

from interlock.domain.enums import (
    Authorization,
    BranchMissReason,
    CancellationAckScope,
    ClaimCertainty,
    ClaimState,
    PlanStepState,
    RuntimeMode,
    SafePointName,
    ToolOutcome,
)
from interlock.domain.models import (
    BranchRecord,
    ClaimRecord,
    ControlIntent,
    DivergenceCase,
    DomainBaseModel,
    EffectRecord,
    EvidenceRecord,
    IntentDelta,
    IntentRevision,
    OperationRecord,
    ReconciliationPlan,
    SpeechAct,
)


class SessionStarted(DomainBaseModel):
    """Event: SessionStarted. Ingress: API -> reducer."""

    mode: RuntimeMode


class UserInputObserved(DomainBaseModel):
    """Event: UserInputObserved. Ingress: input adapter -> reducer."""

    evidence_id: str = Field(..., min_length=1)
    modality: str = Field(..., min_length=1)
    content_ref: str = Field(..., min_length=1)


class TranscriptHypothesisObserved(DomainBaseModel):
    """Event: TranscriptHypothesisObserved. Ingress: audio adapter -> reducer."""

    evidence_id: str = Field(..., min_length=1)
    text: str
    final: bool


class ControlIntentInterpreted(DomainBaseModel):
    """Event: ControlIntentInterpreted. Ingress: model/fallback -> reducer."""

    control: ControlIntent


class IntentRevisionProposed(DomainBaseModel):
    """Event: IntentRevisionProposed. Ingress: interpreter -> reducer."""

    intent_delta: IntentDelta


class IntentRevisionCommitted(DomainBaseModel):
    """Event: IntentRevisionCommitted. Ingress: reducer policy -> reducer."""

    revision: IntentRevision


class IntentAuthorizationChanged(DomainBaseModel):
    """Event: IntentAuthorizationChanged. Ingress: user/policy -> reducer."""

    revision_id: str = Field(..., min_length=1)
    authorization: Authorization
    evidence_id: str = Field(..., min_length=1)


class BranchPredicted(DomainBaseModel):
    """Event: BranchPredicted. Ingress: branch generator -> reducer."""

    branch: BranchRecord


class BranchPreparationStarted(DomainBaseModel):
    """Event: BranchPreparationStarted. Ingress: dispatcher -> reducer."""

    branch_id: str = Field(..., min_length=1)
    operation_id: str = Field(..., min_length=1)


class BranchPreparationCompleted(DomainBaseModel):
    """Event: BranchPreparationCompleted. Ingress: tool executor -> reducer."""

    branch_id: str = Field(..., min_length=1)
    operation_id: str = Field(..., min_length=1)
    result_evidence_id: str = Field(..., min_length=1)


class BranchPromoted(DomainBaseModel):
    """Event: BranchPromoted. Ingress: reducer policy -> reducer."""

    branch_id: str = Field(..., min_length=1)
    revision_id: str = Field(..., min_length=1)


class BranchInvalidated(DomainBaseModel):
    """Event: BranchInvalidated. Ingress: reducer -> reducer."""

    branch_id: str = Field(..., min_length=1)
    reason: BranchMissReason


class OperationCreated(DomainBaseModel):
    """Event: OperationCreated. Ingress: planner -> reducer."""

    operation: OperationRecord


class OperationPreparationStarted(DomainBaseModel):
    """Event: OperationPreparationStarted. Ingress: dispatcher -> reducer."""

    operation_id: str = Field(..., min_length=1)


class OperationPrepared(DomainBaseModel):
    """Event: OperationPrepared. Ingress: executor -> reducer."""

    operation_id: str = Field(..., min_length=1)
    prepared_args_hash: str = Field(..., min_length=1)
    safe_point: SafePointName


class ToolDispatchRequested(DomainBaseModel):
    """Event: ToolDispatchRequested. Ingress: reducer policy -> reducer."""

    operation_id: str = Field(..., min_length=1)


class ToolDispatchAccepted(DomainBaseModel):
    """Event: ToolDispatchAccepted. Ingress: executor -> reducer."""

    operation_id: str = Field(..., min_length=1)
    provider_request_id: str = Field(..., min_length=1)


class CancellationRequested(DomainBaseModel):
    """Event: CancellationRequested. Ingress: reducer policy -> reducer."""

    operation_id: str = Field(..., min_length=1)
    reason: str = Field(..., min_length=1)


class CancellationAcknowledged(DomainBaseModel):
    """Event: CancellationAcknowledged. Ingress: executor/provider -> reducer."""

    operation_id: str = Field(..., min_length=1)
    scope: CancellationAckScope


class SafePointReached(DomainBaseModel):
    """Event: SafePointReached. Ingress: executor -> reducer."""

    operation_id: str = Field(..., min_length=1)
    name: SafePointName


class ToolResultObserved(DomainBaseModel):
    """Event: ToolResultObserved. Ingress: tool adapter -> reducer."""

    operation_id: str = Field(..., min_length=1)
    provider_request_id: str = Field(..., min_length=1)
    outcome: ToolOutcome
    result: Dict[str, Any]
    provider_effect_id: Optional[str] = None


class ToolTimedOut(DomainBaseModel):
    """Event: ToolTimedOut. Ingress: executor -> reducer."""

    operation_id: str = Field(..., min_length=1)
    after_dispatch: bool


class WorldEffectObserved(DomainBaseModel):
    """Event: WorldEffectObserved. Ingress: result interpreter -> reducer."""

    effect: EffectRecord


class EvidenceRecorded(DomainBaseModel):
    """Event: EvidenceRecorded. Ingress: adapters/reducer -> reducer."""

    evidence: EvidenceRecord


class ClaimProposed(DomainBaseModel):
    """Event: ClaimProposed. Ingress: claim engine -> reducer."""

    claim: ClaimRecord


class ClaimStateChanged(DomainBaseModel):
    """Event: ClaimStateChanged. Ingress: claim engine -> reducer."""

    claim_id: str = Field(..., min_length=1)
    from_state: ClaimState = Field(..., alias="from")
    to_state: ClaimState = Field(..., alias="to")
    evidence_ids: List[str] = Field(default_factory=list)
    reason: str = Field(..., min_length=1)


class SpeechActProposed(DomainBaseModel):
    """Event: SpeechActProposed. Ingress: output planner -> reducer."""

    speech_act: SpeechAct


class SpeechActApproved(DomainBaseModel):
    """Event: SpeechActApproved. Ingress: TRUTHLOCK -> reducer."""

    speech_id: str = Field(..., min_length=1)
    rendered_text: str = Field(..., min_length=1)
    policy_id: str = Field(..., min_length=1)


class SpeechActBlocked(DomainBaseModel):
    """Event: SpeechActBlocked. Ingress: TRUTHLOCK -> reducer."""

    speech_id: str = Field(..., min_length=1)
    reason: str = Field(..., min_length=1)
    max_certainty: ClaimCertainty


class SpeechQueued(DomainBaseModel):
    """Event: SpeechQueued. Ingress: output dispatcher -> reducer."""

    speech_id: str = Field(..., min_length=1)


class SpeechEmissionStarted(DomainBaseModel):
    """Event: SpeechEmissionStarted. Ingress: output adapter -> reducer."""

    speech_id: str = Field(..., min_length=1)


class SpeechEmissionFinished(DomainBaseModel):
    """Event: SpeechEmissionFinished. Ingress: output adapter -> reducer."""

    speech_id: str = Field(..., min_length=1)
    heard: bool


class SpeechCancellationRequested(DomainBaseModel):
    """Event: SpeechCancellationRequested. Ingress: reducer -> reducer."""

    speech_id: str = Field(..., min_length=1)


class DivergenceDetected(DomainBaseModel):
    """Event: DivergenceDetected. Ingress: reconciliation detector -> reducer."""

    case: DivergenceCase


class ReconciliationPlanned(DomainBaseModel):
    """Event: ReconciliationPlanned. Ingress: planner -> reducer."""

    plan: ReconciliationPlan


class ReconciliationAuthorized(DomainBaseModel):
    """Event: ReconciliationAuthorized. Ingress: user/policy -> reducer."""

    plan_id: str = Field(..., min_length=1)
    evidence_id: str = Field(..., min_length=1)


class ReconciliationDenied(DomainBaseModel):
    """Event: ReconciliationDenied. Ingress: user/policy -> reducer."""

    plan_id: str = Field(..., min_length=1)
    evidence_id: str = Field(..., min_length=1)
    reason: str = Field(..., min_length=1)


class ReconciliationStepChanged(DomainBaseModel):
    """Event: ReconciliationStepChanged. Ingress: executor -> reducer."""

    plan_id: str = Field(..., min_length=1)
    step_id: str = Field(..., min_length=1)
    state: PlanStepState
    evidence_id: Optional[str] = None


class DivergenceResolved(DomainBaseModel):
    """Event: DivergenceResolved. Ingress: verifier -> reducer."""

    divergence_id: str = Field(..., min_length=1)
    evidence_ids: List[str] = Field(default_factory=list)


class FaultActivated(DomainBaseModel):
    """Event: FaultActivated. Ingress: scenario runner -> reducer."""

    fault_id: str = Field(..., min_length=1)
    operation_match: Dict[str, Any] = Field(default_factory=dict)


class ProtocolViolationObserved(DomainBaseModel):
    """Event: ProtocolViolationObserved. Ingress: trusted boundary -> reducer."""

    boundary: str = Field(..., min_length=1)
    code: str = Field(..., min_length=1)
    digest: str = Field(..., min_length=1)


# Event Registry Mapping canonical event type string to its payload model class
EVENT_PAYLOAD_REGISTRY: Dict[str, type[DomainBaseModel]] = {
    "SessionStarted": SessionStarted,
    "UserInputObserved": UserInputObserved,
    "TranscriptHypothesisObserved": TranscriptHypothesisObserved,
    "ControlIntentInterpreted": ControlIntentInterpreted,
    "IntentRevisionProposed": IntentRevisionProposed,
    "IntentRevisionCommitted": IntentRevisionCommitted,
    "IntentAuthorizationChanged": IntentAuthorizationChanged,
    "BranchPredicted": BranchPredicted,
    "BranchPreparationStarted": BranchPreparationStarted,
    "BranchPreparationCompleted": BranchPreparationCompleted,
    "BranchPromoted": BranchPromoted,
    "BranchInvalidated": BranchInvalidated,
    "OperationCreated": OperationCreated,
    "OperationPreparationStarted": OperationPreparationStarted,
    "OperationPrepared": OperationPrepared,
    "ToolDispatchRequested": ToolDispatchRequested,
    "ToolDispatchAccepted": ToolDispatchAccepted,
    "CancellationRequested": CancellationRequested,
    "CancellationAcknowledged": CancellationAcknowledged,
    "SafePointReached": SafePointReached,
    "ToolResultObserved": ToolResultObserved,
    "ToolTimedOut": ToolTimedOut,
    "WorldEffectObserved": WorldEffectObserved,
    "EvidenceRecorded": EvidenceRecorded,
    "ClaimProposed": ClaimProposed,
    "ClaimStateChanged": ClaimStateChanged,
    "SpeechActProposed": SpeechActProposed,
    "SpeechActApproved": SpeechActApproved,
    "SpeechActBlocked": SpeechActBlocked,
    "SpeechQueued": SpeechQueued,
    "SpeechEmissionStarted": SpeechEmissionStarted,
    "SpeechEmissionFinished": SpeechEmissionFinished,
    "SpeechCancellationRequested": SpeechCancellationRequested,
    "DivergenceDetected": DivergenceDetected,
    "ReconciliationPlanned": ReconciliationPlanned,
    "ReconciliationAuthorized": ReconciliationAuthorized,
    "ReconciliationDenied": ReconciliationDenied,
    "ReconciliationStepChanged": ReconciliationStepChanged,
    "DivergenceResolved": DivergenceResolved,
    "FaultActivated": FaultActivated,
    "ProtocolViolationObserved": ProtocolViolationObserved,
}
