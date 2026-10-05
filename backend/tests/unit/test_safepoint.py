"""T-SAF-01, T-SAF-02, T-INV-I3-P, T-INV-I3-N,
T-INV-I14-P, T-INV-I14-N: final dispatch gate.
"""

from interlock.domain.enums import (
    Authorization, CancellationPolicy, CancellationState, IntentMaturity,
    OperationState, RuntimeMode, SafePointDecision,
)
from interlock.domain.models import IntentNode, IntentRevision, SessionState
from interlock.execution.descriptors import ToolRegistry
from interlock.execution.operations import OperationManager
from interlock.execution.safepoint import SafePointPolicy
from interlock.intelligence.intent_graph import bind_dependencies, dependency_fingerprint
from interlock.testing.fixtures import register_tool_manifests


def _case():
    registry = ToolRegistry()
    register_tool_manifests(registry)
    values = {"center_id": "center-1", "requested_slot": "2026-01-01T11:00:00Z"}
    bindings = bind_dependencies(values, values.keys())
    revision = IntentRevision(
        revision_id="r1", intent_id="intent", values=values,
        maturity=IntentMaturity.COMMITTED, authorization=Authorization.AUTHORIZED,
        created_by_event_id="event", dependency_fingerprint=dependency_fingerprint(bindings),
    )
    operation = OperationManager(registry).create_operation(
        operation_id="op", session_id="s", intent_goal_id="intent",
        intent_revision=revision, bindings=bindings, tool_name="appointment.book",
        arguments=values, existing_operation_ids=set(), known_idempotency_digests={},
    )
    operation.state = OperationState.READY
    session = SessionState(
        session_id="s", last_sequence=3, mode=RuntimeMode.TEST,
        active_intent_id="intent",
        intents={"intent": IntentNode(intent_id="intent", goal_type="booking",
                                       revisions=["r1"], active_revision_id="r1")},
        revisions={"r1": revision}, operations={"op": operation},
    )
    evidence = {binding.path: list(binding.evidence_ids) for binding in bindings}
    return registry, revision, operation, session, evidence


def _decide(registry, revision, operation, session, evidence):
    return SafePointPolicy.decide(
        operation=operation, current_revision=revision, session_state=session,
        registry=registry, evidence_ids_by_path=evidence,
    )


def test_t_saf_01_t_inv_i14_p_exact_authorization_allows_dispatch_event():
    result = _decide(*_case())
    assert result.decision == SafePointDecision.CONTINUE
    assert result.follow_up_event.operation_id == "op"
    assert type(result.follow_up_event).__name__ == "ToolDispatchRequested"


def test_t_saf_02_t_inv_i14_n_provisional_or_expired_holds():
    for change in ({"maturity": IntentMaturity.PROVISIONAL},
                   {"authorization": Authorization.EXPIRED}):
        registry, revision, operation, session, evidence = _case()
        revision = revision.model_copy(update=change)
        session.revisions["r1"] = revision
        result = _decide(registry, revision, operation, session, evidence)
        assert result.decision == SafePointDecision.HOLD
        assert result.follow_up_event is None


def test_t_saf_01_t_inv_i3_p_named_safepoint_cancels_requested_write():
    registry, revision, operation, session, evidence = _case()
    operation.cancellation_state = CancellationState.REQUESTED
    assert operation.cancellation_policy == CancellationPolicy.AT_SAFEPOINT
    result = _decide(registry, revision, operation, session, evidence)
    assert result.decision == SafePointDecision.CANCEL


def test_t_saf_02_t_inv_i3_n_noncancellable_request_does_not_force_cancel():
    registry, revision, operation, session, evidence = _case()
    raw = next(item for item in __import__(
        "interlock.testing.fixtures", fromlist=["load_tool_manifests"]
    ).load_tool_manifests() if item["tool_name"] == "appointment.book")
    raw = dict(raw, cancellation_policy="NONCANCELLABLE", safe_points=[])
    registry.register(raw)
    operation.cancellation_policy = CancellationPolicy.NONCANCELLABLE
    operation.descriptor_capability_hash = registry.capability_hash(operation.tool_name)
    operation.cancellation_state = CancellationState.REQUESTED
    result = _decide(registry, revision, operation, session, evidence)
    assert result.decision == SafePointDecision.CONTINUE
