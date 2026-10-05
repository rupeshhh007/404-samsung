"""T-INT-01, T-INT-02, T-CON-02, T-INV-I1-P, T-INV-I1-N.

Exact revision dependencies determine whether a read remains eligible.
"""

import pytest

from interlock.domain.enums import Authorization, IntentMaturity
from interlock.domain.models import IntentDelta, IntentNode, IntentRevision
from interlock.intelligence.intent_graph import (
    IntentGraph, IntentGraphError, assess_impact, bind_dependencies,
    dependency_fingerprint,
)


def _revision(revision_id, values, parent=None):
    bindings = bind_dependencies(values, values.keys())
    return IntentRevision(
        revision_id=revision_id, intent_id="intent", parent_revision_id=parent,
        values=values, maturity=IntentMaturity.COMMITTED,
        authorization=Authorization.AUTHORIZED, created_by_event_id="event",
        dependency_fingerprint=dependency_fingerprint(bindings),
    )


def test_t_int_01_t_int_02_t_inv_i1_p_t_inv_i1_n_selective_freshness():
    prior = _revision("r1", {"slot": "11", "device": "phone"})
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
    assert current.values == {"slot": "12", "device": "phone"}
    changed = assess_impact(prior, current, bind_dependencies(prior, ["slot"]))
    unaffected = assess_impact(prior, current, bind_dependencies(prior, ["device"]))
    assert changed.stale and not changed.eligible_for_active_result
    assert changed.affected_paths == ("slot",)
    assert not unaffected.stale and unaffected.eligible_for_active_result


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
