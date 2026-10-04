"""Deterministic offline appointment provider behind the generic adapter path.

This is test/demo infrastructure, not an official Samsung integration.  Each
instance owns all of its state; no wall clock, network, credentials, or module
globals participate in an outcome.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from hashlib import sha256
import json
from typing import Any

from interlock.adapters.protocol import WireClientFailure, strict_object
from interlock.adapters.samsung import SamsungShapedToolAdapter
from interlock.execution.idempotency import canonical_json, strict_json_copy
from interlock.testing.fixtures import FakeProviderFixture, ProviderOutcome, load_demo_fixture


_REQUEST_FIELDS = frozenset({
    "schemaVersion", "kind", "tool", "operationId", "dispatchEventId",
    "idempotencyKey", "attempt", "cancellationToken", "payload",
})
_CANCEL_FIELDS = frozenset({
    "schemaVersion", "kind", "operationId", "targetRequestId", "reason",
})
_WIRE_TO_TOOL = {
    "BOOK_APPOINTMENT": "appointment.book",
    "GET_APPOINTMENT": "appointment.get",
    "CANCEL_APPOINTMENT": "appointment.cancel",
}


@dataclass(slots=True)
class _RequestRecord:
    tool_name: str
    operation_id: str
    idempotency_key: str
    request_digest: str
    provider_request_id: str
    outcomes: tuple[ProviderOutcome, ...]
    next_outcome: int = 0
    terminal: bool = False
    cancel_requested: bool = False
    last_response: dict[str, Any] | None = None


class FakeAppointmentProvider:
    """Samsung-shaped wire client with isolated deterministic state."""

    def __init__(
        self,
        fixture: FakeProviderFixture | None = None,
        *,
        outcome_scripts: Mapping[str, Sequence[ProviderOutcome]] | None = None,
    ) -> None:
        seed = (fixture or load_demo_fixture()).model_copy(deep=True)
        scripts = {
            tool: tuple(outcomes)
            for tool, outcomes in seed.default_outcomes.items()
        }
        for tool, outcomes in (outcome_scripts or {}).items():
            if tool not in _WIRE_TO_TOOL.values():
                raise ValueError("outcome script targets an unsupported tool")
            sequence = tuple(outcomes)
            if not sequence:
                raise ValueError("outcome script must be nonempty")
            if any(outcome not in {"ACKNOWLEDGED", "SUCCEEDED", "FAILED", "UNKNOWN"}
                   for outcome in sequence):
                raise ValueError("outcome script contains an unsupported outcome")
            if "ACKNOWLEDGED" in sequence and tool != "appointment.book":
                raise ValueError("only appointment.book supports acknowledgement")
            scripts[tool] = sequence
        self._fixture_id = seed.fixture_id
        self._centers = {center.center_id for center in seed.centers}
        self._availability = {
            center_id: tuple(slots) for center_id, slots in seed.availability.items()
        }
        self._cancelled_at = seed.cancelled_at
        self._scripts = scripts
        self._bookings = {
            booking.booking_id: booking.model_dump(mode="python")
            for booking in seed.initial_bookings
        }
        self._requests: dict[str, _RequestRecord] = {}
        self._request_by_provider_id: dict[str, _RequestRecord] = {}
        self._physical_action_count = 0
        self._lock = asyncio.Lock()

    @property
    def bookings(self) -> dict[str, dict[str, Any]]:
        return deepcopy(self._bookings)

    @property
    def physical_action_count(self) -> int:
        return self._physical_action_count

    @property
    def provider_request_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._request_by_provider_id))

    async def invoke(self, request: Mapping[str, Any]) -> Mapping[str, Any]:
        wire = strict_object(
            request,
            field="fake_provider_request",
            allowed=_REQUEST_FIELDS,
            required=_REQUEST_FIELDS,
        )
        _require_exact(wire, "schemaVersion", 1)
        _require_exact(wire, "kind", "TOOL_CALL")
        wire_tool = _text(wire["tool"], "tool")
        try:
            tool_name = _WIRE_TO_TOOL[wire_tool]
        except KeyError as exc:
            raise WireClientFailure("UNSUPPORTED_TOOL", after_dispatch=False) from exc
        operation_id = _text(wire["operationId"], "operationId")
        idempotency_key = _text(wire["idempotencyKey"], "idempotencyKey")
        _text(wire["dispatchEventId"], "dispatchEventId")
        _text(wire["cancellationToken"], "cancellationToken")
        if type(wire["attempt"]) is not int or wire["attempt"] < 1:
            raise WireClientFailure("INVALID_REQUEST", after_dispatch=False)
        payload = _payload(tool_name, wire["payload"])
        # The fixture manifests declare provider-scoped idempotency, so the
        # key itself (not the tool name) is the provider's collision domain.
        identity = idempotency_key
        digest = _digest({"tool": tool_name, "payload": payload})

        async with self._lock:
            record = self._requests.get(identity)
            if record is None:
                provider_id = _stable_id("request", self._fixture_id, identity)
                record = _RequestRecord(
                    tool_name=tool_name,
                    operation_id=operation_id,
                    idempotency_key=idempotency_key,
                    request_digest=digest,
                    provider_request_id=provider_id,
                    outcomes=self._scripts[tool_name],
                )
                self._requests[identity] = record
                self._request_by_provider_id[provider_id] = record
            elif (
                record.request_digest != digest
                or record.operation_id != operation_id
                or record.tool_name != tool_name
            ):
                raise WireClientFailure("IDEMPOTENCY_CONFLICT", after_dispatch=False)

            if record.next_outcome >= len(record.outcomes):
                if record.last_response is None:
                    raise RuntimeError("fake provider request has no response")
                return deepcopy(record.last_response)

            outcome_index = record.next_outcome
            outcome = record.outcomes[outcome_index]
            record.next_outcome += 1
            response = self._response(record, payload, outcome, outcome_index)
            record.last_response = strict_json_copy(response, field="fake_response")
            if outcome in {"SUCCEEDED", "FAILED", "UNKNOWN"}:
                record.terminal = True
            return deepcopy(record.last_response)

    async def cancel(self, request: Mapping[str, Any]) -> Mapping[str, Any]:
        wire = strict_object(
            request,
            field="fake_cancel_request",
            allowed=_CANCEL_FIELDS,
            required={"schemaVersion", "kind", "operationId", "targetRequestId"},
        )
        _require_exact(wire, "schemaVersion", 1)
        _require_exact(wire, "kind", "CANCEL_PROVIDER_REQUEST")
        operation_id = _text(wire["operationId"], "operationId")
        provider_id = _text(wire["targetRequestId"], "targetRequestId")
        if "reason" in wire:
            _text(wire["reason"], "reason")

        async with self._lock:
            record = self._request_by_provider_id.get(provider_id)
            if record is None or record.operation_id != operation_id:
                state, reason = "REJECTED", "UNKNOWN_REQUEST"
            elif record.terminal:
                state, reason = "TOO_LATE", "TERMINAL_OBSERVED"
            elif record.cancel_requested:
                state, reason = "CANCEL_ACCEPTED", "CANCEL_ALREADY_RECORDED"
            else:
                record.cancel_requested = True
                state, reason = "CANCEL_ACCEPTED", "CANCEL_RECORDED"
            return {
                "schemaVersion": 1,
                "operationId": operation_id,
                "targetRequestId": provider_id,
                "state": state,
                "reason": reason,
            }

    def _response(
        self,
        record: _RequestRecord,
        payload: dict[str, str],
        outcome: ProviderOutcome,
        outcome_index: int,
    ) -> dict[str, Any]:
        response: dict[str, Any] = {
            "schemaVersion": 1,
            "requestId": record.provider_request_id,
            "operationId": record.operation_id,
            "idempotencyKey": record.idempotency_key,
            "callbackId": _stable_id(
                "callback", record.provider_request_id, str(outcome_index), outcome
            ),
        }
        if outcome == "ACKNOWLEDGED":
            response.update({
                "state": "REQUEST_RECEIVED",
                "booking": {
                    "serviceCenterId": payload["serviceCenterId"],
                    "requestedStart": payload["requestedStart"],
                },
            })
            return response
        if outcome == "FAILED":
            response.update({
                "state": _failure_state(record.tool_name),
                "error": {
                    "code": "SIMULATED_FAILURE",
                    "message": "Simulated deterministic provider failure",
                    "retryable": False,
                },
            })
            if "bookingId" in payload:
                response["booking"] = {"bookingId": payload["bookingId"]}
            return response
        if outcome == "UNKNOWN":
            response["state"] = "OUTCOME_UNKNOWN"
            if "bookingId" in payload:
                response["booking"] = {"bookingId": payload["bookingId"]}
            return response
        if record.tool_name == "appointment.book":
            response.update(self._book(record, payload))
        elif record.tool_name == "appointment.get":
            response.update(self._get(payload))
        else:
            response.update(self._cancel_booking(payload))
        return response

    def _book(self, record: _RequestRecord, payload: dict[str, str]) -> dict[str, Any]:
        center_id = payload["serviceCenterId"]
        requested = payload["requestedStart"]
        occupied = any(
            booking["center_id"] == center_id
            and booking["confirmed_slot"] == requested
            and booking.get("cancelled_at") is None
            for booking in self._bookings.values()
        )
        if center_id not in self._centers or requested not in self._availability[center_id] or occupied:
            return _wire_failure("BOOKING_FAILED", "SLOT_UNAVAILABLE")
        booking_id = _stable_id("booking", self._fixture_id, record.idempotency_key)
        booking = {
            "booking_id": booking_id,
            "center_id": center_id,
            "requested_slot": requested,
            "confirmed_slot": requested,
            "cancelled_at": None,
        }
        self._bookings[booking_id] = booking
        self._physical_action_count += 1
        return {"state": "BOOKING_CONFIRMED", "booking": _wire_booking(booking)}

    def _get(self, payload: dict[str, str]) -> dict[str, Any]:
        booking = self._bookings.get(payload["bookingId"])
        if (
            booking is None
            or booking["center_id"] != payload["serviceCenterId"]
            or booking.get("cancelled_at") is not None
        ):
            return _wire_failure("LOOKUP_FAILED", "BOOKING_NOT_FOUND", payload["bookingId"])
        return {"state": "BOOKING_FOUND", "booking": _wire_booking(booking)}

    def _cancel_booking(self, payload: dict[str, str]) -> dict[str, Any]:
        booking = self._bookings.get(payload["bookingId"])
        if booking is None or booking["center_id"] != payload["serviceCenterId"]:
            return _wire_failure(
                "CANCELLATION_FAILED", "BOOKING_NOT_FOUND", payload["bookingId"]
            )
        if booking.get("cancelled_at") is None:
            booking["cancelled_at"] = self._cancelled_at
            self._physical_action_count += 1
        return {"state": "CANCELLATION_CONFIRMED", "booking": _wire_booking(booking)}


def create_fake_tool_transport(
    fixture: FakeProviderFixture | None = None,
    *,
    outcome_scripts: Mapping[str, Sequence[ProviderOutcome]] | None = None,
) -> tuple[SamsungShapedToolAdapter, FakeAppointmentProvider]:
    """Compose the fake endpoint through the same generic adapter used by runtime."""

    provider = FakeAppointmentProvider(fixture, outcome_scripts=outcome_scripts)
    return SamsungShapedToolAdapter(provider), provider


def _payload(tool_name: str, value: Any) -> dict[str, str]:
    if tool_name == "appointment.book":
        fields = {"serviceCenterId", "requestedStart"}
    else:
        fields = {"bookingId", "serviceCenterId"}
    payload = strict_object(value, field="payload", allowed=fields, required=fields)
    return {field: _text(payload[field], f"payload.{field}") for field in fields}


def _wire_booking(booking: Mapping[str, Any]) -> dict[str, Any]:
    result = {
        "bookingId": booking["booking_id"],
        "serviceCenterId": booking["center_id"],
        "requestedStart": booking["requested_slot"],
        "confirmedStart": booking["confirmed_slot"],
    }
    if booking.get("cancelled_at") is not None:
        result["cancelledAt"] = booking["cancelled_at"]
    return result


def _wire_failure(state: str, code: str, booking_id: str | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "state": state,
        "error": {"code": code, "message": "Simulated failure", "retryable": False},
    }
    if booking_id is not None:
        result["booking"] = {"bookingId": booking_id}
    return result


def _failure_state(tool_name: str) -> str:
    return {
        "appointment.book": "BOOKING_FAILED",
        "appointment.get": "LOOKUP_FAILED",
        "appointment.cancel": "CANCELLATION_FAILED",
    }[tool_name]


def _require_exact(mapping: Mapping[str, Any], field: str, expected: Any) -> None:
    if type(mapping.get(field)) is not type(expected) or mapping.get(field) != expected:
        raise WireClientFailure("INVALID_REQUEST", after_dispatch=False)


def _text(value: Any, field: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > 512
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise WireClientFailure("INVALID_REQUEST", after_dispatch=False)
    return value


def _digest(value: Any) -> str:
    return sha256(canonical_json(value).encode()).hexdigest()


def _stable_id(kind: str, *parts: str) -> str:
    encoded = json.dumps((kind, *parts), separators=(",", ":"), ensure_ascii=False)
    return f"fake-{kind}-{sha256(encoded.encode()).hexdigest()[:32]}"


__all__ = ["FakeAppointmentProvider", "create_fake_tool_transport"]
