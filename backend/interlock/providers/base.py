"""Private structured-model provider contracts owned by INTEL-001.

These types deliberately live outside the shared domain contract.  They describe
the boundary between semantic-control code and an injectable model transport;
they do not grant authority to mutate session state or invoke tools.
"""

from __future__ import annotations

from enum import Enum
import hashlib
import json
import math
from typing import Any, Awaitable, Dict, Optional, Protocol, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ProviderTask(str, Enum):
    """The four prompt contracts documented in LLM_CONTRACTS.md."""

    CONTROL_V1 = "CONTROL_V1"
    DELTA_V1 = "DELTA_V1"
    BRANCH_V1 = "BRANCH_V1"
    REFERENCE_V1 = "REFERENCE_V1"


class ProviderFailureKind(str, Enum):
    """Behaviorally distinct, fail-closed provider failures."""

    INVALID_OUTPUT = "INVALID_OUTPUT"
    TIMEOUT = "TIMEOUT"
    UNAVAILABLE = "UNAVAILABLE"


class ProviderBoundaryModel(BaseModel):
    """Strict immutable base for private provider-boundary values."""

    model_config = ConfigDict(extra="forbid", frozen=True, use_enum_values=False)


class ProviderRequest(ProviderBoundaryModel):
    """JSON-compatible request sent to a configured model transport."""

    task: ProviderTask
    prompt_version: str = Field(..., min_length=1)
    payload: Dict[str, Any]
    correlation_id: str = Field(..., min_length=1)
    timeout_ms: int = Field(..., gt=0)

    @field_validator("payload", mode="before")
    @classmethod
    def validate_json_payload(cls, value: Any) -> Dict[str, Any]:
        """Accept only finite, recursively JSON-compatible request data."""

        normalized = normalize_json_value(value, path="payload")
        if not isinstance(normalized, dict):
            raise ValueError("Provider payload must be a JSON object")
        return normalized


class ProviderSuccess(ProviderBoundaryModel):
    """Validated structured provider output."""

    task: ProviderTask
    data: Dict[str, Any]
    correlation_id: str
    input_digest: str
    repaired: bool = False


class ProviderFailure(ProviderBoundaryModel):
    """Typed failure returned instead of leaking transport exceptions."""

    task: ProviderTask
    kind: ProviderFailureKind
    correlation_id: str
    input_digest: str
    message: str
    repair_attempted: bool = False


ProviderResult = Union[ProviderSuccess, ProviderFailure]


class StructuredProvider(Protocol):
    """Interface consumed by the semantic-control orchestrator."""

    async def invoke(self, request: ProviderRequest) -> ProviderResult:
        """Return validated structured data or a typed failure."""


class ModelTransport(Protocol):
    """Injectable vendor-neutral model call.

    ``previous_output`` is supplied only for the single permitted format-repair
    attempt.  No vendor SDK or network contract is assumed here.
    """

    def __call__(
        self,
        request: ProviderRequest,
        *,
        repair: bool,
        previous_output: Optional[Any],
    ) -> Awaitable[Any]:
        """Produce an untrusted JSON object or JSON string."""


class ProviderUnavailableError(Exception):
    """Expected signal from an injected transport that it cannot serve a call."""


def request_digest(request: ProviderRequest) -> str:
    """Return a stable digest without logging or retaining the raw payload."""

    serialized = json.dumps(
        {
            "task": request.task.value,
            "prompt_version": request.prompt_version,
            "payload": request.payload,
            "correlation_id": request.correlation_id,
            "timeout_ms": request.timeout_ms,
        },
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(serialized).hexdigest()}"


def normalize_json_value(value: Any, *, path: str) -> Any:
    """Return a detached JSON-compatible value or reject it fail-closed."""

    if value is None or type(value) in (str, bool, int):
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError(f"{path} contains a non-finite number")
        return value
    if isinstance(value, list):
        return [
            normalize_json_value(item, path=f"{path}[{index}]")
            for index, item in enumerate(value)
        ]
    if isinstance(value, dict):
        normalized: Dict[str, Any] = {}
        for key, item in value.items():
            if type(key) is not str:
                raise ValueError(f"{path} contains a non-string object key")
            normalized[key] = normalize_json_value(item, path=f"{path}.{key}")
        return normalized
    raise ValueError(f"{path} contains non-JSON value of type {type(value).__name__}")
