"""Deterministic TEST/DEMO fault plans for an injected scenario driver.

This module never invokes a provider, journals an event, or changes runtime
state. The driver journals ``FaultActivated`` first, then passes its accepted
envelope to ``activate``. All resulting work uses the TST-001 virtual clock.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from interlock.domain.enums import EventSource, RuntimeMode
from interlock.domain.models import EventEnvelope
from interlock.runtime.journal import EventCandidate
from interlock.testing.clock import ScheduleHandle, VirtualClock


_FAULT_FIELDS: dict[str, frozenset[str]] = {
    "LATENCY": frozenset({"delay_ms"}),
    "FAILURE": frozenset({"code", "before_dispatch"}),
    "TIMEOUT": frozenset({"after_dispatch"}),
    "IGNORE_CANCELLATION": frozenset(),
    "LATE_RESULT": frozenset({"delay_ms"}),
    "COMMIT_BEFORE_CANCEL": frozenset({"commit_at_ms", "cancel_at_ms"}),
    "DUPLICATE_CALLBACK": frozenset({"count", "identical"}),
    "DUPLICATE_RETRY": frozenset({"provider_idempotency_supported", "same_key"}),
    "UNKNOWN_OUTCOME": frozenset({"after_dispatch"}),
    "COMPENSATION_FAILURE": frozenset({"code"}),
}
_MATCH_FIELDS = frozenset({
    "operation_id", "tool_name", "idempotency_key", "provider_request_id",
    "callback_id", "args.center_id", "args.requested_slot",
    "args.provider_booking_id", "args.device_id", "args.error_code",
})
_SAFE_CODE = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_:-")


def _text(value: Any, field: str) -> str:
    if (not isinstance(value, str) or not value or value != value.strip()
            or len(value) > 512 or any(ord(char) < 32 or ord(char) == 127 for char in value)):
        raise ValueError(f"{field} must be safe nonempty text")
    return value


def _time(value: Any, field: str, *, positive: bool = False) -> int:
    if type(value) is not int or value < (1 if positive else 0) or value > 60_000:
        raise ValueError(f"{field} must be a bounded logical millisecond value")
    return value


@dataclass(frozen=True, slots=True)
class Fault:
    """One strictly validated immutable scenario declaration."""

    fault_id: str
    fault_type: str
    match: tuple[tuple[str, str], ...]
    parameters: tuple[tuple[str, str | int | bool], ...]

    @classmethod
    def parse(cls, raw: Mapping[str, Any]) -> "Fault":
        if not isinstance(raw, Mapping):
            raise TypeError("fault must be an object")
        kind = raw.get("type")
        if kind not in _FAULT_FIELDS:
            raise ValueError("unknown fault type")
        fields = _FAULT_FIELDS[kind]
        if frozenset(raw) != {"id", "type", "match"} | fields:
            raise ValueError("fault fields do not match canonical type")
        identity = _text(raw["id"], "id")
        match = raw["match"]
        if (not isinstance(match, Mapping) or not match
                or not set(match) <= _MATCH_FIELDS):
            raise ValueError("fault match must use supported nonempty identities")
        normalized_match = tuple(sorted(
            (key, _text(value, f"match.{key}")) for key, value in match.items()
        ))
        values = {key: raw[key] for key in fields}
        if kind in {"LATENCY", "LATE_RESULT"}:
            _time(values["delay_ms"], "delay_ms", positive=True)
        elif kind == "COMMIT_BEFORE_CANCEL":
            commit = _time(values["commit_at_ms"], "commit_at_ms")
            cancel = _time(values["cancel_at_ms"], "cancel_at_ms")
            if commit >= cancel:
                raise ValueError("commit must precede cancellation")
        elif kind == "DUPLICATE_CALLBACK":
            if type(values["count"]) is not int or not 2 <= values["count"] <= 8:
                raise ValueError("duplicate callback count must be 2..8")
            if type(values["identical"]) is not bool:
                raise ValueError("identical must be boolean")
        elif kind == "DUPLICATE_RETRY":
            if any(type(value) is not bool for value in values.values()):
                raise ValueError("retry flags must be boolean")
        elif kind in {"TIMEOUT", "UNKNOWN_OUTCOME"}:
            if type(values["after_dispatch"]) is not bool:
                raise ValueError("after_dispatch must be boolean")
            if kind == "UNKNOWN_OUTCOME" and not values["after_dispatch"]:
                raise ValueError("unknown outcome requires a crossed provider boundary")
        elif kind == "FAILURE":
            _code(values["code"])
            if type(values["before_dispatch"]) is not bool:
                raise ValueError("before_dispatch must be boolean")
        elif kind == "COMPENSATION_FAILURE":
            _code(values["code"])
        return cls(identity, kind, normalized_match, tuple(sorted(values.items())))

    def match_dict(self) -> dict[str, str]:
        return dict(self.match)

    def parameter_dict(self) -> dict[str, str | int | bool]:
        return dict(self.parameters)


def _code(value: Any) -> str:
    text = _text(value, "code")
    if len(text) > 128 or not set(text) <= _SAFE_CODE or text[0] not in _SAFE_CODE - frozenset("0123456789_:-"):
        raise ValueError("failure code must be a stable uppercase code")
    return text


@dataclass(frozen=True, slots=True)
class FaultDecision:
    """Detached driver instruction, never an authoritative runtime fact."""

    fault_id: str
    fault_type: str
    parameters: tuple[tuple[str, str | int | bool], ...]

    def parameter_dict(self) -> dict[str, str | int | bool]:
        return dict(self.parameters)


class FaultEngine:
    """Session-local activation and virtual scheduling for explicit faults."""

    def __init__(
        self, clock: VirtualClock, declarations: Sequence[Mapping[str, Any]] = (),
        *, mode: RuntimeMode = RuntimeMode.TEST,
    ) -> None:
        if not isinstance(clock, VirtualClock):
            raise TypeError("clock must be VirtualClock")
        if mode not in {RuntimeMode.TEST, RuntimeMode.DEMO}:
            raise ValueError("fault engine is TEST/DEMO-only")
        if len(declarations) > 128:
            raise ValueError("too many fault declarations")
        self.clock = clock
        self.mode = mode
        self._faults = tuple(Fault.parse(deepcopy(dict(raw))) for raw in declarations)
        if len({fault.fault_id for fault in self._faults}) != len(self._faults):
            raise ValueError("duplicate fault identity")
        if len({(fault.fault_type, fault.match) for fault in self._faults}) != len(self._faults):
            raise ValueError("ambiguous duplicate fault match")
        self._by_id = {fault.fault_id: fault for fault in self._faults}
        self._activated: dict[str, str] = {}
        self._session_id: str | None = None

    @property
    def declarations(self) -> tuple[dict[str, Any], ...]:
        return tuple({
            "id": fault.fault_id, "type": fault.fault_type,
            "match": fault.match_dict(), **fault.parameter_dict(),
        } for fault in self._faults)

    def activation_candidate(self, session_id: str, fault_id: str) -> EventCandidate:
        """Candidate for caller-owned journal; this does not activate the fault."""
        fault = self._by_id[fault_id]
        return EventCandidate(
            event_type="FaultActivated", session_id=_text(session_id, "session_id"),
            source=EventSource.SCENARIO, logical_time=self.clock.now(),
            payload={"fault_id": fault.fault_id, "operation_match": fault.match_dict()},
            dedupe_key=f"fault:{session_id}:{fault.fault_id}",
        )

    def activate(self, accepted: EventEnvelope) -> None:
        """Accept only the matching, already-journaled scenario fact."""
        if not isinstance(accepted, EventEnvelope) or accepted.event_type != "FaultActivated":
            raise ValueError("activation requires an accepted FaultActivated envelope")
        if accepted.source != EventSource.SCENARIO:
            raise ValueError("fault activation must come from scenario ingress")
        if self._session_id is not None and accepted.session_id != self._session_id:
            raise ValueError("fault activation belongs to another session")
        if accepted.logical_time > self.clock.now():
            raise ValueError("fault activation cannot precede its accepted logical time")
        fault_id = accepted.payload.get("fault_id")
        fault = self._by_id.get(fault_id)
        if fault is None or accepted.payload.get("operation_match") != fault.match_dict():
            raise ValueError("accepted fault fact does not match declaration")
        prior = self._activated.get(fault_id)
        if prior is not None and prior != accepted.event_id:
            raise ValueError("fault was activated by a different fact")
        self._session_id = accepted.session_id
        self._activated[fault_id] = accepted.event_id

    def decisions_for(self, metadata: Mapping[str, Any]) -> tuple[FaultDecision, ...]:
        """Return immutable decisions only for activated exact matches."""
        if not isinstance(metadata, Mapping):
            raise TypeError("metadata must be a mapping")
        return tuple(FaultDecision(fault.fault_id, fault.fault_type, fault.parameters)
                     for fault in self._faults if fault.fault_id in self._activated
                     and all(metadata.get(key) == value for key, value in fault.match))

    def _decision(self, kind: str, metadata: Mapping[str, Any]) -> FaultDecision | None:
        return next((item for item in self.decisions_for(metadata)
                     if item.fault_type == kind), None)

    def result_plan(self, metadata: Mapping[str, Any], *, base_at_ms: int) -> dict[str, Any]:
        """Plan delivery without claiming provider success or changing world truth."""
        base = _time(base_at_ms, "base_at_ms")
        if base < self.clock.now():
            raise ValueError("result cannot be scheduled in the past")
        delay = sum(int(item.parameter_dict()["delay_ms"])
                    for kind in ("LATENCY", "LATE_RESULT")
                    if (item := self._decision(kind, metadata)) is not None)
        failure = self._decision("FAILURE", metadata)
        compensation = self._decision("COMPENSATION_FAILURE", metadata)
        timeout = self._decision("TIMEOUT", metadata)
        unknown = self._decision("UNKNOWN_OUTCOME", metadata)
        if sum(item is not None for item in (failure, compensation, timeout, unknown)) > 1:
            raise ValueError("conflicting terminal fault decisions")
        if timeout is not None:
            disposition = "TIMEOUT"
            params = timeout.parameter_dict()
        elif unknown is not None:
            disposition = "OUTCOME_UNKNOWN"
            params = unknown.parameter_dict()
        elif failure is not None or compensation is not None:
            params = (failure or compensation).parameter_dict()
            disposition = ("OUTCOME_UNKNOWN" if failure is not None
                           and not params["before_dispatch"] else "FAILURE")
        else:
            disposition = "DELIVER"
            params = {}
        # A result plan is a detached scenario instruction, not a provider fact.
        return {"at_ms": base + delay, "disposition": disposition,
                "parameters": dict(params), "retry_allowed": disposition == "DELIVER"}

    def schedule_result(
        self, metadata: Mapping[str, Any], *, base_at_ms: int,
        deliver: Callable[[dict[str, Any]], Any],
    ) -> ScheduleHandle:
        """Deliver the detached plan to the driver's canonical ingress hook."""
        plan = self.result_plan(metadata, base_at_ms=base_at_ms)
        return self.clock.schedule_at(plan["at_ms"], lambda: deliver(deepcopy(plan)))

    def cancellation_decision(self, metadata: Mapping[str, Any]) -> str:
        """Ignore leaves provider work running; no acknowledgement is invented."""
        return "IGNORE" if self._decision("IGNORE_CANCELLATION", metadata) else "DELEGATE"

    def schedule_commit_before_cancel(
        self, metadata: Mapping[str, Any], *, commit: Callable[[], Any],
        cancel: Callable[[], Any],
    ) -> tuple[ScheduleHandle, ScheduleHandle]:
        decision = self._decision("COMMIT_BEFORE_CANCEL", metadata)
        if decision is None:
            raise ValueError("commit-before-cancel fault is not active")
        params = decision.parameter_dict()
        commit_at = int(params["commit_at_ms"])
        cancel_at = int(params["cancel_at_ms"])
        if commit_at < self.clock.now():
            raise ValueError("race commit is in the past")
        return (self.clock.schedule_at(commit_at, commit),
                self.clock.schedule_at(cancel_at, cancel))

    def schedule_callbacks(
        self, metadata: Mapping[str, Any], *, at_ms: int,
        callback: Mapping[str, Any], ingress: Callable[[dict[str, Any]], Any],
        conflicting_callback: Mapping[str, Any] | None = None,
    ) -> tuple[ScheduleHandle, ...]:
        """Schedule duplicates with a stable callback identity for ingress dedupe."""
        at = _time(at_ms, "at_ms")
        if at < self.clock.now():
            raise ValueError("callback is in the past")
        original = deepcopy(dict(callback))
        identity = _text(original.get("callback_id"), "callback_id")
        decision = self._decision("DUPLICATE_CALLBACK", metadata)
        count = 1 if decision is None else int(decision.parameter_dict()["count"])
        identical = True if decision is None else bool(decision.parameter_dict()["identical"])
        if not identical:
            if conflicting_callback is None:
                raise ValueError("conflicting duplicate requires explicit alternate callback")
            alternate = deepcopy(dict(conflicting_callback))
            if alternate.get("callback_id") != identity or alternate == original:
                raise ValueError("conflict must retain callback identity and change content")
        else:
            if conflicting_callback is not None:
                raise ValueError("identical duplicate cannot have alternate content")
            alternate = original
        return tuple(self.clock.schedule_at(
            at, lambda item=deepcopy(original if index == 0 else alternate): ingress(deepcopy(item))
        ) for index in range(count))

    def retry_decision(self, metadata: Mapping[str, Any], *, key: str) -> dict[str, Any]:
        """Represent a scripted retry, never invoke one or override unknown safety."""
        decision = self._decision("DUPLICATE_RETRY", metadata)
        if decision is None:
            return {"repeat": False}
        disposition = self.result_plan(metadata, base_at_ms=self.clock.now())["disposition"]
        if disposition != "DELIVER":
            return {"repeat": False, "reason": (
                "AMBIGUOUS_WRITE" if disposition in {"TIMEOUT", "OUTCOME_UNKNOWN"}
                else "TERMINAL_FAILURE"
            )}
        params = decision.parameter_dict()
        if not params["provider_idempotency_supported"]:
            return {"repeat": False, "reason": "NO_PROVIDER_IDEMPOTENCY"}
        if not params["same_key"]:
            return {"repeat": False, "reason": "DIFFERENT_KEY"}
        original = _text(key, "idempotency_key")
        return {"repeat": True, "idempotency_key": original,
                "provider_idempotency_supported": params["provider_idempotency_supported"]}


__all__ = ["Fault", "FaultDecision", "FaultEngine"]
