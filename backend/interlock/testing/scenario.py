"""Deterministic execution of canonical INTERLOCK scenario definitions."""

from __future__ import annotations

import inspect
import json
from collections.abc import Awaitable, Mapping
from copy import deepcopy
from typing import Any, Protocol, TypeAlias

from interlock.domain.models import ScenarioDefinition, ScenarioStep
from interlock.testing.clock import Clock, VirtualClock


HookResult: TypeAlias = Awaitable[None] | None


class ScenarioDriver(Protocol):
    """Injected boundary for runtime orchestration and scenario assertions."""

    def setup(
        self,
        scenario: ScenarioDefinition,
        clock: VirtualClock,
    ) -> HookResult:
        """Configure the runtime from a detached complete scenario snapshot."""

    def deliver_input(
        self,
        input_payload: Mapping[str, Any],
        clock: VirtualClock,
    ) -> HookResult:
        """Deliver opaque input at the clock's current logical time."""

    def assert_checkpoint(
        self,
        assertion: Mapping[str, Any],
        clock: VirtualClock,
    ) -> HookResult:
        """Evaluate one checkpoint after current-time work has drained."""

    def assert_final(
        self,
        expectation: Mapping[str, Any],
        clock: VirtualClock,
    ) -> HookResult:
        """Evaluate final expectations without advancing into future work."""


class ScenarioRunner:
    """Run canonical scenario steps against an injected driver and virtual clock."""

    def __init__(
        self,
        scenario: ScenarioDefinition | Mapping[str, Any] | str,
        driver: ScenarioDriver,
        *,
        clock: VirtualClock | None = None,
    ) -> None:
        self._scenario = parse_scenario(scenario)
        self._driver = driver
        self._clock = clock if clock is not None else VirtualClock()

    @property
    def clock(self) -> VirtualClock:
        """Expose the runner's logical clock for driver scheduling and inspection."""

        return self._clock

    @property
    def scenario(self) -> ScenarioDefinition:
        """Expose an isolated copy of the parsed scenario definition."""

        return self._scenario.model_copy(deep=True)

    async def run(self) -> None:
        """Execute steps in declaration order and evaluate the final expectation."""

        scenario = self._scenario.model_copy(deep=True)
        await _await_hook(
            self._driver.setup(scenario.model_copy(deep=True), self._clock)
        )

        for step in scenario.steps:
            if step.input is not None:
                self._schedule_input(step.input)
            elif step.advance_to is not None:
                await self._clock.advance_to(step.advance_to)
            else:
                await self._clock.advance_to(self._clock.now())
                await _await_hook(
                    self._driver.assert_checkpoint(
                        deepcopy(step.assert_),
                        self._clock,
                    )
                )

        await self._clock.advance_to(self._clock.now())
        await _await_hook(
            self._driver.assert_final(deepcopy(scenario.expect), self._clock)
        )

    def _schedule_input(self, input_step: Mapping[str, Any]) -> None:
        """Validate and schedule one opaque timed input."""

        if "at_ms" not in input_step:
            raise ValueError("input step must define at_ms")
        at_ms = _require_logical_time(input_step["at_ms"], name="input.at_ms")
        payload = deepcopy(
            {key: value for key, value in input_step.items() if key != "at_ms"}
        )

        async def deliver_input() -> None:
            await _await_hook(
                self._driver.deliver_input(deepcopy(payload), self._clock)
            )

        self._clock.schedule_at(at_ms, deliver_input)


def parse_scenario(
    source: ScenarioDefinition | Mapping[str, Any] | str,
) -> ScenarioDefinition:
    """Parse, strictly validate, and detach a canonical ScenarioDefinition."""

    if isinstance(source, ScenarioDefinition):
        scenario = source.model_copy(deep=True)
    elif isinstance(source, str):
        raw = _parse_scenario_string(source)
        if not isinstance(raw, Mapping):
            raise TypeError("scenario data must be a mapping")
        scenario = ScenarioDefinition.model_validate(raw, strict=True)
    elif isinstance(source, Mapping):
        raw = deepcopy(dict(source))
        scenario = ScenarioDefinition.model_validate(raw, strict=True)
    else:
        raise TypeError("scenario must be a ScenarioDefinition, mapping, or string")

    _validate_scenario_semantics(scenario)
    return scenario.model_copy(deep=True)


def _parse_scenario_string(text: str) -> Any:
    """Parse JSON string into a scenario mapping."""

    try:
        return json.loads(text)
    except json.JSONDecodeError as json_err:
        raise ValueError(
            f"Failed to parse scenario JSON string: {json_err}"
        ) from json_err


def _validate_scenario_semantics(scenario: ScenarioDefinition) -> None:
    """Validate canonical DSL rules for expectations and step time monotonicity."""

    if not scenario.expect or not isinstance(scenario.expect, Mapping):
        raise ValueError("ScenarioDefinition must define a non-empty expect mapping")

    timeline_ms = 0
    for idx, step in enumerate(scenario.steps):
        if step.input is not None:
            if "at_ms" not in step.input:
                raise ValueError(f"Step {idx}: input step must define at_ms")
            at_ms = _require_logical_time(step.input["at_ms"], name=f"steps[{idx}].input.at_ms")
            if at_ms < timeline_ms:
                raise ValueError(
                    f"Step {idx}: retrograde input at_ms ({at_ms} < {timeline_ms})"
                )
            timeline_ms = at_ms
        elif step.advance_to is not None:
            advance_to = _require_logical_time(
                step.advance_to, name=f"steps[{idx}].advance_to"
            )
            if advance_to < timeline_ms:
                raise ValueError(
                    f"Step {idx}: retrograde advance_to ({advance_to} < {timeline_ms})"
                )
            timeline_ms = advance_to
        elif step.assert_ is not None:
            if not isinstance(step.assert_, Mapping) or len(step.assert_) == 0:
                raise ValueError(f"Step {idx}: assert checkpoint must be a non-empty mapping")


async def _await_hook(result: HookResult) -> None:
    """Await async hooks while permitting simple synchronous test drivers."""

    if inspect.isawaitable(result):
        await result


def _require_logical_time(value: object, *, name: str) -> int:
    """Return a strict non-negative integer logical time."""

    if type(value) is not int:
        raise TypeError(f"{name} must be an integer")
    if value < 0:
        raise ValueError(f"{name} must be non-negative")
    return value


__all__ = [
    "Clock",
    "HookResult",
    "ScenarioDefinition",
    "ScenarioDriver",
    "ScenarioRunner",
    "ScenarioStep",
    "VirtualClock",
    "parse_scenario",
]
