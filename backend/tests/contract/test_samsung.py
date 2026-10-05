"""T-ADP-01: provisional Samsung-shaped wire is normalized at the adapter."""

import asyncio
from dataclasses import replace

import pytest

from interlock.adapters.samsung import SamsungShapedToolAdapter
from interlock.domain.enums import ToolOutcome
from interlock.execution.tools import ToolInvocation, ToolTransportError


def _invocation():
    return ToolInvocation(
        operation_id="op", dispatch_requested_event_id="dispatch",
        tool_name="appointment.book", descriptor_capability_hash="sha256:hash",
        arguments={"center_id": "ctr-01",
                   "requested_slot": "2030-01-15T11:00:00+05:30",
                   "idempotency_key": "key"},
        logical_action_id="action", idempotency_key="key",
        timeout_ms=5000, deadline_ms=None, cancellation_token="cancel",
        speculative=False, attempt=1,
    )


def test_t_adp_01_wire_request_and_unknown_result_are_canonical():
    class FakeWire:
        requests = []

        async def invoke(self, request):
            self.requests.append(request)
            return {"schemaVersion": 1, "requestId": "provider-1",
                    "operationId": "op", "idempotencyKey": "key",
                    "state": "OUTCOME_UNKNOWN"}

        async def cancel(self, request):
            raise AssertionError("not called")

    wire = FakeWire()
    result = asyncio.run(SamsungShapedToolAdapter(wire).invoke(_invocation()))
    assert wire.requests[0]["tool"] == "BOOK_APPOINTMENT"
    assert wire.requests[0]["payload"]["requestedStart"] == "2030-01-15T11:00:00+05:30"
    assert result.observation.outcome == ToolOutcome.UNKNOWN
    assert result.observation.result["status"] == "OUTCOME_UNKNOWN"


def test_t_adp_01_identity_mismatch_rejected_before_wire_call():
    class FakeWire:
        calls = 0

        async def invoke(self, request):
            self.calls += 1
            return {}

        async def cancel(self, request):
            return {}

    wire = FakeWire()
    bad = _invocation()
    bad = replace(bad, arguments={
        **bad.arguments, "idempotency_key": "other"})
    with pytest.raises(ToolTransportError):
        asyncio.run(SamsungShapedToolAdapter(wire).invoke(bad))
    assert wire.calls == 0
