"""Provisional local Samsung-shaped mapping onto canonical tool contracts.

No official Samsung API or behavior is represented here.  Camel-case wire
fields are confined to this module and are normalized to the existing generic
``ToolProviderTransport`` types before they can reach runtime code.
"""

from __future__ import annotations

from collections.abc import Mapping
from hashlib import sha256
import json
from typing import Any

from interlock.adapters.protocol import (
    AdapterErrorCode,
    AdapterProtocolError,
    ProviderWireClient,
    WireClientFailure,
    require_bool,
    require_rfc3339,
    require_safe_code,
    require_safe_text,
    require_version,
    strict_object,
)
from interlock.domain.enums import ToolOutcome
from interlock.execution.idempotency import strict_json_copy
from interlock.execution.tools import (
    ProviderCancellationRequest,
    ProviderCancellationResult,
    ProviderCancellationStatus,
    ProviderObservation,
    ProviderResponse,
    ToolInvocation,
    ToolTransportError,
)


_TOOLS = frozenset({"appointment.book", "appointment.get", "appointment.cancel"})
_WIRE_TOOL = {
    "appointment.book": "BOOK_APPOINTMENT",
    "appointment.get": "GET_APPOINTMENT",
    "appointment.cancel": "CANCEL_APPOINTMENT",
}
_REQUEST_FIELDS = frozenset({
    "schemaVersion", "kind", "tool", "operationId", "dispatchEventId",
    "idempotencyKey", "attempt", "cancellationToken", "payload",
})
_RESPONSE_FIELDS = frozenset({
    "schemaVersion", "requestId", "operationId", "idempotencyKey", "state",
    "booking", "error", "retryCategory", "callbackId",
})
_BOOKING_FIELDS = frozenset({
    "bookingId", "serviceCenterId", "requestedStart", "confirmedStart",
    "cancelledAt",
})
_ERROR_FIELDS = frozenset({"code", "message", "retryable"})
_CANCEL_FIELDS = frozenset({
    "schemaVersion", "kind", "operationId", "targetRequestId", "reason",
})
_CANCEL_RESPONSE_FIELDS = frozenset({
    "schemaVersion", "operationId", "targetRequestId", "state", "reason",
})


