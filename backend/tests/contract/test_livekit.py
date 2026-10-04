"""T-VOICE-01: deterministic, network-free LiveKit boundary contract."""

from __future__ import annotations

import asyncio
from importlib.metadata import version
from typing import Any, Callable

from interlock.adapters.livekit_agent import LiveKitSessionAdapter
from interlock.config import Settings
from interlock.domain.enums import (
    Authorization,
    ClaimCertainty,
    EventSource,
    IntentMaturity,
    SpeechActType,
    SpeechState,
)
from interlock.domain.models import IntentRevision, SpeechAct
from interlock.main import Application, RuntimeDependencies
from interlock.runtime.journal import EventCandidate


def test_verified_livekit_agents_version_is_installed() -> None:
    assert version("livekit-agents") == "1.8.4"


class FakeSpeechHandle:
    def __init__(self) -> None:
        self.interrupted = False
        self._done = asyncio.Event()

    def done(self) -> bool:
        return self._done.is_set()

    def interrupt(self, *, force: bool = False, source: str = "programmatic") -> "FakeSpeechHandle":
        del force, source
        self.interrupted = True
        self._done.set()
        return self

    async def wait_for_playout(self) -> None:
        await self._done.wait()

    def exception(self) -> None:
        return None

    def finish(self) -> None:
        self._done.set()


class FakeAgentSession:
    def __init__(self) -> None:
        self.listeners: dict[str, list[Callable[[Any], None]]] = {}
        self.spoken: list[tuple[str, bool, bool]] = []
        self.handles: list[FakeSpeechHandle] = []
        self.closed = False

    def on(self, event: str, callback: Callable[[Any], None] | None = None):
        def register(listener: Callable[[Any], None]):
            self.listeners.setdefault(event, []).append(listener)
            return listener

        return register(callback) if callback is not None else register

    def off(self, event: str, callback: Callable[[Any], None]) -> None:
        self.listeners.get(event, []).remove(callback)

    def say(self, text: str, *, allow_interruptions: bool, add_to_chat_ctx: bool):
        self.spoken.append((text, allow_interruptions, add_to_chat_ctx))
        handle = FakeSpeechHandle()
        self.handles.append(handle)
        return handle

    async def aclose(self) -> None:
        self.closed = True


def _factory(
    *, input_context: Callable[..., dict[str, Any]] | None = None
) -> Callable[[Any], Application]:
    def build(output: Any) -> Application:
        return Application(
            settings=Settings(INTERLOCK_MODE="TEST"),
            dependencies=RuntimeDependencies(
                output=output,
                input_context=input_context,
            ),
        )

    return build


async def _adapter(
    session_id: str = "voice-1",
    *,
    input_context: Callable[..., dict[str, Any]] | None = None,
) -> tuple[LiveKitSessionAdapter, FakeAgentSession]:
    livekit = FakeAgentSession()
    adapter = LiveKitSessionAdapter(
        livekit,
        session_id=session_id,
        application_factory=_factory(input_context=input_context),
    )
    await adapter.start(logical_time=1)
    return adapter, livekit


async def _append(adapter: LiveKitSessionAdapter, event_type: str, payload: dict[str, Any]):
    return await adapter.application.append(EventCandidate(
        session_id=adapter.session_id,
        event_type=event_type,
        source=EventSource.POLICY,
        payload=payload,
        correlation_id=adapter.session_id,
    ))


async def _queue_progress(
    adapter: LiveKitSessionAdapter,
    *,
    speech_id: str = "speech-1",
    text: str = "I am checking that now.",
) -> None:
    speech = SpeechAct(
        speech_id=speech_id,
        act_type=SpeechActType.PROGRESS,
        template_id="tmpl_progress",
        requested_certainty=ClaimCertainty.PROGRESS,
        state=SpeechState.PROPOSED,
        created_by_event_id="test",
    )
    proposal = await _append(
        adapter, "SpeechActProposed", {"speech_act": speech.model_dump(mode="json")}
    )
    await _append(adapter, "SpeechActApproved", {
        "speech_id": speech_id,
        "rendered_text": text,
        "policy_id": "test-policy",
        "through_sequence": proposal.sequence,
        "claim_versions": {},
    })
    await adapter.application.drain(adapter.session_id)


def test_partial_transcript_is_provisional_and_dispatches_no_write() -> None:
    async def case() -> None:
        adapter, _ = await _adapter()
        await adapter.accept_transcript(
            transcript="pause", final=False, item_id="turn-1", created_at=1.0
        )
        await adapter.application.drain(adapter.session_id)
        events = adapter.application.events(adapter.session_id)
        assert any(
            event.event_type == "TranscriptHypothesisObserved"
            and event.payload["final"] is False
            for event in events
        )
        assert not any(event.event_type == "ToolDispatchRequested" for event in events)
        assert not adapter.application.snapshot(adapter.session_id).operations
        await adapter.close()

    asyncio.run(case())


