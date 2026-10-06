"""T-INT-01, T-INT-02, T-CON-02, T-INV-I1-P, T-INV-I1-N.

Exact revision dependencies determine whether a read remains eligible.
"""

import pytest

from interlock.domain.enums import (
    Authorization, IntentMaturity, OperationState, RuntimeMode, SafePointDecision,
)
from interlock.domain.models import IntentDelta, IntentNode, IntentRevision, SessionState
from interlock.execution.descriptors import ToolRegistry
from interlock.execution.operations import OperationManager
from interlock.execution.safepoint import SafePointPolicy, SafePointReason
from interlock.intelligence.intent_graph import (
    IntentGraph, IntentGraphError, assess_impact, bind_dependencies,
    dependency_fingerprint,
)
from interlock.testing.fixtures import register_tool_manifests


def _revision(revision_id, values, parent=None):
    bindings = bind_dependencies(values, values.keys())
    return IntentRevision(
        revision_id=revision_id, intent_id="intent", parent_revision_id=parent,
        values=values, maturity=IntentMaturity.COMMITTED,
        authorization=Authorization.AUTHORIZED, created_by_event_id="event",
        dependency_fingerprint=dependency_fingerprint(bindings),
    )


def test_t_int_01_t_int_02_t_inv_i1_p_t_inv_i1_n_selective_freshness():
    prior = _revision("r1", {"slot": "11", "warranty_status": "ACTIVE"})
    graph = IntentGraph(
        {"intent": IntentNode(intent_id="intent", goal_type="booking",
                              revisions=["r1"], active_revision_id="r1")},
        {"r1": prior},
    )
    proposal = graph.apply_delta(
        IntentDelta(target_intent_id="intent", set_fields={"slot": "12"},
                    confidence=0.96),
        revision_id="r2", created_by_event_id="event-2",
    )
    current = proposal.proposed_revision
    assert current.parent_revision_id == "r1"
    assert current.values == {"slot": "12", "warranty_status": "ACTIVE"}
    changed = assess_impact(prior, current, bind_dependencies(prior, ["slot"]))
    unaffected = assess_impact(
        prior, current, bind_dependencies(prior, ["warranty_status"])
    )
    assert changed.stale and not changed.eligible_for_active_result
    assert changed.affected_paths == ("slot",)
    assert not unaffected.stale and unaffected.eligible_for_active_result
    assert unaffected.affected_paths == ()


def test_t_int_01_rejects_duplicate_or_untrusted_revision():
    prior = _revision("r1", {"slot": "11"})
    graph = IntentGraph(
        {"intent": IntentNode(intent_id="intent", goal_type="booking",
                              revisions=["r1"], active_revision_id="r1")},
        {"r1": prior},
    )
    with pytest.raises(IntentGraphError):
        graph.apply_delta(IntentDelta(target_intent_id="intent",
                                      set_fields={"slot": "12"}, confidence=0.9),
                          revision_id="r1", created_by_event_id="event-2")


def test_t_int_01_partial_booking_stays_provisional_unauthorized_and_cannot_dispatch():
    prior = _revision("r1", {"center_id": "ctr-01", "requested_slot": "ten"})
    graph = IntentGraph(
        {"intent": IntentNode(intent_id="intent", goal_type="booking",
                              revisions=["r1"], active_revision_id="r1")},
        {"r1": prior},
    )
    proposal = graph.apply_delta(
        IntentDelta(target_intent_id="intent", set_fields={"requested_slot": "10"},
                    confidence=0.70),
        revision_id="partial-book-ten", created_by_event_id="partial-transcript",
    )
    revision = proposal.proposed_revision
    assert revision.maturity == IntentMaturity.PROVISIONAL
    assert revision.authorization == Authorization.NOT_REQUESTED

    registry = ToolRegistry()
    register_tool_manifests(registry)
    operation = OperationManager(registry).create_operation(
        operation_id="op-partial", session_id="s", intent_goal_id="intent",
        intent_revision=revision, bindings=proposal.bindings,
        tool_name="appointment.book",
        arguments={"center_id": "ctr-01",
                   "requested_slot": "2030-01-15T10:00:00+05:30"},
        existing_operation_ids=set(), known_idempotency_digests={},
    )
    operation.state = OperationState.READY
    state = SessionState(
        session_id="s", last_sequence=3, mode=RuntimeMode.TEST,
        active_intent_id="intent",
        intents={"intent": IntentNode(intent_id="intent", goal_type="booking",
                                       revisions=[revision.revision_id],
                                       active_revision_id=revision.revision_id)},
        revisions={revision.revision_id: revision},
        operations={operation.operation_id: operation},
    )
    evidence = {binding.path: list(binding.evidence_ids)
                for binding in proposal.bindings}
    decision = SafePointPolicy.decide(
        operation=operation, current_revision=revision, session_state=state,
        registry=registry, evidence_ids_by_path=evidence,
    )
    assert decision.decision == SafePointDecision.HOLD
    assert decision.reason == SafePointReason.INTENT_NOT_COMMITTED
    assert decision.follow_up_event is None
