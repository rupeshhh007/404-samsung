"""T-FLT-01: declared fault catalogue and deterministic scheduled outcomes."""

import asyncio
from datetime import datetime, timezone

import pytest

from interlock.domain.enums import EventSource
from interlock.domain.models import EventEnvelope
from interlock.testing.clock import VirtualClock
from interlock.testing.faults import Fault, FaultEngine


def _activated_engine(raw):
    clock = VirtualClock()
    engine = FaultEngine(clock, [raw])
    accepted = EventEnvelope(
        event_id=f"event-{raw['id']}", session_id="s", sequence=1,
        event_type="FaultActivated", source=EventSource.SCENARIO,
        occurred_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        logical_time=0,
        payload={"fault_id": raw["id"], "operation_match": raw["match"]},
    )
    engine.activate(accepted)
    return clock, engine


@pytest.mark.parametrize("kind,params", [
    ("LATENCY", {"delay_ms": 5}),
    ("FAILURE", {"code": "SIMULATED_FAILURE", "before_dispatch": True}),
    ("TIMEOUT", {"after_dispatch": True}),
    ("IGNORE_CANCELLATION", {}),
    ("LATE_RESULT", {"delay_ms": 5}),
    ("COMMIT_BEFORE_CANCEL", {"commit_at_ms": 5, "cancel_at_ms": 6}),
    ("DUPLICATE_CALLBACK", {"count": 2, "identical": True}),
    ("DUPLICATE_RETRY", {"provider_idempotency_supported": True, "same_key": True}),
    ("UNKNOWN_OUTCOME", {"after_dispatch": True}),
    ("COMPENSATION_FAILURE", {"code": "SIMULATED_FAILURE"}),
])
def test_t_flt_01_all_documented_faults_parse(kind, params):
    fault = Fault.parse({"id": kind.lower(), "type": kind,
                         "match": {"operation_id": "op"}, **params})
    assert fault.fault_type == kind
    assert fault.match_dict() == {"operation_id": "op"}


def test_t_flt_01_activated_latency_delivers_at_virtual_time():
    async def run():
        clock = VirtualClock()
        engine = FaultEngine(clock, [{
            "id": "delay", "type": "LATENCY",
            "match": {"operation_id": "op"}, "delay_ms": 5,
        }])
        assert engine.result_plan({"operation_id": "op"}, base_at_ms=10)["at_ms"] == 10
        accepted = EventEnvelope(
            event_id="fault-event", session_id="s", sequence=1,
            event_type="FaultActivated", source=EventSource.SCENARIO,
            occurred_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            logical_time=0, payload={"fault_id": "delay",
                                      "operation_match": {"operation_id": "op"}},
        )
        engine.activate(accepted)
        delivered = []
        engine.schedule_result({"operation_id": "op"}, base_at_ms=10,
                               deliver=lambda plan: delivered.append((clock.now(), plan)))
        await clock.advance_to(14)
        assert delivered == []
        await clock.advance_to(15)
        assert delivered[0][0] == 15
        assert delivered[0][1]["disposition"] == "DELIVER"
    asyncio.run(run())


@pytest.mark.parametrize("raw,expected", [
    ({"id": "failure", "type": "FAILURE", "match": {"operation_id": "op"},
      "code": "SIMULATED_FAILURE", "before_dispatch": True}, "FAILURE"),
    ({"id": "timeout", "type": "TIMEOUT", "match": {"operation_id": "op"},
      "after_dispatch": True}, "TIMEOUT"),
    ({"id": "unknown", "type": "UNKNOWN_OUTCOME", "match": {"operation_id": "op"},
      "after_dispatch": True}, "OUTCOME_UNKNOWN"),
    ({"id": "compensation", "type": "COMPENSATION_FAILURE",
      "match": {"operation_id": "op"}, "code": "SIMULATED_FAILURE"}, "FAILURE"),
])
def test_t_flt_01_terminal_faults_have_exact_safe_runtime_plan(raw, expected):
    _, engine = _activated_engine(raw)
    plan = engine.result_plan({"operation_id": "op"}, base_at_ms=10)
    assert plan["disposition"] == expected
    assert plan["retry_allowed"] is False


def test_t_flt_01_cancellation_race_and_late_result_preserve_exact_order():
    async def run():
        clock, engine = _activated_engine({
            "id": "race", "type": "COMMIT_BEFORE_CANCEL",
            "match": {"operation_id": "op"}, "commit_at_ms": 5, "cancel_at_ms": 6,
        })
        observed = []
        engine.schedule_commit_before_cancel(
            {"operation_id": "op"},
            commit=lambda: observed.append((clock.now(), "commit")),
            cancel=lambda: observed.append((clock.now(), "cancel")),
        )
        await clock.advance_to(6)
        assert observed == [(5, "commit"), (6, "cancel")]

        late_clock, late = _activated_engine({
            "id": "late", "type": "LATE_RESULT",
            "match": {"operation_id": "op"}, "delay_ms": 7,
        })
        assert late.result_plan({"operation_id": "op"}, base_at_ms=10) == {
            "at_ms": 17, "disposition": "DELIVER", "parameters": {},
            "retry_allowed": True,
        }
        assert late_clock.now() == 0
    asyncio.run(run())


def test_t_flt_01_duplicate_and_ignore_faults_are_bounded_and_fail_closed():
    async def run():
        clock, callbacks = _activated_engine({
            "id": "duplicates", "type": "DUPLICATE_CALLBACK",
            "match": {"operation_id": "op"}, "count": 2, "identical": True,
        })
        delivered = []
        handles = callbacks.schedule_callbacks(
            {"operation_id": "op"}, at_ms=5,
            callback={"callback_id": "callback", "value": 1},
            ingress=lambda item: delivered.append(item),
        )
        assert len(handles) == 2
        await clock.advance_to(5)
        assert delivered == [
            {"callback_id": "callback", "value": 1},
            {"callback_id": "callback", "value": 1},
        ]

        _, retry = _activated_engine({
            "id": "retry", "type": "DUPLICATE_RETRY",
            "match": {"operation_id": "op"},
            "provider_idempotency_supported": True, "same_key": True,
        })
        assert retry.retry_decision({"operation_id": "op"}, key="stable") == {
            "repeat": True, "idempotency_key": "stable",
            "provider_idempotency_supported": True,
        }

        _, ignored = _activated_engine({
            "id": "ignore", "type": "IGNORE_CANCELLATION",
            "match": {"operation_id": "op"},
        })
        assert ignored.cancellation_decision({"operation_id": "op"}) == "IGNORE"
        assert ignored.cancellation_decision({"operation_id": "other"}) == "DELEGATE"
    asyncio.run(run())
