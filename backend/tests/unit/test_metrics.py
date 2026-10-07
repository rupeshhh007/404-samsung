"""T-MET-01: metrics derive only from complete accepted event prefixes."""

from datetime import datetime, timezone

import pytest

from interlock.domain.enums import EventSource
from interlock.domain.models import EventEnvelope
from interlock.metrics import derive_metrics


def _start(sequence: int = 1) -> EventEnvelope:
    return EventEnvelope(
        event_id="start", session_id="s", sequence=sequence,
        event_type="SessionStarted", source=EventSource.SYSTEM,
        occurred_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        logical_time=0, payload={"mode": "TEST"},
    )


def test_t_met_01_count_and_no_invented_denominators():
    result = derive_metrics("s", [_start()])
    assert result.through_sequence == 1
    assert result.counters["accepted_events"] == 1
    assert result.counters["events.SessionStarted"] == 1
    assert result.durations_ms == {}
    assert result.gauges == {}


def test_t_met_01_reject_truncated_or_gapped_trace():
    with pytest.raises(ValueError, match="complete ordered"):
        derive_metrics("s", [_start(sequence=2)])


def test_t_met_01_known_event_trace_derives_exact_durations_and_empty_denominators():
    from interlock.domain.enums import (
        ActionType, CancellationPolicy, CancellationState, DivergenceState,
        EffectState, OperationState,
    )
    from interlock.domain.models import DivergenceCase, OperationRecord

    now = datetime(2026, 1, 1, tzinfo=timezone.utc)

    def env(seq, ev_type, payload, logical_time=0):
        return EventEnvelope(
            event_id=f"e-{seq}", session_id="s", sequence=seq,
            event_type=ev_type, source=EventSource.SYSTEM,
            occurred_at=now, logical_time=logical_time, payload=payload,
        )

    # 1. Unmeasured trace: absence means unmeasured, no invented denominators
    empty_trace = [_start()]
    empty_metrics = derive_metrics("s", empty_trace)
    assert empty_metrics.durations_ms == {}
    assert empty_metrics.gauges == {}
    assert "safe_point_latency_p50" not in empty_metrics.durations_ms
    assert "safe_point_latency_p95" not in empty_metrics.durations_ms
    assert "reconciliation_success_rate" not in empty_metrics.gauges

    # 2. Known event trace with exact known logical timestamp deltas
    events = [_start()]
    seq = 1

    # Delays: (140-100=40), (260-200=60), (380-300=80), (500-400=100)
    deltas = [(100, 140), (200, 260), (300, 380), (400, 500)]
    for i, (t_req, t_safe) in enumerate(deltas, start=1):
        op = OperationRecord(
            operation_id=f"op-{i}", tool_name="appointment.book",
            intent_revision_id="rev-1", fingerprint=f"fp-{i}",
            action_type=ActionType.REVERSIBLE,
            cancellation_policy=CancellationPolicy.AT_SAFEPOINT,
            state=OperationState.CREATED, cancellation_state=CancellationState.NONE,
            effect_state=EffectState.NOT_STARTED, speculative=False,
            logical_action_id=f"action-{i}", idempotency_key=f"key-{i}",
        )
        seq += 1
        events.append(env(seq, "OperationCreated", {"operation": op.model_dump(mode="json")}, t_req - 10))
        seq += 1
        events.append(env(seq, "CancellationRequested", {"operation_id": f"op-{i}", "reason": "test"}, t_req))
        seq += 1
        events.append(env(seq, "SafePointReached", {"operation_id": f"op-{i}", "name": "BEFORE_PROVIDER_DISPATCH"}, t_safe))

    # Add terminal divergence cases: one RESOLVED, one ESCALATED
    case1 = DivergenceCase(
        divergence_id="div-1", desired_fingerprint="dfp-1", observed_effect_ids=["eff-1"],
        kind="BOOKING_SLOT_MISMATCH", state=DivergenceState.RECONCILING, detected_by_event_id="e-div-1",
    )
    seq += 1
    events.append(env(seq, "DivergenceDetected", {"case": case1.model_dump(mode="json")}, 600))
    seq += 1
    events.append(env(seq, "DivergenceResolved", {"divergence_id": "div-1", "evidence_ids": []}, 650))

    case2 = DivergenceCase(
        divergence_id="div-2", desired_fingerprint="dfp-2", observed_effect_ids=["eff-2"],
        kind="BOOKING_SLOT_MISMATCH", state=DivergenceState.ESCALATED, detected_by_event_id="e-div-2",
    )
    seq += 1
    events.append(env(seq, "DivergenceDetected", {"case": case2.model_dump(mode="json")}, 700))

    # Calculate metrics over the full known trace
    metrics = derive_metrics("s", events)

    # Assert exact derived durations from nearest-rank percentiles
    assert metrics.counters["safe_point_latency_samples"] == 4
    assert metrics.durations_ms["safe_point_latency_p50"] == 60.0
    assert metrics.durations_ms["safe_point_latency_p95"] == 100.0

    # Assert exact reconciliation success rate gauge
    assert metrics.counters["terminal_reconciliation_cases"] == 2
    assert metrics.counters["resolved_reconciliation_cases"] == 1
    assert metrics.gauges["reconciliation_success_rate"] == 0.5
