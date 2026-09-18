"""Deterministic credential-free semantic interpretation for INTEL-001."""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any, Dict, Mapping, Optional

from interlock.domain.enums import ControlKind
from interlock.domain.models import IntentDelta


@dataclass(frozen=True)
class FallbackContext:
    """Trusted bounded context supplied by the runtime caller."""

    active_intent_id: Optional[str] = None
    candidate_target_ids: tuple[str, ...] = ()
    correction_field: Optional[str] = None
    value_aliases: Mapping[str, Any] = field(default_factory=dict)
    goal_additions: Mapping[str, Dict[str, Any]] = field(default_factory=dict)
    retractable_goal_ids: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class FallbackInterpretation:
    """Provider-neutral interpretation before trusted IDs are attached."""

    kind: ControlKind
    confidence: float
    consequential: bool
    target_refs: tuple[str, ...] = ()
    clarification: Optional[str] = None
    intent_delta: Optional[IntentDelta] = None


class DeterministicFallbackProvider:
    """Small ordered phrase policy for offline/demo operation."""

    def interpret(self, text: str, context: FallbackContext) -> FallbackInterpretation:
        normalized = _normalize(text)

        if _matches(normalized, r"\b(stop explaining|stop talking|be quiet|quiet please)\b"):
            return _result(ControlKind.CANCEL_SPEECH, 0.99, False)

        if _matches(normalized, r"\b(stop it|cancel it|never mind that)\b"):
            return _clarify("What would you like me to stop or cancel?")

        if _matches(normalized, r"\b(no\s+)?(do not|don't)\s+book\b"):
            targets = _active_targets(context)
            goal_id = context.retractable_goal_ids.get("booking")
            delta = None
            if context.active_intent_id and goal_id:
                delta = IntentDelta(
                    target_intent_id=context.active_intent_id,
                    retract_goals=[goal_id],
                    confidence=0.96,
                )
            return _result(
                ControlKind.RETRACT_GOAL,
                0.96,
                True,
                targets=targets,
                delta=delta,
            )

        if _matches(normalized, r"\b(no\s+)?(do not|don't)\s+check\s+(the\s+)?warranty\b"):
            goal_id = context.retractable_goal_ids.get("warranty")
            delta = None
            if context.active_intent_id and goal_id:
                delta = IntentDelta(
                    target_intent_id=context.active_intent_id,
                    retract_goals=[goal_id],
                    confidence=0.96,
                )
            return _result(
                ControlKind.RETRACT_GOAL,
                0.96,
                True,
                targets=(goal_id,) if goal_id else (),
                delta=delta,
            )

        if _matches(normalized, r"\b(also\s+)?check\s+(the\s+)?warranty\b"):
            goal = context.goal_additions.get("warranty")
            delta = None
            if context.active_intent_id and goal is not None:
                delta = IntentDelta(
                    target_intent_id=context.active_intent_id,
                    add_goals=[dict(goal)],
                    confidence=0.96,
                )
            return _result(ControlKind.ADD_GOAL, 0.96, True, delta=delta)

        if _matches(normalized, r"\b(wait|hold on|pause)\b"):
            return _result(ControlKind.PAUSE, 0.98, True)

        if _matches(normalized, r"\b(continue|resume|go on)\b"):
            return _result(ControlKind.RESUME, 0.98, True)

        if _matches(normalized, r"\b(that one|the one before this|the earlier one|before this)\b"):
            if len(context.candidate_target_ids) == 1:
                return _result(
                    ControlKind.REFER,
                    0.92,
                    True,
                    targets=context.candidate_target_ids,
                )
            return _clarify("Which earlier item do you mean?")

        if _matches(normalized, r"\b(new topic|something else|talk about)\b"):
            return _result(ControlKind.NEW_TOPIC, 0.90, True)

        if _matches(normalized, r"\b(actually|make it|make that|change it to|change that to)\b"):
            return self._correction(normalized, context)

        if normalized in {"ok", "okay", "yes", "right", "thanks", "thank you", "uh huh"}:
            return _result(ControlKind.BACKCHANNEL, 0.96, False)

        return _clarify("Could you clarify what you want to change or continue?")

    def _correction(
        self,
        normalized: str,
        context: FallbackContext,
    ) -> FallbackInterpretation:
        targets = _active_targets(context)
        if context.active_intent_id is None:
            return _clarify("Which active request should I correct?")

        delta = None
        value_token = _last_value_token(normalized)
        if context.correction_field and value_token:
            value = context.value_aliases.get(value_token, value_token)
            delta = IntentDelta(
                target_intent_id=context.active_intent_id,
                set_fields={context.correction_field: value},
                confidence=0.96,
            )
        return _result(
            ControlKind.CORRECT,
            0.96,
            True,
            targets=targets,
            delta=delta,
        )


def _normalize(text: str) -> str:
    return " ".join(text.strip().lower().replace("’", "'").split())


def _matches(text: str, pattern: str) -> bool:
    return re.search(pattern, text, flags=re.IGNORECASE) is not None


def _last_value_token(text: str) -> Optional[str]:
    matches = re.findall(r"\b\d{1,2}(?::\d{2})?(?:\s*[ap]m)?\b", text)
    return matches[-1].replace(" ", "") if matches else None


def _active_targets(context: FallbackContext) -> tuple[str, ...]:
    if context.active_intent_id is None:
        return ()
    return (context.active_intent_id,)


def _clarify(message: str) -> FallbackInterpretation:
    return _result(ControlKind.CLARIFY, 1.0, True, clarification=message)


def _result(
    kind: ControlKind,
    confidence: float,
    consequential: bool,
    *,
    targets: tuple[str, ...] = (),
    clarification: Optional[str] = None,
    delta: Optional[IntentDelta] = None,
) -> FallbackInterpretation:
    return FallbackInterpretation(
        kind=kind,
        confidence=confidence,
        consequential=consequential,
        target_refs=targets,
        clarification=clarification,
        intent_delta=delta,
    )