class SamsungShapedToolAdapter:
    """Validate and normalize one provisional Samsung-shaped endpoint."""

    def __init__(self, client: ProviderWireClient) -> None:
        if not callable(getattr(client, "invoke", None)) or not callable(
            getattr(client, "cancel", None)
        ):
            raise TypeError("client must implement invoke and cancel")
        self._client = client

    async def invoke(self, invocation: ToolInvocation) -> ProviderResponse:
        if not isinstance(invocation, ToolInvocation):
            raise ToolTransportError("INVALID_REQUEST", after_dispatch=False)
        try:
            request = self._request(invocation)
        except AdapterProtocolError as exc:
            raise ToolTransportError(exc.code.value, after_dispatch=False) from exc
        try:
            raw = await self._client.invoke(strict_json_copy(request, field="samsung_request"))
        except WireClientFailure as exc:
            raise ToolTransportError(
                exc.category,
                after_dispatch=exc.after_dispatch,
                provider_request_id=exc.provider_request_id,
            ) from exc
        except Exception as exc:
            raise ToolTransportError("TRANSPORT_FAILURE", after_dispatch=True) from exc
        provider_id: str | None = None
        try:
            if isinstance(raw, Mapping):
                candidate = raw.get("requestId")
                if isinstance(candidate, str) and candidate.strip() == candidate and candidate:
                    provider_id = candidate
            return self._response(invocation, raw)
        except AdapterProtocolError as exc:
            raise ToolTransportError(
                exc.code.value,
                after_dispatch=True,
                provider_request_id=provider_id,
            ) from exc

    async def cancel(
        self, request: ProviderCancellationRequest
    ) -> ProviderCancellationResult:
        if not isinstance(request, ProviderCancellationRequest):
            raise ToolTransportError("INVALID_REQUEST", after_dispatch=False)
        wire: dict[str, Any] = {
            "schemaVersion": 1,
            "kind": "CANCEL_PROVIDER_REQUEST",
            "operationId": request.operation_id,
            "targetRequestId": request.provider_request_id,
        }
        if request.reason is not None:
            wire["reason"] = request.reason
        try:
            raw = await self._client.cancel(strict_json_copy(wire, field="samsung_cancel_request"))
        except WireClientFailure as exc:
            raise ToolTransportError(
                exc.category,
                after_dispatch=exc.after_dispatch,
                provider_request_id=exc.provider_request_id,
            ) from exc
        except Exception as exc:
            raise ToolTransportError("TRANSPORT_FAILURE", after_dispatch=True) from exc
        try:
            return self._cancellation_response(request, raw)
        except AdapterProtocolError as exc:
            raise ToolTransportError(
                exc.code.value,
                after_dispatch=True,
                provider_request_id=request.provider_request_id,
            ) from exc

    @staticmethod
    def _request(invocation: ToolInvocation) -> dict[str, Any]:
        if invocation.tool_name not in _TOOLS:
            raise AdapterProtocolError(
                AdapterErrorCode.UNSUPPORTED_TOOL, "tool is not supported by local adapter"
            )
        args = strict_object(
            invocation.arguments,
            field="arguments",
            allowed=_argument_fields(invocation.tool_name),
            required=_argument_fields(invocation.tool_name),
        )
        if args["idempotency_key"] != invocation.idempotency_key:
            raise AdapterProtocolError(
                AdapterErrorCode.IDENTITY_MISMATCH, "idempotency identity differs"
            )
        payload: dict[str, Any] = {}
        if invocation.tool_name == "appointment.book":
            payload = {
                "serviceCenterId": require_safe_text(args["center_id"], "center_id"),
                "requestedStart": require_rfc3339(args["requested_slot"], "requested_slot"),
            }
        elif invocation.tool_name == "appointment.get":
            payload = {
                "bookingId": require_safe_text(
                    args["provider_booking_id"], "provider_booking_id"
                )
            }
            if "center_id" in args:
                payload["serviceCenterId"] = require_safe_text(args["center_id"], "center_id")
        else:
            payload = {
                "bookingId": require_safe_text(
                    args["provider_booking_id"], "provider_booking_id"
                ),
                "serviceCenterId": require_safe_text(args["center_id"], "center_id"),
            }
        request = {
            "schemaVersion": 1,
            "kind": "TOOL_CALL",
            "tool": _WIRE_TOOL[invocation.tool_name],
            "operationId": invocation.operation_id,
            "dispatchEventId": invocation.dispatch_requested_event_id,
            "idempotencyKey": invocation.idempotency_key,
            "attempt": invocation.attempt,
            "cancellationToken": invocation.cancellation_token,
            "payload": payload,
        }
        return strict_object(
            request,
            field="request",
            allowed=_REQUEST_FIELDS,
            required=_REQUEST_FIELDS,
        )

    @staticmethod
    def _response(invocation: ToolInvocation, raw: Any) -> ProviderResponse:
        response = strict_object(
            raw,
            field="response",
            allowed=_RESPONSE_FIELDS,
            required={
                "schemaVersion", "requestId", "operationId", "idempotencyKey", "state"
            },
        )
        require_version(response["schemaVersion"])
        provider_id = require_safe_text(response["requestId"], "requestId")
        if response["operationId"] != invocation.operation_id:
            raise AdapterProtocolError(
                AdapterErrorCode.IDENTITY_MISMATCH, "operation identity differs"
            )
        if response["idempotencyKey"] != invocation.idempotency_key:
            raise AdapterProtocolError(
                AdapterErrorCode.IDENTITY_MISMATCH, "idempotency identity differs"
            )
        state = require_safe_code(response["state"], "state")
        result, outcome, effect_id = _normalize_result(invocation, response, state, provider_id)
        callback_id = response.get("callbackId")
        if callback_id is None:
            callback_id = _digest({
                "provider_request_id": provider_id,
                "outcome": outcome.value,
                "result": result,
                "provider_effect_id": effect_id,
            })
        else:
            callback_id = require_safe_text(callback_id, "callbackId")
        retry_category = response.get("retryCategory")
        if retry_category is not None:
            retry_category = require_safe_code(retry_category, "retryCategory")
        observation = ProviderObservation(
            provider_request_id=provider_id,
            callback_dedupe_key=callback_id,
            outcome=outcome,
            result=strict_json_copy(result, field="normalized_result"),
            provider_effect_id=effect_id,
            retry_category=retry_category,
        )
        return ProviderResponse(provider_request_id=provider_id, observation=observation)

    @staticmethod
    def _cancellation_response(
        request: ProviderCancellationRequest, raw: Any
    ) -> ProviderCancellationResult:
        response = strict_object(
            raw,
            field="cancellation_response",
            allowed=_CANCEL_RESPONSE_FIELDS,
            required={"schemaVersion", "operationId", "targetRequestId", "state", "reason"},
        )
        require_version(response["schemaVersion"])
        if (
            response["operationId"] != request.operation_id
            or response["targetRequestId"] != request.provider_request_id
        ):
            raise AdapterProtocolError(
                AdapterErrorCode.IDENTITY_MISMATCH, "cancellation identity differs"
            )
        state = require_safe_code(response["state"], "state")
        try:
            status = ProviderCancellationStatus(state)
        except ValueError as exc:
            raise AdapterProtocolError(
                AdapterErrorCode.INVALID_RESPONSE, "unknown cancellation state"
            ) from exc
        reason = require_safe_code(response["reason"], "reason")
        return ProviderCancellationResult(status=status, reason=reason)


