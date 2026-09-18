"""Semantic-control orchestration for INTEL-001.

The interpreter converts trusted input evidence into proposals only.  It has no
runtime, tool, evidence-store, claim, speech, or external-effect dependencies.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional

from pydantic import BaseModel, ConfigDict, Field

from interlock.config import Settings
from interlock.domain.enums import ControlKind, RuntimeMode
from interlock.domain.models import ControlIntent, IntentDelta
from interlock.providers.base import (
    ProviderFailure,
    ProviderFailureKind,
    ProviderRequest,
    ProviderSuccess,
    ProviderTask,
    StructuredProvider,
    request_digest,
)
from interlock.providers.fallback import (
    DeterministicFallbackProvider,
    FallbackContext,
    FallbackInterpretation,
)


CONTROL_CONSEQUENTIAL_THRESHOLD = 0.85
_DEFAULT_MODEL_TIMEOUT_MS = 5_000
_CANONICALLY_CONSEQUENTIAL = frozenset(
    {
        ControlKind.CORRECT,
        ControlKind.ADD_GOAL,
        ControlKind.RETRACT_GOAL,
        ControlKind.PAUSE,
        ControlKind.RESUME,
        ControlKind.NEW_TOPIC,
    }
)
_DELTA_CONTROL_KINDS = frozenset(
    {ControlKind.CORRECT, ControlKind.ADD_GOAL, ControlKind.RETRACT_GOAL}
)


class _ControlBoundaryModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class InterpretationRequest(_ControlBoundaryModel):
    """Trusted, bounded input supplied by a future runtime dispatcher."""

    control_id: str = Field(..., min_length=1)
    raw_evidence_id: str = Field(..., min_length=1)
    text: str
    final: bool = True
    correlation_id: str = Field(..., min_length=1)
    candidate_target_ids: List[str] = Field(default_factory=list)
    active_intent_id: Optional[str] = None
    context: Dict[str, Any] = Field(default_factory=dict)
    timeout_ms: int = Field(default=_DEFAULT_MODEL_TIMEOUT_MS, gt=0)


class InterpretationResult(_ControlBoundaryModel):
    """Canonical proposal plus explicit transcript provisionality."""

    control: ControlIntent
    intent_delta: Optional[IntentDelta] = None
    provisional: bool
    provider_failure: Optional[ProviderFailure] = None


class ControlInterpreter:
    """Interpret immutable user evidence without causing external effects."""

    def __init__(
        self,
        settings: Settings,
        *,
        configured_provider: Optional[StructuredProvider] = None,
        fallback_provider: Optional[DeterministicFallbackProvider] = None,
    ) -> None:
        self._settings = settings
        self._configured_provider = configured_provider
        self._fallback = fallback_provider or DeterministicFallbackProvider()

    async def interpret(self, request: InterpretationRequest) -> InterpretationResult:
        fallback_context = _fallback_context(request)
        failure: Optional[ProviderFailure] = None

        if self._settings.INTERLOCK_MODEL_PROVIDER == "configured":
            proposal, failure = await self._configured_interpretation(request)
            if proposal is None:
                if self._fallback_enabled:
                    proposal = self._fallback.interpret(request.text, fallback_context)
                else:
                    proposal = _safe_clarification(
                        "I could not safely interpret that request. Please clarify."
                    )
            elif failure is not None and proposal.kind in _DELTA_CONTROL_KINDS:
                if self._fallback_enabled:
                    fallback_proposal = self._fallback.interpret(
                        request.text,
                        fallback_context,
                    )
                    if (
                        fallback_proposal.kind in _DELTA_CONTROL_KINDS
                        and fallback_proposal.intent_delta is None
                    ):
                        proposal = _safe_clarification(
                            "I could not safely represent that change. Please clarify."
                        )
                    else:
                        proposal = fallback_proposal
                else:
                    proposal = _safe_clarification(
                        "I could not safely represent that change. Please clarify."
                    )
        else:
            proposal = self._fallback.interpret(request.text, fallback_context)

        proposal = _enforce_policy(request, proposal)
        delta = proposal.intent_delta
        if not request.final:
            # A partial transcript is explicitly provisional.  Returning a delta is
            # safe because it remains a proposal and the result carries that status.
            provisional = True
        else:
            provisional = False

        control = ControlIntent(
            control_id=request.control_id,
            kind=proposal.kind,
            confidence=proposal.confidence,
            consequential=proposal.consequential,
            target_refs=list(proposal.target_refs),
            raw_evidence_id=request.raw_evidence_id,
            clarification=proposal.clarification,
        )
        return InterpretationResult(
            control=control,
            intent_delta=delta,
            provisional=provisional,
            provider_failure=failure,
        )

    @property
    def _fallback_enabled(self) -> bool:
        return self._settings.INTERLOCK_MODE in (RuntimeMode.DEMO, RuntimeMode.TEST)

    async def _configured_interpretation(
        self,
        request: InterpretationRequest,
    ) -> tuple[Optional[FallbackInterpretation], Optional[ProviderFailure]]:
        control_request = _control_provider_request(request)
        if self._configured_provider is None:
            return None, ProviderFailure(
                task=ProviderTask.CONTROL_V1,
                kind=ProviderFailureKind.UNAVAILABLE,
                correlation_id=request.correlation_id,
                input_digest=request_digest(control_request),
                message="Configured model provider is unavailable",
            )

        control_result = await self._configured_provider.invoke(control_request)
        if isinstance(control_result, ProviderFailure):
            return None, control_result

        proposal = _proposal_from_success(control_result)
        delta: Optional[IntentDelta] = None
        if (
            proposal.kind in {ControlKind.CORRECT, ControlKind.ADD_GOAL, ControlKind.RETRACT_GOAL}
            and proposal.confidence >= CONTROL_CONSEQUENTIAL_THRESHOLD
            and request.active_intent_id is not None
        ):
            delta_result = await self._configured_provider.invoke(
                ProviderRequest(
                    task=ProviderTask.DELTA_V1,
                    prompt_version="1",
                    payload={
                        "text": request.text,
                        "allowed_target_intent_ids": [request.active_intent_id],
                        "context": request.context,
                    },
                    correlation_id=request.correlation_id,
                    timeout_ms=request.timeout_ms,
                )
            )
            if isinstance(delta_result, ProviderSuccess):
                delta = IntentDelta.model_validate(delta_result.data)
            else:
                return proposal, delta_result

        return FallbackInterpretation(
            kind=proposal.kind,
            confidence=proposal.confidence,
            consequential=proposal.consequential,
            target_refs=proposal.target_refs,
            clarification=proposal.clarification,
            intent_delta=delta,
        ), None


def _proposal_from_success(success: ProviderSuccess) -> FallbackInterpretation:
    data = success.data
    return FallbackInterpretation(
        kind=ControlKind(data["kind"]),
        confidence=float(data["confidence"]),
        consequential=bool(data["consequential"]),
        target_refs=tuple(data.get("target_refs", [])),
        clarification=data.get("clarification"),
    )


def _fallback_context(request: InterpretationRequest) -> FallbackContext:
    context = request.context
    return FallbackContext(
        active_intent_id=request.active_intent_id,
        candidate_target_ids=tuple(request.candidate_target_ids),
        correction_field=_optional_string(context.get("correction_field")),
        value_aliases=_mapping(context.get("value_aliases")),
        goal_additions=_dict_mapping(context.get("goal_additions")),
        retractable_goal_ids=_string_mapping(context.get("retractable_goal_ids")),
    )


def _control_provider_request(request: InterpretationRequest) -> ProviderRequest:
    return ProviderRequest(
        task=ProviderTask.CONTROL_V1,
        prompt_version="1",
        payload={
            "text": request.text,
            "final": request.final,
            "candidate_ids": request.candidate_target_ids,
            "active_intent_id": request.active_intent_id,
            "context": request.context,
        },
        correlation_id=request.correlation_id,
        timeout_ms=request.timeout_ms,
    )


def _enforce_policy(
    request: InterpretationRequest,
    proposal: FallbackInterpretation,
) -> FallbackInterpretation:
    proposal = _normalize_consequential(proposal)
    if proposal.consequential and proposal.confidence < CONTROL_CONSEQUENTIAL_THRESHOLD:
        return _safe_clarification(
            proposal.clarification
            or "Please clarify the consequential change you want me to make."
        )

    if proposal.kind in _DELTA_CONTROL_KINDS and proposal.intent_delta is None:
        return _safe_clarification(
            "I could not safely represent that change. Please clarify."
        )

    if proposal.consequential and _contains_ambiguous_target(request.text):
        if len(proposal.target_refs) != 1:
            return _safe_clarification("Which specific item or operation do you mean?")

    if any(target not in request.candidate_target_ids for target in proposal.target_refs):
        return _safe_clarification("I could not match that reference to the supplied context.")

    return proposal


def _normalize_consequential(
    proposal: FallbackInterpretation,
) -> FallbackInterpretation:
    """Prevent a model from downgrading canonical state-affecting controls."""

    if proposal.kind not in _CANONICALLY_CONSEQUENTIAL or proposal.consequential:
        return proposal
    return FallbackInterpretation(
        kind=proposal.kind,
        confidence=proposal.confidence,
        consequential=True,
        target_refs=proposal.target_refs,
        clarification=proposal.clarification,
        intent_delta=proposal.intent_delta,
    )


def _safe_clarification(message: str) -> FallbackInterpretation:
    return FallbackInterpretation(
        kind=ControlKind.CLARIFY,
        confidence=1.0,
        consequential=True,
        clarification=message,
        intent_delta=None,
    )


def _contains_ambiguous_target(text: str) -> bool:
    normalized = f" {' '.join(text.lower().split())} "
    return any(token in normalized for token in (" it ", " that ", " that one "))


def _optional_string(value: Any) -> Optional[str]:
    return value if isinstance(value, str) and value else None


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _dict_mapping(value: Any) -> Mapping[str, Dict[str, Any]]:
    if not isinstance(value, Mapping):
        return {}
    return {
        str(key): dict(item)
        for key, item in value.items()
        if isinstance(item, Mapping)
    }


def _string_mapping(value: Any) -> Mapping[str, str]:
    if not isinstance(value, Mapping):
        return {}
    return {
        str(key): item
        for key, item in value.items()
        if isinstance(item, str)
    }
