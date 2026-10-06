"""Canonical domain enumerations for INTERLOCK.

All enums use uppercase string tokens as defined in architecture/DOMAIN_MODEL.md.
"""

from enum import Enum


class ControlKind(str, Enum):
    """Semantic control classification kinds."""

    BACKCHANNEL = "BACKCHANNEL"
    CANCEL_SPEECH = "CANCEL_SPEECH"
    CORRECT = "CORRECT"
    ADD_GOAL = "ADD_GOAL"
    RETRACT_GOAL = "RETRACT_GOAL"
    PAUSE = "PAUSE"
    RESUME = "RESUME"
    REFER = "REFER"
    NEW_TOPIC = "NEW_TOPIC"
    CLARIFY = "CLARIFY"


class IntentMaturity(str, Enum):
    """Maturity lifecycle of an intent revision."""

    PROVISIONAL = "PROVISIONAL"
    COMMITTED = "COMMITTED"
    SUPERSEDED = "SUPERSEDED"


class Authorization(str, Enum):
    """User/policy action authorization state."""

    NOT_REQUESTED = "NOT_REQUESTED"
    REQUIRED = "REQUIRED"
    AUTHORIZED = "AUTHORIZED"
    DENIED = "DENIED"
    EXPIRED = "EXPIRED"


class ActionType(str, Enum):
    """Action safety classification for tool descriptors and operations."""

    READ_ONLY = "READ_ONLY"
    REVERSIBLE = "REVERSIBLE"
    IRREVERSIBLE = "IRREVERSIBLE"


class CancellationPolicy(str, Enum):
    """Preemption/cancellation policy for tool execution."""

    IMMEDIATE = "IMMEDIATE"
    AT_SAFEPOINT = "AT_SAFEPOINT"
    NONCANCELLABLE = "NONCANCELLABLE"


class OperationState(str, Enum):
    """Local workflow lifecycle state of an operation."""

    CREATED = "CREATED"
    PREPARING = "PREPARING"
    READY = "READY"
    DISPATCHED = "DISPATCHED"
    WAITING = "WAITING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    TIMED_OUT = "TIMED_OUT"
    CANCELLED = "CANCELLED"
    SUPERSEDED = "SUPERSEDED"


class CancellationState(str, Enum):
    """Cancellation request state orthogonal to operation and effect states."""

    NONE = "NONE"
    REQUESTED = "REQUESTED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    REJECTED = "REJECTED"
    TOO_LATE = "TOO_LATE"


class EffectState(str, Enum):
    """Observed external world effect lifecycle state."""

    NOT_STARTED = "NOT_STARTED"
    IN_FLIGHT = "IN_FLIGHT"
    COMMITTED = "COMMITTED"
    FAILED = "FAILED"
    OUTCOME_UNKNOWN = "OUTCOME_UNKNOWN"
    COMPENSATED = "COMPENSATED"


class BranchState(str, Enum):
    """Speculative branch lifecycle state."""

    PREDICTED = "PREDICTED"
    PREPARING = "PREPARING"
    READY = "READY"
    PROMOTED = "PROMOTED"
    EXPIRED = "EXPIRED"
    EVICTED = "EVICTED"
    INVALIDATED = "INVALIDATED"
    FAILED = "FAILED"


class EvidenceSource(str, Enum):
    """Provenance source of an evidence record."""

    USER = "USER"
    TOOL = "TOOL"
    FRAME = "FRAME"
    AUDIO = "AUDIO"
    SYSTEM = "SYSTEM"


class EvidenceAuthority(str, Enum):
    """Authority level of evidence for establishing committed facts."""

    AUTHORITATIVE = "AUTHORITATIVE"
    NON_AUTHORITATIVE = "NON_AUTHORITATIVE"
    DERIVED = "DERIVED"


class ClaimState(str, Enum):
    """Verification lifecycle state of a claim."""

    PROPOSED = "PROPOSED"
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    CONTRADICTED = "CONTRADICTED"
    UNCERTAIN = "UNCERTAIN"
    STALE = "STALE"
    SUPERSEDED = "SUPERSEDED"


