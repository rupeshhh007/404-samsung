"""Deterministic execution of canonical INTERLOCK scenario definitions."""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Mapping
from copy import deepcopy
from typing import Any, Protocol, TypeAlias

from interlock.domain.models import ScenarioDefinition
from interlock.testing.clock import VirtualClock


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
        scenario: ScenarioDefinition | Mapping[str, Any],
        driver: ScenarioDriver,
        *,
        clock: VirtualClock | None = None,
    ) -> None:
        self._scenario = _snapshot_scenario(scenario)
        self._driver = driver
        self._clock = clock if clock is not None else VirtualClock()

    @property
    def clock(self) -> VirtualClock:
        """Expose the runner's logical clock for driver scheduling and inspection."""

        return self._clock

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


def _snapshot_scenario(
    scenario: ScenarioDefinition | Mapping[str, Any],
) -> ScenarioDefinition:
    """Validate and detach a caller-owned scenario for deterministic execution."""

    if isinstance(scenario, ScenarioDefinition):
        return scenario.model_copy(deep=True)
    if not isinstance(scenario, Mapping):
        raise TypeError("scenario must be a ScenarioDefinition or mapping")

    return ScenarioDefinition.model_validate(scenario, strict=True).model_copy(deep=True)


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
