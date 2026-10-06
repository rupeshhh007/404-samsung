"""T-ADP-01: provisional Samsung-shaped wire is normalized at the adapter."""

import asyncio
from dataclasses import replace

import pytest

from interlock.adapters.samsung import SamsungShapedToolAdapter
from interlock.domain.enums import ToolOutcome
from interlock.execution.tools import (
    ProviderCancellationRequest, ProviderCancellationStatus,
    ToolInvocation, ToolTransportError,
)
from interlock.providers.fake_tools import create_fake_tool_transport
from interlock.testing.fixtures import load_demo_fixture


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


def test_t_adp_01_all_simulated_tool_messages_round_trip_canonical_results():
    adapter, provider = create_fake_tool_transport()

    def invoke(tool, arguments, index):
        key = f"key-{index}"
        return asyncio.run(adapter.invoke(ToolInvocation(
            operation_id=f"op-{index}", dispatch_requested_event_id=f"dispatch-{index}",
            tool_name=tool, descriptor_capability_hash="sha256:hash",
            arguments={**arguments, "idempotency_key": key},
            logical_action_id=f"action-{index}", idempotency_key=key,
            timeout_ms=5000, deadline_ms=None, cancellation_token=f"cancel-{index}",
            speculative=False, attempt=1,
        )))

    results = [
        invoke("device.lookup_error", {"device_id": "device-demo-01", "error_code": "E101"}, 1),
        invoke("service.find_centers", {"device_id": "device-demo-01", "error_code": "E101"}, 2),
        invoke("appointment.availability", {"center_id": "ctr-01"}, 3),
        invoke("appointment.book", {"center_id": "ctr-01",
                                    "requested_slot": "2030-01-15T11:00:00+05:30"}, 4),
        invoke("appointment.get", {"provider_booking_id": "apt-11", "center_id": "ctr-01"}, 5),
        invoke("appointment.cancel", {"provider_booking_id": "apt-11", "center_id": "ctr-01"}, 6),
    ]
    assert [item.observation.result["status"] for item in results] == [
        "ERROR_LOOKUP_SUCCEEDED", "SERVICE_CENTERS_FOUND", "AVAILABILITY_FOUND",
        "BOOKING_CONFIRMED", "BOOKING_CONFIRMED", "CANCELLATION_CONFIRMED",
    ]
    assert results[3].observation.provider_effect_id == "apt-11"
    assert results[4].observation.provider_effect_id == "apt-11"
    assert results[5].observation.provider_effect_id == "apt-11"
    assert provider.bookings["apt-11"]["cancelled_at"] is not None
    fixture = load_demo_fixture()
    assert "SIMULATED" in fixture.label
    assert all("SIMULATED" in diagnostic.title and "SIMULATED" in diagnostic.summary
               for diagnostic in fixture.diagnostics)


def test_t_adp_01_provider_cancel_boundary_maps_acceptance_without_claiming_effect_absence():
    adapter, _ = create_fake_tool_transport(
        outcome_scripts={"appointment.book": ["ACKNOWLEDGED"]}
    )
    invocation = _invocation()
    accepted = asyncio.run(adapter.invoke(invocation))
    cancellation = asyncio.run(adapter.cancel(ProviderCancellationRequest(
        operation_id="op", provider_request_id=accepted.provider_request_id,
        reason="USER_CORRECTION",
    )))
    assert cancellation.status == ProviderCancellationStatus.CANCEL_ACCEPTED
    assert cancellation.reason == "CANCEL_RECORDED"