def _argument_fields(tool_name: str) -> frozenset[str]:
    if tool_name == "appointment.book":
        return frozenset({"center_id", "requested_slot", "idempotency_key"})
    if tool_name == "appointment.get":
        return frozenset({"provider_booking_id", "center_id", "idempotency_key"})
    return frozenset({"provider_booking_id", "center_id", "idempotency_key"})


def _normalize_result(
    invocation: ToolInvocation,
    response: Mapping[str, Any],
    state: str,
    provider_id: str,
) -> tuple[dict[str, Any], ToolOutcome, str | None]:
    if state == "REQUEST_RECEIVED":
        if invocation.tool_name != "appointment.book":
            raise AdapterProtocolError(
                AdapterErrorCode.INVALID_RESPONSE, "acknowledgement is unsupported for this tool"
            )
        _forbid(response, "error", "retryCategory")
        booking = _booking(response, required={"serviceCenterId", "requestedStart"})
        result = {
            "phase": "ACKNOWLEDGEMENT",
            "status": "REQUEST_RECEIVED",
            "provider_request_id": provider_id,
            "center_id": booking["serviceCenterId"],
            "requested_slot": booking["requestedStart"],
        }
        _match_request(invocation, result)
        return result, ToolOutcome.ACKNOWLEDGED, None

    if state in {"BOOKING_CONFIRMED", "BOOKING_FOUND"}:
        if invocation.tool_name not in {"appointment.book", "appointment.get"}:
            raise AdapterProtocolError(
                AdapterErrorCode.INVALID_RESPONSE, "booking result is for another tool"
            )
        _forbid(response, "error", "retryCategory")
        booking = _booking(response, required={
            "bookingId", "serviceCenterId", "requestedStart", "confirmedStart"
        })
        result = {
            "phase": "FINAL",
            "status": "BOOKING_CONFIRMED",
            "provider_request_id": provider_id,
            "provider_booking_id": booking["bookingId"],
            "center_id": booking["serviceCenterId"],
            "requested_slot": booking["requestedStart"],
            "confirmed_slot": booking["confirmedStart"],
        }
        _match_request(invocation, result)
        return result, ToolOutcome.SUCCEEDED, booking["bookingId"]

    if state == "CANCELLATION_CONFIRMED":
        if invocation.tool_name != "appointment.cancel":
            raise AdapterProtocolError(
                AdapterErrorCode.INVALID_RESPONSE, "cancellation result is for another tool"
            )
        _forbid(response, "error", "retryCategory")
        booking = _booking(
            response,
            required={"bookingId", "serviceCenterId", "cancelledAt"},
        )
        result = {
            "phase": "FINAL",
            "status": "CANCELLATION_CONFIRMED",
            "provider_request_id": provider_id,
            "provider_booking_id": booking["bookingId"],
            "center_id": booking["serviceCenterId"],
            "cancelled_at": booking["cancelledAt"],
        }
        _match_request(invocation, result)
        return result, ToolOutcome.SUCCEEDED, booking["bookingId"]

    if state in {"BOOKING_FAILED", "LOOKUP_FAILED", "CANCELLATION_FAILED"}:
        error = strict_object(
            response.get("error"),
            field="error",
            allowed=_ERROR_FIELDS,
            required=_ERROR_FIELDS,
        )
        code = require_safe_code(error["code"], "error.code")
        result = {
            "phase": "FINAL",
            "status": state,
            "provider_request_id": provider_id,
            "error": {
                "code": code,
                "message": "Provider reported a failure",
                "retryable": require_bool(error["retryable"], "error.retryable"),
            },
        }
        effect_id = _optional_booking_identity(response)
        if effect_id is not None:
            result["provider_booking_id"] = effect_id
        return result, ToolOutcome.FAILED, effect_id

    if state == "OUTCOME_UNKNOWN":
        _forbid(response, "error", "retryCategory")
        result = {
            "phase": "FINAL",
            "status": "OUTCOME_UNKNOWN",
            "provider_request_id": provider_id,
        }
        effect_id = _optional_booking_identity(response)
        if effect_id is not None:
            result["provider_booking_id"] = effect_id
        return result, ToolOutcome.UNKNOWN, effect_id

    raise AdapterProtocolError(
        AdapterErrorCode.INVALID_RESPONSE, "unknown provider result state"
    )


