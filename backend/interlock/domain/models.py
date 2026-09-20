"""Canonical shared domain models for INTERLOCK.

Implements all entities, aggregate states, and simulated booking models
defined in DOMAIN_MODEL.md, EVENT_MODEL.md, and TOOL_DESCRIPTOR.md.
"""

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional, Union
from pydantic import BaseModel, ConfigDict, Field, model_validator

from interlock.domain.enums import (
    ActionType,
    Authorization,
    BranchMissReason,
    BranchState,
    CancellationAckScope,
    CancellationPolicy,
    CancellationState,
    ClaimCertainty,
    ClaimState,
    ControlKind,
    DivergenceState,
    EffectClassification,
    EffectState,
    EventSource,
    EvidenceAuthority,
    EvidenceSource,
    IntentMaturity,
    OperationState,
    PlanState,
    PlanStepKind,
    PlanStepState,
    RuntimeMode,
    SafePointDecision,
    SafePointName,
    SpeechActType,
    SpeechState,
    ToolOutcome,
)


class DomainBaseModel(BaseModel):
    """Base model enforcing strict schema validation and prohibiting extra fields."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=False,
        use_enum_values=True,
    )


# ---------------------------------------------------------------------------
# Core Shared Entities
# ---------------------------------------------------------------------------


class DependencyBinding(DomainBaseModel):
    """Exact operation/branch input binding.

    Canonical path is dotted form; arrays/evidence_ids are sorted before
    canonical JSON SHA-256 hashing.
    """

    path: str = Field(..., min_length=1)
    value_hash: str = Field(..., min_length=1)
    evidence_ids: List[str] = Field(default_factory=list)


class ControlIntent(DomainBaseModel):
    """Model proposal produced by semantic control interpretation.

    Confidence is bounded in [0.0, 1.0]. Reducer applies deterministic policy.
    """

    control_id: str = Field(..., min_length=1)
    kind: ControlKind
    confidence: float = Field(..., ge=0.0, le=1.0)
    consequential: bool
    target_refs: List[str] = Field(default_factory=list)
    raw_evidence_id: str = Field(..., min_length=1)
    clarification: Optional[str] = None


class IntentDelta(DomainBaseModel):
    """Validated proposed intent mutation."""

    target_intent_id: str = Field(..., min_length=1)
    set_fields: Dict[str, Any] = Field(default_factory=dict)
    unset_fields: List[str] = Field(default_factory=list)
    add_goals: List[Dict[str, Any]] = Field(default_factory=list)
    retract_goals: List[str] = Field(default_factory=list)
    confidence: float = Field(..., ge=0.0, le=1.0)


class IntentRevision(DomainBaseModel):
    """Immutable intent revision representing a point in goal evolution."""

    revision_id: str = Field(..., min_length=1)
    intent_id: str = Field(..., min_length=1)
    parent_revision_id: Optional[str] = None
    values: Dict[str, Any] = Field(default_factory=dict)
    maturity: IntentMaturity
    authorization: Authorization
    created_by_event_id: str = Field(..., min_length=1)
    dependency_fingerprint: str = Field(..., min_length=1)


class IntentNode(DomainBaseModel):
    """Stable goal identity tracking revision chains."""

    intent_id: str = Field(..., min_length=1)
    goal_type: str = Field(..., min_length=1)
    revisions: List[str] = Field(default_factory=list)
    active_revision_id: Optional[str] = None


class BranchRecord(DomainBaseModel):
    """Bounded speculative read plan."""

    branch_id: str = Field(..., min_length=1)
    candidate_delta: IntentDelta
    confidence: float = Field(..., ge=0.0, le=1.0)
    state: BranchState
    bindings: List[DependencyBinding] = Field(default_factory=list)
    fingerprint: str = Field(..., min_length=1)
    expires_at: datetime
    estimated_cost: int = Field(..., ge=0)
    operation_ids: List[str] = Field(default_factory=list)


class ErrorRecord(DomainBaseModel):
    """Structured error information for operation and tool failures."""

    code: str = Field(..., min_length=1)
    message: str = Field(..., min_length=1)
    retryable: bool = False


class RetryPolicy(DomainBaseModel):
    """Tool descriptor retry policy."""

    max_attempts: int = Field(default=1, ge=0)
    retry_on: List[str] = Field(default_factory=list)


class IdempotencyPolicy(DomainBaseModel):
    """Tool descriptor idempotency declaration."""

    supported: bool = False
    scope: Optional[str] = None
    key_field: Optional[str] = None


class CompensationPolicy(DomainBaseModel):
    """Tool descriptor compensation declaration."""

    supported: bool = False
    tool_name: Optional[str] = None
    requires_authorization: bool = True


class ConfirmationSemantics(DomainBaseModel):
    """Tool descriptor confirmation mapping semantics."""

    acknowledgement: Optional[str] = None
    commit: Optional[str] = None
    unknown: Optional[str] = None
    authoritative_fields: List[str] = Field(default_factory=list)


class ToolDescriptor(DomainBaseModel):
    """Normalized trusted registration for a tool."""

    tool_name: str = Field(..., min_length=1)
    manifest_version: int = Field(default=1, ge=1)
    argument_schema: Dict[str, Any]
    result_schema: Dict[str, Any]
    effect_classification: EffectClassification
    action_type: ActionType
    cancellation_policy: CancellationPolicy
    safe_points: List[SafePointName] = Field(default_factory=list)
    timeout_ms: int = Field(..., ge=1)
    retry_policy: RetryPolicy
    idempotency: IdempotencyPolicy
    compensation: CompensationPolicy
    confirmation_semantics: ConfirmationSemantics


class OperationRecord(DomainBaseModel):
    """Tracks local execution separately from world effects.

    Invariant I2: speculative=true requires READ_ONLY action_type.
    """

    operation_id: str = Field(..., min_length=1)
    tool_name: str = Field(..., min_length=1)
    args: Dict[str, Any] = Field(default_factory=dict)
    intent_revision_id: str = Field(..., min_length=1)
    bindings: List[DependencyBinding] = Field(default_factory=list)
    fingerprint: str = Field(..., min_length=1)
    action_type: ActionType
    cancellation_policy: CancellationPolicy
    state: OperationState
    cancellation_state: CancellationState
    effect_state: EffectState
    speculative: bool
    logical_action_id: str = Field(..., min_length=1)
    idempotency_key: str = Field(..., min_length=1)
    descriptor_capability_hash: Optional[str] = None
    schema_version: Literal[1] = 1
    provider_request_id: Optional[str] = None
    error: Optional[ErrorRecord] = None

    @model_validator(mode="after")
    def validate_speculative_invariant(self) -> "OperationRecord":
        """Invariant I2: speculative operations must be READ_ONLY."""
        if self.speculative and self.action_type != ActionType.READ_ONLY:
            raise ValueError(
                f"Speculative operation must have action_type READ_ONLY, got {self.action_type}"
            )
        return self


class EffectRecord(DomainBaseModel):
    """Append-only world ledger entry.

    COMMITTED and COMPENSATED effects require AUTHORITATIVE evidence.
    """

    effect_id: str = Field(..., min_length=1)
    logical_action_id: str = Field(..., min_length=1)
    operation_id: str = Field(..., min_length=1)
    provider_effect_id: str = Field(..., min_length=1)
    effect_type: str = Field(..., min_length=1)
    subject: Dict[str, Any] = Field(default_factory=dict)
    parameters: Dict[str, Any] = Field(default_factory=dict)
    state: EffectState
    observed_at: datetime
    authority: EvidenceAuthority
    evidence_ids: List[str] = Field(default_factory=list)
    schema_version: Literal[1] = 1
    supersedes_effect_id: Optional[str] = None

    @model_validator(mode="after")
    def validate_effect_authority(self) -> "EffectRecord":
        """Validate that COMMITTED and COMPENSATED effects require AUTHORITATIVE evidence."""
        if self.state in (EffectState.COMMITTED, EffectState.COMPENSATED):
            if self.authority != EvidenceAuthority.AUTHORITATIVE:
                raise ValueError(
                    f"Effect state {self.state} requires AUTHORITATIVE evidence, got {self.authority}"
                )
            if not self.evidence_ids:
                raise ValueError(
                    f"Effect state {self.state} requires at least one supporting evidence ID"
                )
        return self


class EvidenceRecord(DomainBaseModel):
    """Immutable observation or derived interpretation."""

    evidence_id: str = Field(..., min_length=1)
    source: EvidenceSource
    kind: str = Field(..., min_length=1)
    captured_at: datetime
    content_ref: str = Field(..., min_length=1)
    content_hash: str = Field(..., min_length=1)
    authority: EvidenceAuthority
    provenance: Dict[str, Any] = Field(default_factory=dict)
    schema_version: Literal[1] = 1
    expires_at: Optional[datetime] = None
    derived_from: Optional[List[str]] = None


class ClaimRecord(DomainBaseModel):
    """ClaimGraph node linking assertions to required evidence rules.

    Invariant I6/I9: CONFIRMED claims require supporting evidence IDs.
    """

    claim_id: str = Field(..., min_length=1)
    predicate: str = Field(..., min_length=1)
    subject: Dict[str, Any] = Field(default_factory=dict)
    object: Dict[str, Any] = Field(default_factory=dict)
    state: ClaimState
    required_evidence_rule: str = Field(..., min_length=1)
    supporting_evidence_ids: List[str] = Field(default_factory=list)
    intent_revision_id: str = Field(..., min_length=1)
    updated_by_event_id: str = Field(..., min_length=1)
    schema_version: Literal[1] = 1

    @model_validator(mode="after")
    def validate_claim_evidence(self) -> "ClaimRecord":
        """Validate that CONFIRMED claims have supporting evidence."""
        if self.state == ClaimState.CONFIRMED and not self.supporting_evidence_ids:
            raise ValueError("Claim cannot be CONFIRMED with empty supporting_evidence_ids")
        return self


class SpeechAct(DomainBaseModel):
    """Structured output proposal gated by TRUTHLOCK."""

    speech_id: str = Field(..., min_length=1)
    act_type: SpeechActType
    template_id: str = Field(..., min_length=1)
    slots: Dict[str, Any] = Field(default_factory=dict)
    claim_ids: List[str] = Field(default_factory=list)
    requested_certainty: ClaimCertainty
    state: SpeechState
    created_by_event_id: str = Field(..., min_length=1)
    schema_version: Literal[1] = 1
    supersedes_speech_id: Optional[str] = None


class DivergenceCase(DomainBaseModel):
    """Explicit intent/world mismatch case."""

    divergence_id: str = Field(..., min_length=1)
    desired_fingerprint: str = Field(..., min_length=1)
    observed_effect_ids: List[str] = Field(default_factory=list)
    kind: str = Field(..., min_length=1)
    state: DivergenceState
    detected_by_event_id: str = Field(..., min_length=1)
    authorization_required: bool = True
    schema_version: Literal[1] = 1


class PlanStep(DomainBaseModel):
    """Single step in a reconciliation repair plan."""

    step_id: str = Field(..., min_length=1)
    kind: PlanStepKind
    tool_name: str = Field(..., min_length=1)
    arguments: Dict[str, Any] = Field(default_factory=dict)
    state: PlanStepState
    requires_authorization: bool = True
    idempotency_key: Optional[str] = None


class ReconciliationPlan(DomainBaseModel):
    """Ordered verify/compensate/commit/verify repair plan."""

    plan_id: str = Field(..., min_length=1)
    divergence_id: str = Field(..., min_length=1)
    based_on_intent_revision_id: str = Field(..., min_length=1)
    steps: List[PlanStep] = Field(default_factory=list)
    state: PlanState
    provider_capability_hash: str = Field(..., min_length=1)
    schema_version: Literal[1] = 1
    authorized_by_evidence_id: Optional[str] = None


class ScenarioStep(DomainBaseModel):
    """Step in a deterministic test scenario.

    Step is the ordered union of timed input, advance_to, or assert checkpoint.
    """

    input: Optional[Dict[str, Any]] = None
    advance_to: Optional[int] = Field(default=None, ge=0)
    assert_: Optional[Dict[str, Any]] = Field(default=None, alias="assert")

    @model_validator(mode="after")
    def validate_step_content(self) -> "ScenarioStep":
        """Ensure exactly one of input, advance_to, or assert is provided."""
        provided = sum(x is not None for x in [self.input, self.advance_to, self.assert_])
        if provided != 1:
            raise ValueError("ScenarioStep must define exactly one of input, advance_to, or assert")
        return self


class ScenarioDefinition(DomainBaseModel):
    """Deterministic test specification."""

    scenario_id: str = Field(..., min_length=1)
    schema_version: Literal[1] = 1
    fixture: Optional[str] = None
    initial_state: Dict[str, Any] = Field(default_factory=dict)
    tools: Dict[str, Any] = Field(default_factory=dict)
    faults: List[Dict[str, Any]] = Field(default_factory=list)
    steps: List[ScenarioStep] = Field(default_factory=list)
    expect: Dict[str, Any] = Field(default_factory=dict)


class MetricsSnapshot(DomainBaseModel):
    """Derived projection of session metrics pinned through a sequence."""

    session_id: str = Field(..., min_length=1)
    through_sequence: int = Field(..., ge=0)
    counters: Dict[str, int] = Field(default_factory=dict)
    durations_ms: Dict[str, float] = Field(default_factory=dict)
    gauges: Dict[str, float] = Field(default_factory=dict)


class SessionState(DomainBaseModel):
    """Reducer-owned aggregate state representing authoritative session state."""

    session_id: str = Field(..., min_length=1)
    last_sequence: int = Field(default=0, ge=0)
    mode: RuntimeMode = RuntimeMode.DEMO
    intents: Dict[str, IntentNode] = Field(default_factory=dict)
    active_intent_id: Optional[str] = None
    branches: Dict[str, BranchRecord] = Field(default_factory=dict)
    operations: Dict[str, OperationRecord] = Field(default_factory=dict)
    effects: Dict[str, EffectRecord] = Field(default_factory=dict)
    evidence: Dict[str, EvidenceRecord] = Field(default_factory=dict)
    claims: Dict[str, ClaimRecord] = Field(default_factory=dict)
    divergences: Dict[str, DivergenceCase] = Field(default_factory=dict)
    plans: Dict[str, ReconciliationPlan] = Field(default_factory=dict)
    speech: Dict[str, SpeechAct] = Field(default_factory=dict)
    metrics: MetricsSnapshot = Field(
        default_factory=lambda: MetricsSnapshot(session_id="default", through_sequence=0)
    )
    schema_version: Literal[1] = 1


class EventEnvelope(DomainBaseModel):
    """Immutable accepted fact recorded in the journal.

    Validation rules:
    - sequence > 0
    - logical_time >= 0
    - schema_version == 1
    - payload: valid object
    """

    event_id: str = Field(..., min_length=1)
    session_id: str = Field(..., min_length=1)
    sequence: int = Field(..., gt=0)
    event_type: str = Field(..., min_length=1)
    source: EventSource
    occurred_at: datetime
    logical_time: int = Field(..., ge=0)
    schema_version: Literal[1] = 1
    payload: Dict[str, Any] = Field(...)
    correlation_id: Optional[str] = None
    causation_id: Optional[str] = None
    dedupe_key: Optional[str] = None


# ---------------------------------------------------------------------------
# Canonical Simulated Booking Schemas (DOMAIN_MODEL.md & TOOL_DESCRIPTOR.md)
# ---------------------------------------------------------------------------


class BookingRequest(DomainBaseModel):
    """Simulated appointment booking request."""

    center_id: str = Field(..., min_length=1)
    requested_slot: datetime
    idempotency_key: str = Field(..., min_length=1)


class BookingResultAcknowledgement(DomainBaseModel):
    """Receipt acknowledgement for a booking request."""

    phase: Literal["ACKNOWLEDGEMENT"] = "ACKNOWLEDGEMENT"
    status: Literal["REQUEST_RECEIVED"] = "REQUEST_RECEIVED"
    provider_request_id: str = Field(..., min_length=1)
    center_id: str = Field(..., min_length=1)
    requested_slot: datetime


class BookingResultConfirmed(DomainBaseModel):
    """Authoritative confirmation of a completed booking."""

    phase: Literal["FINAL"] = "FINAL"
    status: Literal["BOOKING_CONFIRMED"] = "BOOKING_CONFIRMED"
    provider_request_id: str = Field(..., min_length=1)
    provider_booking_id: str = Field(..., min_length=1)
    center_id: str = Field(..., min_length=1)
    requested_slot: datetime
    confirmed_slot: datetime


class BookingResultFailed(DomainBaseModel):
    """Terminal failure outcome of a booking request."""

    phase: Literal["FINAL"] = "FINAL"
    status: Literal["BOOKING_FAILED"] = "BOOKING_FAILED"
    provider_request_id: str = Field(..., min_length=1)
    error: ErrorRecord


class BookingResultUnknown(DomainBaseModel):
    """Ambiguous or timeout outcome of a booking request."""

    phase: Literal["FINAL"] = "FINAL"
    status: Literal["OUTCOME_UNKNOWN"] = "OUTCOME_UNKNOWN"
    provider_request_id: str = Field(..., min_length=1)


BookingResult = Union[
    BookingResultAcknowledgement,
    BookingResultConfirmed,
    BookingResultFailed,
    BookingResultUnknown,
]


class CancellationRequest(DomainBaseModel):
    """Simulated appointment cancellation request."""

    provider_booking_id: str = Field(..., min_length=1)
    center_id: str = Field(..., min_length=1)
    idempotency_key: str = Field(..., min_length=1)


class CancellationResultConfirmed(DomainBaseModel):
    """Authoritative confirmation of appointment cancellation."""

    phase: Optional[Literal["FINAL"]] = "FINAL"
    status: Literal["CANCELLATION_CONFIRMED"] = "CANCELLATION_CONFIRMED"
    provider_request_id: str = Field(..., min_length=1)
    provider_booking_id: str = Field(..., min_length=1)
    center_id: str = Field(..., min_length=1)
    cancelled_at: datetime


class CancellationResultFailed(DomainBaseModel):
    """Failure outcome of appointment cancellation."""

    phase: Optional[Literal["FINAL"]] = "FINAL"
    status: Literal["CANCELLATION_FAILED"] = "CANCELLATION_FAILED"
    provider_request_id: str = Field(..., min_length=1)
    error: ErrorRecord


class CancellationResultUnknown(DomainBaseModel):
    """Unknown outcome of appointment cancellation."""

    phase: Optional[Literal["FINAL"]] = "FINAL"
    status: Literal["OUTCOME_UNKNOWN"] = "OUTCOME_UNKNOWN"
    provider_request_id: str = Field(..., min_length=1)


CancellationResult = Union[
    CancellationResultConfirmed,
    CancellationResultFailed,
    CancellationResultUnknown,
]
