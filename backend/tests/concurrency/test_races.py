"""T-CON-01, T-CON-02 and I11: simultaneous ingress has one legal order."""

import asyncio

from interlock.domain.enums import EventSource, RuntimeMode
from interlock.runtime.journal import EventCandidate, EventJournal
from interlock.runtime.reducer import Reducer
from interlock.runtime.session import SessionRegistry


def test_t_con_01_t_con_02_t_inv_i11_p_t_inv_i11_n_contiguous_acceptance_and_replay():
    async def run():
        journal = EventJournal(SessionRegistry())
        await journal.append(EventCandidate(
            session_id="s", event_type="SessionStarted",
            source=EventSource.SYSTEM, payload={"mode": "TEST"},
        ))
        accepted = await asyncio.gather(*(
            journal.append(EventCandidate(
                session_id="s", event_type="UserInputObserved",
                source=EventSource.USER,
                payload={"evidence_id": f"e-{index}", "modality": "TEXT",
                         "content_ref": f"input-{index}"},
                dedupe_key=f"input-{index}",
            )) for index in range(20)
        ))
        assert len({event.event_id for event in accepted}) == 20
        events = journal.read_events("s")
        assert [event.sequence for event in events] == list(range(1, 22))
        state = None
        for event in events:
            state, commands = Reducer.reduce(state, event, mode=RuntimeMode.REPLAY)
            assert commands == []
        assert state.last_sequence == 21
    asyncio.run(run())
