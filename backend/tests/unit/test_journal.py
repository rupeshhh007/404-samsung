"""T-JRN-01: serialized acceptance, dedupe and sequence continuity."""

import asyncio

import pytest

from interlock.domain.enums import EventSource
from interlock.runtime.journal import DedupeConflictError, EventCandidate, EventJournal
from interlock.runtime.session import SessionRegistry


def _start() -> EventCandidate:
    return EventCandidate(event_type="SessionStarted", session_id="s",
                          source=EventSource.SYSTEM, payload={"mode": "TEST"},
                          dedupe_key="start")


def _input(index: int, key: str) -> EventCandidate:
    return EventCandidate(
        event_type="UserInputObserved", session_id="s", source=EventSource.USER,
        payload={"evidence_id": f"e-{index}", "modality": "TEXT",
                 "content_ref": f"input-{index}"}, dedupe_key=key,
    )


def test_t_jrn_01_identical_duplicate_and_conflict():
    async def run():
        journal = EventJournal(SessionRegistry())
        first = await journal.append(_start())
        original = await journal.append(_input(1, "input"))
        duplicate = await journal.append(_input(1, "input"))
        assert first.sequence == 1
        assert duplicate.event_id == original.event_id
        assert journal.get_last_sequence("s") == 2
        with pytest.raises(DedupeConflictError):
            await journal.append(_input(2, "input"))
        assert [event.sequence for event in journal.read_events("s")] == [1, 2]
    asyncio.run(run())


def test_t_jrn_01_parallel_acceptance_is_contiguous():
    async def run():
        journal = EventJournal(SessionRegistry())
        await journal.append(_start())
        accepted = await asyncio.gather(
            *(journal.append(_input(i, f"input-{i}")) for i in range(20))
        )
        assert sorted(event.sequence for event in accepted) == list(range(2, 22))
        assert [event.sequence for event in journal.read_events("s")] == list(range(1, 22))
    asyncio.run(run())
