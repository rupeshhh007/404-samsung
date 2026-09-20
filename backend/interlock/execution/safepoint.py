"""EXE-003 final local BEFORE_PROVIDER_DISPATCH eligibility policy.

The caller supplies one coherent reducer snapshot and the current dependency
evidence projection. A decision is valid at this check only; ToolRuntime must
still enforce the creation-time capability identity before I/O. No events or
commands are emitted here.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re
from typing import Mapping, Sequence

from pydantic import ValidationError

from interlock.domain.enums import (
    ActionType, Authorization, CancellationPolicy, CancellationState,
    EffectClassification, EffectState, IntentMaturity, OperationState,
    SafePointDecision, SafePointName,
)
from interlock.domain.models import IntentRevision, OperationRecord, SessionState
from interlock.execution.descriptors import ToolRegistry
from interlock.execution.idempotency import IdempotencyError, strict_json_copy
from interlock.intelligence.intent_graph import (
    IntentGraphError, bind_dependencies, dependency_fingerprint,
)


class SafePointError(ValueError):
    """Invalid boundary input; callers must not dispatch after this error."""


class SafePointReason(str, Enum):
    """Local explanations for the canonical decisions; no state transitions."""

    CURRENT_AND_PERMITTED = "CURRENT_AND_PERMITTED"
    DESCRIPTOR_UNKNOWN = "DESCRIPTOR_UNKNOWN"
    CAPABILITY_UNAVAILABLE = "CAPABILITY_UNAVAILABLE"
    DESCRIPTOR_CHANGED = "DESCRIPTOR_CHANGED"
    INVALID_OPERATION_SNAPSHOT = "INVALID_OPERATION_SNAPSHOT"
    SPECULATION_FORBIDDEN = "SPECULATION_FORBIDDEN"
    INTENT_SUPERSEDED = "INTENT_SUPERSEDED"
    DEPENDENCY_CHANGED = "DEPENDENCY_CHANGED"
    DEPENDENCY_UNRESOLVED = "DEPENDENCY_UNRESOLVED"
    INTENT_NOT_COMMITTED = "INTENT_NOT_COMMITTED"
    AUTHORIZATION_REQUIRED = "AUTHORIZATION_REQUIRED"
    SESSION_PAUSED = "SESSION_PAUSED"
    CANCELLATION_REQUESTED = "CANCELLATION_REQUESTED"
    OPERATION_NOT_READY = "OPERATION_NOT_READY"


@dataclass(frozen=True, slots=True)
class SafePointResult:
    decision: SafePointDecision
    reason: SafePointReason
    affected_paths: tuple[str, ...] = ()
    expected_fingerprint: str | None = None
    current_fingerprint: str | None = None
    stored_capability_hash: str | None = None
    current_capability_hash: str | None = None


class SafePointPolicy:
    """Stateless decisions over caller-owned state and trusted registrations."""

    @staticmethod
    def decide(
        *,
        operation: OperationRecord,
        current_revision: IntentRevision,
        session_state: SessionState,
        registry: ToolRegistry,
        evidence_ids_by_path: Mapping[str, Sequence[str]],
    ) -> SafePointResult:
        """Evaluate the named pre-dispatch boundary, without crossing it.

        Boundary/schema, snapshot consistency and pre-dispatch state checks
        precede policy. Policy
        follows SAFEPOINT.md's table order: descriptor, speculation, freshness,
        maturity/authorization, pause, then cancellation.
        Missing/unresolvable evidence holds; malformed models raise SafePointError.
        UNKNOWN is reserved: this pre-dispatch contract defines no case needing it.

        evidence_ids_by_path must explicitly cover exactly the bound paths, with
        an empty list/tuple for a path with no evidence. Historical evidence is
        never silently reused as the current evidence projection.
        """
        if not isinstance(registry, ToolRegistry):
            raise SafePointError("registry must be a trusted ToolRegistry")
        if not isinstance(operation, OperationRecord) or not isinstance(
            current_revision, IntentRevision
        ) or not isinstance(session_state, SessionState):
            raise SafePointError("operation, revision and session models are required")
        if type(session_state.paused) is not bool or type(operation.speculative) is not bool:
            raise SafePointError("pause and speculation flags must be booleans")
        try:
            op = OperationRecord.model_validate(strict_json_copy(operation.model_dump()))
            revision = IntentRevision.model_validate(strict_json_copy(current_revision.model_dump()))
            session = SessionState.model_validate(strict_json_copy(session_state.model_dump(mode="json")))
        except (ValidationError, IdempotencyError, ValueError, TypeError) as exc:
            raise SafePointError("invalid operation, intent or session snapshot") from exc
        if session.operations.get(op.operation_id) != op:
            raise SafePointError("operation must match the reducer-owned session snapshot")
        node = session.intents.get(revision.intent_id)
        if (
            node is None or node.active_revision_id != revision.revision_id
            or revision.revision_id not in node.revisions
        ):
            raise SafePointError("current revision must match its session intent node")

        stored_hash = op.descriptor_capability_hash
        current_hash = None
        current_fingerprint = None

        def result(decision: SafePointDecision, reason: SafePointReason,
                   paths: tuple[str, ...] = ()) -> SafePointResult:
            return SafePointResult(
                decision, reason, paths, op.fingerprint, current_fingerprint,
                stored_hash, current_hash,
            )

        # This gate cannot decide post-dispatch cancellation or world outcomes.
        if (op.state != OperationState.READY or op.effect_state != EffectState.NOT_STARTED
                or op.provider_request_id is not None
                or op.cancellation_state not in (
                    CancellationState.NONE, CancellationState.REQUESTED
                )):
            return result(SafePointDecision.HOLD, SafePointReason.OPERATION_NOT_READY)

        try:
            descriptor = registry.get(op.tool_name)
            current_hash = registry.capability_hash(op.tool_name)
        except (KeyError, ValueError):
            return result(SafePointDecision.HOLD, SafePointReason.DESCRIPTOR_UNKNOWN)
        if not _is_hash(stored_hash) or not _is_hash(current_hash):
            return result(SafePointDecision.HOLD, SafePointReason.CAPABILITY_UNAVAILABLE)
        if stored_hash != current_hash:
            return result(SafePointDecision.HOLD, SafePointReason.DESCRIPTOR_CHANGED)
        safe_read = (
            descriptor.action_type == ActionType.READ_ONLY
            and descriptor.effect_classification == EffectClassification.NONE
        )
        if op.speculative and not safe_read:
            return result(SafePointDecision.CANCEL, SafePointReason.SPECULATION_FORBIDDEN)
        if (op.action_type != descriptor.action_type
                or op.cancellation_policy != descriptor.cancellation_policy):
            return result(SafePointDecision.HOLD, SafePointReason.INVALID_OPERATION_SNAPSHOT)
        try:
            if not op.bindings or dependency_fingerprint(op.bindings) != op.fingerprint:
                return result(SafePointDecision.HOLD, SafePointReason.INVALID_OPERATION_SNAPSHOT)
        except (IntentGraphError, TypeError, ValueError):
            return result(SafePointDecision.HOLD, SafePointReason.INVALID_OPERATION_SNAPSHOT)
        if (session.active_intent_id != revision.intent_id
                or op.intent_revision_id not in node.revisions
                or revision.maturity == IntentMaturity.SUPERSEDED):
            return result(SafePointDecision.CANCEL, SafePointReason.INTENT_SUPERSEDED)

        paths = tuple(sorted(binding.path for binding in op.bindings))
        if not isinstance(evidence_ids_by_path, Mapping) or set(evidence_ids_by_path) != set(paths):
            return result(SafePointDecision.HOLD, SafePointReason.DEPENDENCY_UNRESOLVED)
        try:
            current = bind_dependencies(
                revision, paths, evidence_ids_by_path=evidence_ids_by_path,
            )
            current_fingerprint = dependency_fingerprint(current)
        except (IntentGraphError, TypeError, ValueError):
            return result(SafePointDecision.HOLD, SafePointReason.DEPENDENCY_UNRESOLVED)
        if current_fingerprint != op.fingerprint:
            previous = {binding.path: binding for binding in op.bindings}
            changed = tuple(binding.path for binding in current if
                dependency_fingerprint([binding]) != dependency_fingerprint([previous[binding.path]]))
            return result(SafePointDecision.CANCEL, SafePointReason.DEPENDENCY_CHANGED, changed)
        if not safe_read:
            if revision.maturity != IntentMaturity.COMMITTED:
                return result(SafePointDecision.HOLD, SafePointReason.INTENT_NOT_COMMITTED)
            if revision.authorization != Authorization.AUTHORIZED:
                return result(SafePointDecision.HOLD, SafePointReason.AUTHORIZATION_REQUIRED)
        if session.paused:
            return result(SafePointDecision.HOLD, SafePointReason.SESSION_PAUSED)
        if op.cancellation_state == CancellationState.REQUESTED and (
            descriptor.cancellation_policy == CancellationPolicy.IMMEDIATE
            or (descriptor.cancellation_policy == CancellationPolicy.AT_SAFEPOINT
                and SafePointName.BEFORE_PROVIDER_DISPATCH in descriptor.safe_points)
        ):
            return result(SafePointDecision.CANCEL, SafePointReason.CANCELLATION_REQUESTED)
        return result(SafePointDecision.CONTINUE, SafePointReason.CURRENT_AND_PERMITTED)


def _is_hash(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r"sha256:[0-9a-f]{64}", value) is not None
