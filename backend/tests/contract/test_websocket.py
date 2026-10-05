"""T-WS-01: projection stream cursor, dedupe, gap and reconnect."""

import asyncio
from datetime import datetime, timezone

from interlock.adapters.websocket import ProjectionHub
from interlock.domain.enums import EventSource
from interlock.domain.models import EventEnvelope, SessionState


_NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _event(sequence):
    return EventEnvelope(
        event_id=f"event-{sequence}", session_id="s", sequence=sequence,
        event_type="SessionStarted" if sequence == 1 else "UserInputObserved",
        source=EventSource.SYSTEM, occurred_at=_NOW, logical_time=sequence,
        payload={"mode": "TEST"} if sequence == 1 else {
            "evidence_id": f"e-{sequence}", "modality": "TEXT", "content_ref": "input"},
    )


def test_t_ws_01_snapshot_delta_duplicate_gap_and_reconnect():
    async def run():
        class ApplicationView:
            state = SessionState(session_id="s", last_sequence=1)

            def snapshot(self, session_id):
                assert session_id == "s"
                return self.state.model_copy(deep=True)

        application = ApplicationView()
        hub = ProjectionHub()
        hub.bind(application)
        try:
            assert await hub.publish(_event(1), application.state)
            subscriber = await hub.subscribe("s")
            snapshot = await subscriber.receive()
            assert snapshot["type"] == "snapshot"
            assert snapshot["through_sequence"] == 1
            application.state = SessionState(session_id="s", last_sequence=2)
            assert await hub.publish(_event(2), application.state)
            assert (await subscriber.receive())["sequence"] == 2
            assert not await hub.publish(_event(2), application.state)
            reconnect = await hub.subscribe("s", after_sequence=1)
            assert (await reconnect.receive())["sequence"] == 2
            gap = SessionState(session_id="s", last_sequence=4)
            assert not await hub.publish(_event(4), gap)
            assert (await subscriber.receive())["type"] == "resync_required"
            await hub.unsubscribe(subscriber)
            await hub.unsubscribe(reconnect)
        finally:
            await hub.shutdown()
    asyncio.run(run())
