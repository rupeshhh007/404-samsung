"""T-FLT-01: declared fault catalogue and deterministic scheduled outcomes."""

import asyncio
from datetime import datetime, timezone

import pytest

from interlock.domain.enums import EventSource
from interlock.domain.models import EventEnvelope
from interlock.testing.clock import VirtualClock
from interlock.testing.faults import Fault, FaultEngine


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