def test_final_correction_commits_active_arguments_once() -> None:
    async def case() -> None:
        def context(state, evidence):
            del state, evidence
            return {"correction_field": "slot", "value_aliases": {"12:00": "12:00"}}

        adapter, _ = await _adapter(input_context=context)
        revision = IntentRevision(
            revision_id="revision-1",
            intent_id="intent-1",
            values={"goal_type": "booking", "slot": "11:00"},
            maturity=IntentMaturity.COMMITTED,
            authorization=Authorization.NOT_REQUESTED,
            created_by_event_id="seed",
            dependency_fingerprint="seed-fingerprint",
        )
        await _append(
            adapter,
            "IntentRevisionCommitted",
            {"revision": revision.model_dump(mode="json")},
        )
        first = await adapter.accept_transcript(
            transcript="actually make it 12:00",
            final=True,
            item_id="turn-2",
            created_at=2.0,
        )
        duplicate = await adapter.accept_transcript(
            transcript="actually make it 12:00",
            final=True,
            item_id="turn-2",
            created_at=2.0,
        )
        await adapter.application.drain(adapter.session_id)
        state = adapter.application.snapshot(adapter.session_id)
        active = state.revisions[state.intents["intent-1"].active_revision_id]
        assert first.event_id == duplicate.event_id
        assert active.values["slot"] == "12:00"
        assert len(state.intents["intent-1"].revisions) == 2
        await adapter.close()

    asyncio.run(case())


def test_filler_and_false_start_do_not_manufacture_authorization() -> None:
    async def case() -> None:
        adapter, _ = await _adapter()
        await adapter.accept_transcript(
            transcript="I, uh", final=False, item_id="false-start", created_at=2.5
        )
        await adapter.accept_transcript(
            transcript="uh huh", final=True, item_id="filler", created_at=3.0
        )
        await adapter.application.drain(adapter.session_id)
        events = adapter.application.events(adapter.session_id)
        assert not any(
            event.event_type in {
                "IntentAuthorizationChanged",
                "ReconciliationAuthorized",
                "ToolDispatchRequested",
            }
            for event in events
        )
        await adapter.close()

    asyncio.run(case())


def test_barge_in_cancels_speech_without_cancelling_slow_work() -> None:
    async def case() -> None:
        adapter, livekit = await _adapter()
        slow_work = asyncio.create_task(asyncio.Event().wait())
        await _queue_progress(adapter)
        accepted = await adapter.request_barge_in()
        await adapter.application.drain(adapter.session_id)
        assert accepted and livekit.handles[0].interrupted
        assert not slow_work.done()
        assert not any(
            event.event_type == "CancellationRequested"
            for event in adapter.application.events(adapter.session_id)
        )
        assert not any(
            event.event_type == "SpeechEmissionFinished"
            for event in adapter.application.events(adapter.session_id)
        )
        await adapter.output_failed(
            speech_id="speech-1",
            error_code="LIVEKIT_INTERRUPTED",
            heard=False,
        )
        slow_work.cancel()
        await asyncio.gather(slow_work, return_exceptions=True)
        await adapter.close()

    asyncio.run(case())


def test_approved_output_is_exact_and_safe_progress_precedes_slow_completion() -> None:
    async def case() -> None:
        adapter, livekit = await _adapter()
        slow_work = asyncio.create_task(asyncio.Event().wait())
        await _queue_progress(adapter, text="I am checking availability now.")
        assert livekit.spoken == [
            ("I am checking availability now.", True, False)
        ]
        assert not slow_work.done()
        assert "booked" not in livekit.spoken[0][0].lower()
        livekit.handles[0].finish()
        await asyncio.sleep(0)
        await adapter.application.drain(adapter.session_id)
        slow_work.cancel()
        await asyncio.gather(slow_work, return_exceptions=True)
        await adapter.close()

    asyncio.run(case())


def test_new_input_remains_responsive_while_background_work_is_pending() -> None:
    async def case() -> None:
        adapter, _ = await _adapter()
        pending = asyncio.create_task(asyncio.Event().wait())
        event = await asyncio.wait_for(
            adapter.accept_transcript(
                transcript="okay", final=True, item_id="responsive", created_at=4.0
            ),
            timeout=0.2,
        )
        assert event.event_type == "TranscriptHypothesisObserved"
        assert not pending.done()
        pending.cancel()
        await asyncio.gather(pending, return_exceptions=True)
        await adapter.application.drain(adapter.session_id)
        await adapter.close()

    asyncio.run(case())


def test_teardown_quiesces_and_next_conversation_is_fresh() -> None:
    async def case() -> None:
        first, first_livekit = await _adapter("conversation-1")
        await first.accept_transcript(
            transcript="okay", final=True, item_id="first", created_at=5.0
        )
        await first.application.drain(first.session_id)
        await first.close()
        assert first_livekit.closed
        assert not first._tasks

        second, _ = await _adapter("conversation-2")
        state = second.application.snapshot(second.session_id)
        assert state.last_sequence == 1
        assert not state.evidence and not state.intents and not state.operations
        assert second.application is not first.application
        await second.close()

    asyncio.run(case())


def test_measurements_only_report_observed_samples() -> None:
    async def case() -> None:
        adapter, _ = await _adapter()
        assert adapter.measurements() == {}
        await adapter.accept_transcript(
            transcript="okay", final=True, item_id="measured", created_at=6.0
        )
        measurements = adapter.measurements()
        assert set(measurements) == {"transcript_accept"}
        assert len(measurements["transcript_accept"]) == 1
        assert measurements["transcript_accept"][0] >= 0
        await adapter.application.drain(adapter.session_id)
        await adapter.close()

    asyncio.run(case())