class SpeechState(str, Enum):
    """Lifecycle state of an emitted or planned speech act."""

    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    QUEUED = "QUEUED"
    EMITTING = "EMITTING"
    EMITTED = "EMITTED"
    CANCELLED = "CANCELLED"
    BLOCKED = "BLOCKED"
    CORRECTION_REQUIRED = "CORRECTION_REQUIRED"


class DivergenceState(str, Enum):
    """State of an explicit intent/world mismatch case."""

    OPEN = "OPEN"
    PLANNED = "PLANNED"
    RECONCILING = "RECONCILING"
    RESOLVED = "RESOLVED"
    ESCALATED = "ESCALATED"


class PlanState(str, Enum):
    """Lifecycle state of a reconciliation repair plan."""

    DRAFT = "DRAFT"
    AUTHORIZED = "AUTHORIZED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    SUPERSEDED = "SUPERSEDED"


class PlanStepState(str, Enum):
    """Execution state of an individual reconciliation plan step."""

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class PlanStepKind(str, Enum):
    """Canonical ordering kind for reconciliation plan steps."""

    VERIFY_OBSERVED = "VERIFY_OBSERVED"
    COMPENSATE_OBSOLETE = "COMPENSATE_OBSOLETE"
    VERIFY_COMPENSATION = "VERIFY_COMPENSATION"
    PREPARE_DESIRED = "PREPARE_DESIRED"
    COMMIT_DESIRED = "COMMIT_DESIRED"
    VERIFY_FINAL = "VERIFY_FINAL"


class EventSource(str, Enum):
    """Ingress source of an event envelope."""

    USER = "USER"
    INPUT_ADAPTER = "INPUT_ADAPTER"
    MODEL = "MODEL"
    POLICY = "POLICY"
    TOOL = "TOOL"
    OUTPUT_ADAPTER = "OUTPUT_ADAPTER"
    SCENARIO = "SCENARIO"
    SYSTEM = "SYSTEM"


class ToolOutcome(str, Enum):
    """Observation outcome reported for a tool execution."""

    ACKNOWLEDGED = "ACKNOWLEDGED"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"


class RuntimeMode(str, Enum):
    """Operating execution mode of the runtime session."""

    DEMO = "DEMO"
    LIVE = "LIVE"
    TEST = "TEST"
    REPLAY = "REPLAY"


class EffectClassification(str, Enum):
    """Tool descriptor side-effect classification."""

    NONE = "NONE"
    EXTERNAL_STATE_CHANGE = "EXTERNAL_STATE_CHANGE"
    UNKNOWN = "UNKNOWN"


class CancellationAckScope(str, Enum):
    """Scope of acknowledgement returned by provider or executor."""

    LOCAL_TASK = "LOCAL_TASK"
    PROVIDER_REQUEST_ACCEPTED = "PROVIDER_REQUEST_ACCEPTED"
    PROVIDER_CANCEL_ACCEPTED = "PROVIDER_CANCEL_ACCEPTED"


class SpeechActType(str, Enum):
    """Functional classification of a speech act."""

    PROGRESS = "PROGRESS"
    CLARIFICATION = "CLARIFICATION"
    RESULT = "RESULT"
    FAILURE = "FAILURE"
    UNCERTAINTY = "UNCERTAINTY"
    DIVERGENCE = "DIVERGENCE"
    CORRECTION = "CORRECTION"


class ClaimCertainty(str, Enum):
    """Epistemic certainty level required/asserted for a claim."""

    PROGRESS = "PROGRESS"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    CONFIRMED = "CONFIRMED"
    UNCERTAIN = "UNCERTAIN"


class SafePointName(str, Enum):
    """Named safe points for preemption and dispatch revalidation."""

    BEFORE_PROVIDER_DISPATCH = "BEFORE_PROVIDER_DISPATCH"


class SafePointDecision(str, Enum):
    """Decision returned by SafePointPolicy."""

    CONTINUE = "CONTINUE"
    CANCEL = "CANCEL"
    HOLD = "HOLD"
    UNKNOWN = "UNKNOWN"


class BranchMissReason(str, Enum):
    """Categorization for speculative branch cache misses."""

    NOT_FOUND = "NOT_FOUND"
    NOT_READY = "NOT_READY"
    EXPIRED = "EXPIRED"
    FINGERPRINT_MISMATCH = "FINGERPRINT_MISMATCH"
    CAPABILITY_CHANGED = "CAPABILITY_CHANGED"
