"""Deterministic virtual time for INTERLOCK scenario execution."""

from __future__ import annotations

import heapq
import inspect
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, TypeAlias


ScheduledCallback: TypeAlias = Callable[[], Awaitable[Any] | Any]


@dataclass(frozen=True, slots=True)
class ScheduleHandle:
    """Deterministic identity and timing metadata for scheduled work."""

    scheduled_time_ms: int
    declaration_index: int


class VirtualClock:
    """A monotonic logical clock that executes callbacks in canonical order."""

    def __init__(self) -> None:
        self._current_time_ms = 0
        self._next_declaration_index = 0
        self._scheduled: list[tuple[int, int, ScheduledCallback]] = []

    def now(self) -> int:
        """Return the current logical time in milliseconds from session start."""

        return self._current_time_ms

    @property
    def pending_count(self) -> int:
        """Return the number of scheduled callbacks pending execution."""

        return len(self._scheduled)

    def schedule(
        self,
        delay_ms: int,
        callback: ScheduledCallback,
    ) -> ScheduleHandle:
        """Schedule a callback after a non-negative duration from current time."""

        delay = _require_logical_time(delay_ms, name="delay_ms")
        return self.schedule_at(self._current_time_ms + delay, callback)

    def schedule_at(
        self,
        at_ms: int,
        callback: ScheduledCallback,
    ) -> ScheduleHandle:
        """Schedule a callback at an absolute, non-retrograde logical time."""

        scheduled_time = _require_logical_time(at_ms, name="at_ms")
        if scheduled_time < self._current_time_ms:
            raise ValueError(
                "at_ms cannot be earlier than the current logical time "
                f"({scheduled_time} < {self._current_time_ms})"
            )
        if not callable(callback):
            raise TypeError("callback must be callable")

        declaration_index = self._next_declaration_index
        self._next_declaration_index += 1
        heapq.heappush(
            self._scheduled,
            (scheduled_time, declaration_index, callback),
        )
        return ScheduleHandle(
            scheduled_time_ms=scheduled_time,
            declaration_index=declaration_index,
        )

    def cancel(self, handle: ScheduleHandle) -> bool:
        """Cancel a scheduled callback by its handle if not yet executed."""

        for i, (time_ms, decl_idx, _) in enumerate(self._scheduled):
            if time_ms == handle.scheduled_time_ms and decl_idx == handle.declaration_index:
                self._scheduled.pop(i)
                heapq.heapify(self._scheduled)
                return True
        return False

    async def advance_to(self, target_ms: int) -> None:
        """Advance to an absolute time, draining all work due through it."""

        target = _require_logical_time(target_ms, name="target_ms")
        if target < self._current_time_ms:
            raise ValueError(
                "target_ms cannot be earlier than the current logical time "
                f"({target} < {self._current_time_ms})"
            )

        while self._scheduled and self._scheduled[0][0] <= target:
            scheduled_time, _, callback = heapq.heappop(self._scheduled)
            self._current_time_ms = scheduled_time
            result = callback()
            if inspect.isawaitable(result):
                await result

        self._current_time_ms = target

    async def advance(self, duration_ms: int) -> None:
        """Advance by a non-negative duration from the current logical time."""

        duration = _require_logical_time(duration_ms, name="duration_ms")
        await self.advance_to(self._current_time_ms + duration)


Clock: TypeAlias = VirtualClock


def _require_logical_time(value: object, *, name: str) -> int:
    """Return a strict non-negative integer logical time."""

    if type(value) is not int:
        raise TypeError(f"{name} must be an integer")
    if value < 0:
        raise ValueError(f"{name} must be non-negative")
    return value


__all__ = [
    "Clock",
    "ScheduleHandle",
    "ScheduledCallback",
    "VirtualClock",
]
