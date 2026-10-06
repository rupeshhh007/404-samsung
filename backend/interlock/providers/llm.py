"""Vendor-neutral configured-model boundary for INTEL-001.

All model output is untrusted until it passes a strict task-specific schema and
candidate-allowlist validation.  The actual network/model transport is injected;
the repository intentionally does not select or depend on a vendor SDK.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, List, Mapping, Optional, Type

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from interlock.domain.enums import ActionType, ControlKind, EffectClassification
from interlock.domain.models import IntentDelta
from interlock.providers.base import (
    ModelTransport,
    ProviderFailure,
    ProviderFailureKind,
    ProviderRequest,
    ProviderResult,
    ProviderSuccess,
    ProviderTask,
    ProviderUnavailableError,
    StructuredProvider,
    normalize_json_value,
    request_digest,
)


class _StrictOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, use_enum_values=False)


class ControlOutput(_StrictOutput):
    kind: ControlKind
    confidence: float = Field(..., ge=0.0, le=1.0)
    consequential: bool
    target_refs: List[str] = Field(default_factory=list)
    clarification: Optional[str] = None


class DeltaOutput(IntentDelta):
    """Canonical IntentDelta reused directly as the DELTA_V1 output schema."""


class BranchCandidateOutput(_StrictOutput):
    delta: IntentDelta
    confidence: float = Field(..., ge=0.0, le=1.0)
    tool_names: List[str] = Field(default_factory=list)


class BranchOutput(_StrictOutput):
    candidates: List[BranchCandidateOutput] = Field(default_factory=list)


class ReferenceOutput(_StrictOutput):
    candidate_evidence_ids: List[str] = Field(default_factory=list)
    confidence: float = Field(..., ge=0.0, le=1.0)
    reason: str


_OUTPUT_MODELS: Dict[ProviderTask, Type[BaseModel]] = {
    ProviderTask.CONTROL_V1: ControlOutput,
    ProviderTask.DELTA_V1: DeltaOutput,
    ProviderTask.BRANCH_V1: BranchOutput,
    ProviderTask.REFERENCE_V1: ReferenceOutput,
}


class _RepairableFormatError(ValueError):
    """Malformed JSON or structural shape that may receive one repair."""


class _PolicyViolation(ValueError):
    """Security/allowlist/policy failure that must never enter repair."""


class StructuredModelProvider(StructuredProvider):
    """Validate an injected configured-model call and fail closed."""

    def __init__(self, transport: Optional[ModelTransport]) -> None:
        self._transport = transport

    async def invoke(self, request: ProviderRequest) -> ProviderResult:
        digest = request_digest(request)
        if self._transport is None:
            return self._failure(
                request,
                digest,
                ProviderFailureKind.UNAVAILABLE,
                "Configured model transport is unavailable",
            )

        first = await self._call_transport(request, digest, repair=False, previous=None)
        if isinstance(first, ProviderFailure):
            return first

        try:
            return self._validate_success(request, digest, first, repaired=False)
        except _PolicyViolation as error:
            return self._failure(
                request,
                digest,
                ProviderFailureKind.INVALID_OUTPUT,
                f"Structured output violated policy: {error}",
            )
        except _RepairableFormatError:
            repaired = await self._call_transport(
                request,
                digest,
                repair=True,
                previous=first,
            )
            if isinstance(repaired, ProviderFailure):
                return repaired.model_copy(update={"repair_attempted": True})
            try:
                return self._validate_success(request, digest, repaired, repaired=True)
            except (_RepairableFormatError, _PolicyViolation) as repair_error:
                return self._failure(
                    request,
                    digest,
                    ProviderFailureKind.INVALID_OUTPUT,
                    f"Structured output remained invalid after one repair: {type(repair_error).__name__}",
                    repair_attempted=True,
                )

    async def _call_transport(
        self,
        request: ProviderRequest,
        digest: str,
        *,
        repair: bool,
        previous: Optional[Any],
    ) -> Any:
        assert self._transport is not None
        try:
            return await asyncio.wait_for(
                self._transport(request, repair=repair, previous_output=previous),
                timeout=request.timeout_ms / 1000.0,
            )
        except (asyncio.TimeoutError, TimeoutError):
            return self._failure(
                request,
                digest,
                ProviderFailureKind.TIMEOUT,
                "Configured model request timed out",
                repair_attempted=repair,
            )
        except ProviderUnavailableError:
            return self._failure(
                request,
                digest,
                ProviderFailureKind.UNAVAILABLE,
                "Configured model transport is unavailable",
                repair_attempted=repair,
            )
        except (ConnectionError, OSError):
            return self._failure(
                request,
                digest,
                ProviderFailureKind.UNAVAILABLE,
                "Configured model transport failed",
                repair_attempted=repair,
            )
        except Exception as error:
            # A vendor adapter is an untrusted boundary.  Preserve only the
            # exception class, never its potentially sensitive message.
            return self._failure(
                request,
                digest,
                ProviderFailureKind.UNAVAILABLE,
                f"Configured model transport raised {type(error).__name__}",
                repair_attempted=repair,
            )

    def _validate_success(
        self,
        request: ProviderRequest,
        digest: str,
        raw_output: Any,
        *,
        repaired: bool,
    ) -> ProviderSuccess:
        parsed = _parse_object(raw_output)
        try:
            model = _OUTPUT_MODELS[request.task].model_validate(parsed)
        except ValidationError as error:
            if _is_policy_validation_error(error):
                raise _PolicyViolation("task-specific schema policy rejected the output") from error
            raise _RepairableFormatError("task-specific output shape is invalid") from error
        _validate_allowed_values(request, model)
        return ProviderSuccess(
            task=request.task,
            data=model.model_dump(mode="json", by_alias=True),
            correlation_id=request.correlation_id,
            input_digest=digest,
            repaired=repaired,
        )

    @staticmethod
    def _failure(
        request: ProviderRequest,
        digest: str,
        kind: ProviderFailureKind,
        message: str,
        *,
        repair_attempted: bool = False,
    ) -> ProviderFailure:
        return ProviderFailure(
            task=request.task,
            kind=kind,
            correlation_id=request.correlation_id,
            input_digest=digest,
            message=message,
            repair_attempted=repair_attempted,
        )


def validate_structured_output(request: ProviderRequest, raw_output: Any) -> Dict[str, Any]:
    """Validate output without invoking a transport; useful at trusted boundaries."""

    parsed = _parse_object(raw_output)
    try:
        model = _OUTPUT_MODELS[request.task].model_validate(parsed)
    except ValidationError as error:
        if _is_policy_validation_error(error):
            raise _PolicyViolation("task-specific schema policy rejected the output") from error
        raise _RepairableFormatError("task-specific output shape is invalid") from error
    _validate_allowed_values(request, model)
    return model.model_dump(mode="json", by_alias=True)


def _parse_object(raw_output: Any) -> Dict[str, Any]:
    if isinstance(raw_output, str):
        try:
            parsed = json.loads(raw_output)
        except json.JSONDecodeError as error:
            raise _RepairableFormatError("Configured model output is malformed JSON") from error
    else:
        parsed = dict(raw_output) if isinstance(raw_output, Mapping) else raw_output
    try:
        parsed = normalize_json_value(parsed, path="output")
    except ValueError as error:
        raise _PolicyViolation(
            "Configured model output contains a non-JSON value"
        ) from error
    if not isinstance(parsed, dict):
        raise _RepairableFormatError("Configured model output must decode to a JSON object")
    return parsed


def _validate_allowed_values(request: ProviderRequest, output: BaseModel) -> None:
    payload = request.payload
    if request.task == ProviderTask.CONTROL_V1:
        assert isinstance(output, ControlOutput)
        _require_subset(output.target_refs, payload.get("candidate_ids", []), "target_refs")
        return

    if request.task == ProviderTask.DELTA_V1:
        assert isinstance(output, IntentDelta)
        _require_subset(
            [output.target_intent_id],
            payload.get("allowed_target_intent_ids", []),
            "target_intent_id",
        )
        return

    if request.task == ProviderTask.REFERENCE_V1:
        assert isinstance(output, ReferenceOutput)
        _require_subset(
            output.candidate_evidence_ids,
            payload.get("candidate_evidence_ids", []),
            "candidate_evidence_ids",
        )
        return

    assert request.task == ProviderTask.BRANCH_V1
    assert isinstance(output, BranchOutput)
    max_candidates = payload.get("max_candidates")
    if not isinstance(max_candidates, int) or max_candidates < 0:
        raise _PolicyViolation("BRANCH_V1 requires a non-negative max_candidates")
    if len(output.candidates) > max_candidates:
        raise _PolicyViolation("BRANCH_V1 returned more than the supplied candidate limit")

    allowed_targets = payload.get("allowed_target_intent_ids", [])
    safe_tools = _safe_branch_tools(payload.get("descriptors", []))
    for candidate in output.candidates:
        _require_subset(
            [candidate.delta.target_intent_id],
            allowed_targets,
            "branch target_intent_id",
        )
        _require_subset(candidate.tool_names, safe_tools, "branch tool_names")


def _safe_branch_tools(raw_descriptors: Any) -> List[str]:
    if not isinstance(raw_descriptors, list):
        raise _PolicyViolation("descriptors must be a list")
    safe: List[str] = []
    for descriptor in raw_descriptors:
        if not isinstance(descriptor, Mapping):
            raise _PolicyViolation("descriptor entries must be objects")
        if (
            descriptor.get("action_type") == ActionType.READ_ONLY.value
            and descriptor.get("effect_classification") == EffectClassification.NONE.value
            and isinstance(descriptor.get("tool_name"), str)
        ):
            safe.append(descriptor["tool_name"])
    return safe


def _require_subset(values: List[str], allowed_values: Any, field_name: str) -> None:
    if not isinstance(allowed_values, list) or not all(
        isinstance(value, str) for value in allowed_values
    ):
        raise _PolicyViolation(
            f"Allowed values for {field_name} must be a list of strings"
        )
    unknown = sorted(set(values) - set(allowed_values))
    if unknown:
        raise _PolicyViolation(f"{field_name} contains values not supplied by the caller")


def _is_policy_validation_error(error: ValidationError) -> bool:
    """Separate non-repairable policy violations from repairable shape errors."""

    policy_error_types = {
        "extra_forbidden",
        "finite_number",
        "greater_than",
        "greater_than_equal",
        "less_than",
        "less_than_equal",
        "string_too_short",
        "enum",
    }
    return any(item["type"] in policy_error_types for item in error.errors())