def _booking(
    response: Mapping[str, Any], *, required: set[str]
) -> dict[str, Any]:
    booking = strict_object(
        response.get("booking"),
        field="booking",
        allowed=_BOOKING_FIELDS,
        required=required,
    )
    for field in required:
        if field in {"requestedStart", "confirmedStart", "cancelledAt"}:
            booking[field] = require_rfc3339(booking[field], f"booking.{field}")
        else:
            booking[field] = require_safe_text(booking[field], f"booking.{field}")
    return booking


def _forbid(response: Mapping[str, Any], *fields: str) -> None:
    if any(field in response for field in fields):
        raise AdapterProtocolError(
            AdapterErrorCode.INVALID_RESPONSE, "response contains contradictory fields"
        )


def _optional_booking_identity(response: Mapping[str, Any]) -> str | None:
    raw = response.get("booking")
    if raw is None:
        return None
    booking = strict_object(
        raw, field="booking", allowed=_BOOKING_FIELDS, required={"bookingId"}
    )
    return require_safe_text(booking["bookingId"], "booking.bookingId")


def _match_request(invocation: ToolInvocation, result: Mapping[str, Any]) -> None:
    args = invocation.arguments
    if invocation.tool_name == "appointment.book" and (
        result.get("center_id") != args.get("center_id")
        or result.get("requested_slot") != args.get("requested_slot")
    ):
        # A mismatched confirmed booking is still an authoritative world effect;
        # EffectInterpreter records it and ClaimGraph refuses desired confirmation.
        return
    if invocation.tool_name in {"appointment.get", "appointment.cancel"} and (
        result.get("provider_booking_id") != args.get("provider_booking_id")
        or ("center_id" in result and result.get("center_id") != args.get("center_id"))
    ):
        raise AdapterProtocolError(
            AdapterErrorCode.IDENTITY_MISMATCH, "result targets another booking"
        )


def _digest(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return f"samsung-local:{sha256(encoded.encode()).hexdigest()}"


__all__ = ["SamsungShapedToolAdapter"]
