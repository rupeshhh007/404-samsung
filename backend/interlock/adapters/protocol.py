"""Shared adapter-side protocol utilities for untrusted local tool endpoints.

This module is below the canonical ``ToolProviderTransport`` boundary.  It does
not introduce another execution contract: clients exchange provisional wire
objects, while adapters remain responsible for producing the existing
``ProviderResponse`` and ``ProviderObservation`` types.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from enum import Enum
import re
from typing import Any, Protocol

from interlock.execution.idempotency import IdempotencyError, strict_json_copy


_SAFE_CODE = re.compile(r"[A-Z][A-Z0-9_:-]{0,127}")


class AdapterErrorCode(str, Enum):
    INVALID_REQUEST = "INVALID_REQUEST"
    INVALID_RESPONSE = "INVALID_RESPONSE"
    IDENTITY_MISMATCH = "IDENTITY_MISMATCH"
    UNSUPPORTED_TOOL = "UNSUPPORTED_TOOL"
    TRANSPORT_FAILURE = "TRANSPORT_FAILURE"


class AdapterProtocolError(ValueError):
    """An untrusted wire object failed closed at the adapter boundary."""

    def __init__(self, code: AdapterErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code


class WireClientFailure(Exception):
    """Sanitized endpoint failure with explicit dispatch-boundary knowledge."""

    def __init__(
        self,
        category: str,
        *,
        after_dispatch: bool,
        provider_request_id: str | None = None,
    ) -> None:
        if _SAFE_CODE.fullmatch(category) is None:
            raise ValueError("category must be a stable safe code")
        if type(after_dispatch) is not bool:
            raise TypeError("after_dispatch must be a boolean")
        if provider_request_id is not None:
            require_safe_text(provider_request_id, "provider_request_id")
        super().__init__("wire client failed")
        self.category = category
        self.after_dispatch = after_dispatch
        self.provider_request_id = provider_request_id


class ProviderWireClient(Protocol):
    """Injected local/network endpoint used only behind a provider adapter."""

    async def invoke(self, request: Mapping[str, Any]) -> Mapping[str, Any]:
        """Return one detached provisional response mapping."""

    async def cancel(self, request: Mapping[str, Any]) -> Mapping[str, Any]:
        """Return one detached provisional cancellation mapping."""


def strict_object(
    value: Any,
    *,
    field: str,
    allowed: frozenset[str] | set[str] | tuple[str, ...],
    required: frozenset[str] | set[str] | tuple[str, ...] = (),
) -> dict[str, Any]:
    """Copy a strict JSON object and reject unknown or absent fields."""

    if not isinstance(value, Mapping):
        raise AdapterProtocolError(
            AdapterErrorCode.INVALID_RESPONSE, f"{field} must be an object"
        )
    try:
        copied = strict_json_copy(dict(value), field=field)
    except (IdempotencyError, TypeError, ValueError) as exc:
        raise AdapterProtocolError(
            AdapterErrorCode.INVALID_RESPONSE, f"{field} must be strict JSON"
        ) from exc
    if any(not isinstance(key, str) for key in copied):
        raise AdapterProtocolError(
            AdapterErrorCode.INVALID_RESPONSE, f"{field} keys must be strings"
        )
    allowed_set = frozenset(allowed)
    unknown = frozenset(copied) - allowed_set
    if unknown:
        raise AdapterProtocolError(
            AdapterErrorCode.INVALID_RESPONSE, f"{field} has unknown fields"
        )
    missing = frozenset(required) - frozenset(copied)
    if missing:
        raise AdapterProtocolError(
            AdapterErrorCode.INVALID_RESPONSE, f"{field} is missing required fields"
        )
    return copied


def require_safe_text(value: Any, field: str, *, maximum: int = 512) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > maximum
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise AdapterProtocolError(
            AdapterErrorCode.INVALID_RESPONSE, f"{field} must be safe nonempty text"
        )
    return value


def require_safe_code(value: Any, field: str) -> str:
    text = require_safe_text(value, field, maximum=128)
    if _SAFE_CODE.fullmatch(text) is None:
        raise AdapterProtocolError(
            AdapterErrorCode.INVALID_RESPONSE, f"{field} must be a stable code"
        )
    return text


def require_version(value: Any, field: str = "schemaVersion") -> int:
    if type(value) is not int or value != 1:
        raise AdapterProtocolError(
            AdapterErrorCode.INVALID_RESPONSE, f"{field} must equal 1"
        )
    return value


def require_bool(value: Any, field: str) -> bool:
    if type(value) is not bool:
        raise AdapterProtocolError(
            AdapterErrorCode.INVALID_RESPONSE, f"{field} must be boolean"
        )
    return value


def require_rfc3339(value: Any, field: str) -> str:
    text = require_safe_text(value, field)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise AdapterProtocolError(
            AdapterErrorCode.INVALID_RESPONSE, f"{field} must be RFC3339"
        ) from exc
    if parsed.tzinfo is None:
        raise AdapterProtocolError(
            AdapterErrorCode.INVALID_RESPONSE, f"{field} must include an offset"
        )
    return text


__all__ = [
    "AdapterErrorCode",
    "AdapterProtocolError",
    "ProviderWireClient",
    "WireClientFailure",
    "require_bool",
    "require_rfc3339",
    "require_safe_code",
    "require_safe_text",
    "require_version",
    "strict_object",
]
