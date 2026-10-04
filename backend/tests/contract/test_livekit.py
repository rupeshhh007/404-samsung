"""T-VOICE-01: deterministic, network-free LiveKit boundary contract."""

from __future__ import annotations

import asyncio
from importlib.metadata import version
from typing import Any, Callable

import pytest

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
    def __init__(self, *, auto_start: bool = True) -> None:
        self.interrupted = False
        self._done = asyncio.Event()
        self._started = asyncio.Event()
        if auto_start:
            self._started.set()

    def start(self) -> None:
        self._started.set()

    async def wait_for_start(self) -> None:
        await self._started.wait()

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
    def __init__(self, *, auto_start_speech: bool = True) -> None:
        self.auto_start_speech = auto_start_speech
        self.listeners: dict[str, list[Callable[[Any], None]]] = {}
        self.spoken: list[tuple[str, bool, bool]] = []
        self.handles: list[FakeSpeechHandle] = []
        self.closed = False
        self.agent_state = "idle"

    def on(self, event: str, callback: Callable[[Any], None] | None = None):
        def register(listener: Callable[[Any], None]):
            self.listeners.setdefault(event, []).append(listener)
            return listener

        return register(callback) if callback is not None else register

    def off(self, event: str, callback: Callable[[Any], None]) -> None:
        self.listeners.get(event, []).remove(callback)

    def say(self, text: str, *, allow_interruptions: bool, add_to_chat_ctx: bool):
        self.spoken.append((text, allow_interruptions, add_to_chat_ctx))
        handle = FakeSpeechHandle(auto_start=self.auto_start_speech)
        self.handles.append(handle)
        return handle

    @property
    def current_speech(self) -> FakeSpeechHandle | None:
        for handle in reversed(self.handles):
            if handle._started.is_set() and not handle.done():
                return handle
        return None

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


def test_emit_waits_for_livekit_start_signal_before_speech_emission_started() -> None:
    async def case() -> None:
        livekit = FakeAgentSession(auto_start_speech=False)
        adapter = LiveKitSessionAdapter(
            livekit,
            session_id="voice-start-test",
            application_factory=_factory(),
        )
        await adapter.start(logical_time=1)

        speech = SpeechAct(
            speech_id="speech-1",
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
            "speech_id": "speech-1",
            "rendered_text": "Starting task now...",
            "policy_id": "test-policy",
            "through_sequence": proposal.sequence,
            "claim_versions": {},
        })

        drain_task = asyncio.create_task(adapter.application.drain(adapter.session_id))
        await asyncio.sleep(0.05)

        # say() has returned and created a handle, but playout has NOT started yet
        assert len(livekit.spoken) == 1
        assert len(livekit.handles) == 1
        handle = livekit.handles[0]
        assert not drain_task.done()

        # SpeechEmissionStarted must NOT appear merely because say() returned
        events = adapter.application.events(adapter.session_id)
        assert not any(event.event_type == "SpeechEmissionStarted" for event in events)
        assert adapter.application.snapshot(adapter.session_id).speech["speech-1"].state == SpeechState.QUEUED

        # Playout start signal occurs
        handle.start()
        await asyncio.wait_for(drain_task, timeout=1.0)

        # Now SpeechEmissionStarted appears and state is EMITTING
        events = adapter.application.events(adapter.session_id)
        assert any(event.event_type == "SpeechEmissionStarted" for event in events)
        assert adapter.application.snapshot(adapter.session_id).speech["speech-1"].state == SpeechState.EMITTING

        # Complete playout cleanly and close
        handle.finish()
        await asyncio.sleep(0.01)
        await adapter.application.drain(adapter.session_id)
        await adapter.close()

    asyncio.run(case())


def test_active_speech_teardown_does_not_wedge_and_preserves_transport() -> None:
    async def case() -> None:
        adapter, livekit = await _adapter("active-teardown-1")
        await _queue_progress(adapter, text="Active speech playing...")
        assert "speech-1" in adapter._output_origins
        assert adapter.application.snapshot(adapter.session_id).speech["speech-1"].state == SpeechState.EMITTING

        # Teardown while active speech is unresolved must fail BEFORE irreversibly closing LiveKit
        with pytest.raises(RuntimeError, match="voice output terminal status is unresolved"):
            await adapter.close()

        # Transport and adapter state are NOT destroyed
        assert not livekit.closed
        assert not adapter._livekit_closed
        assert not adapter._closed
        assert adapter.session_id in adapter.application._sessions

        # Explicit truthful terminal observation via close(terminal_observations=...)
        final = await adapter.close(terminal_observations={"speech-1": False})

        # Now LiveKit is closed and INTERLOCK session is retired cleanly without wedging
        assert livekit.closed
        assert adapter._livekit_closed
        assert adapter._closed
        assert final.speech["speech-1"].state == SpeechState.CANCELLED

    asyncio.run(case())


def test_emit_start_timeout_fails_closed_unheard() -> None:
    async def case() -> None:
        livekit = FakeAgentSession(auto_start_speech=False)
        adapter = LiveKitSessionAdapter(
            livekit,
            session_id="voice-timeout-test",
            application_factory=_factory(),
        )
        adapter._start_timeout_s = 0.05
        await adapter.start(logical_time=1)

        speech = SpeechAct(
            speech_id="speech-1",
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
            "speech_id": "speech-1",
            "rendered_text": "Will timeout...",
            "policy_id": "test-policy",
            "through_sequence": proposal.sequence,
            "claim_versions": {},
        })

        await adapter.application.drain(adapter.session_id)

        # Output failed closed with heard=False
        events = adapter.application.events(adapter.session_id)
        failed_events = [e for e in events if e.event_type == "SpeechEmissionFailed"]
        assert len(failed_events) == 1
        assert failed_events[0].payload["heard"] is False
        assert failed_events[0].payload["error_code"] == "LIVEKIT_OUTPUT_START_TIMEOUT"
        assert adapter.application.snapshot(adapter.session_id).speech["speech-1"].state == SpeechState.CANCELLED

        await adapter.close()

    asyncio.run(case())


def test_unrelated_speaking_state_does_not_satisfy_interlock_start_waiter() -> None:
    async def case() -> None:
        livekit = FakeAgentSession(auto_start_speech=False)
        adapter = LiveKitSessionAdapter(
            livekit,
            session_id="voice-unrelated-speaking-test",
            application_factory=_factory(),
        )
        await adapter.start(logical_time=1)

        # 1. An unrelated speech is already active and speaking in LiveKit
        unrelated_handle = FakeSpeechHandle(auto_start=True)
        livekit.handles.append(unrelated_handle)
        livekit.agent_state = "speaking"
        assert livekit.current_speech is unrelated_handle

        # Trigger agent_state_changed event with new_state="speaking"
        for listener in livekit.listeners.get("agent_state_changed", []):
            listener(type("AgentStateChangedEvent", (), {"old_state": "idle", "new_state": "speaking"})())

        # 2. Queue an approved INTERLOCK speech
        speech = SpeechAct(
            speech_id="speech-interlock",
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
            "speech_id": "speech-interlock",
            "rendered_text": "Interlock speech text",
            "policy_id": "test-policy",
            "through_sequence": proposal.sequence,
            "claim_versions": {},
        })

        drain_task = asyncio.create_task(adapter.application.drain(adapter.session_id))
        await asyncio.sleep(0.05)

        # say() was called, creating an interlock handle that has NOT started
        assert len(livekit.handles) == 2
        interlock_handle = livekit.handles[1]
        assert interlock_handle is not unrelated_handle
        assert not drain_task.done()

        # The unrelated speaking state must NOT satisfy the INTERLOCK speech start waiter
        events = adapter.application.events(adapter.session_id)
        assert not any(event.event_type == "SpeechEmissionStarted" for event in events)
        assert adapter.application.snapshot(adapter.session_id).speech["speech-interlock"].state == SpeechState.QUEUED

        # 3. Unrelated speech finishes playout
        unrelated_handle.finish()

        # 4. INTERLOCK speech handle now starts
        interlock_handle.start()
        await asyncio.wait_for(drain_task, timeout=1.0)

        # Now SpeechEmissionStarted appears
        events = adapter.application.events(adapter.session_id)
        assert any(event.event_type == "SpeechEmissionStarted" for event in events)
        assert adapter.application.snapshot(adapter.session_id).speech["speech-interlock"].state == SpeechState.EMITTING

        # Complete playout and teardown cleanly
        interlock_handle.finish()
        await asyncio.sleep(0.01)
        await adapter.application.drain(adapter.session_id)
        assert adapter.application.snapshot(adapter.session_id).speech["speech-interlock"].state == SpeechState.EMITTED
        await adapter.close()

    asyncio.run(case())


def test_early_successful_playout_without_start_signal_does_not_fail_unheard() -> None:
    async def case() -> None:
        livekit = FakeAgentSession(auto_start_speech=False)
        adapter = LiveKitSessionAdapter(
            livekit,
            session_id="voice-early-playout-test",
            application_factory=_factory(),
        )
        await adapter.start(logical_time=1)

        speech = SpeechAct(
            speech_id="speech-early",
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
            "speech_id": "speech-early",
            "rendered_text": "Early playout test",
            "policy_id": "test-policy",
            "through_sequence": proposal.sequence,
            "claim_versions": {},
        })

        drain_task = asyncio.create_task(adapter.application.drain(adapter.session_id))
        await asyncio.sleep(0.05)

        handle = livekit.handles[0]
        # Playout finishes cleanly without an explicit handle.start() callback
        handle.finish()
        await asyncio.wait_for(drain_task, timeout=1.0)

        # Successful playout proves speech started and finished; it must NOT fail with heard=False
        events = adapter.application.events(adapter.session_id)
        assert not any(event.event_type == "SpeechEmissionFailed" for event in events)
        assert any(event.event_type == "SpeechEmissionStarted" for event in events)
        assert any(
            event.event_type == "SpeechEmissionFinished" and event.payload["heard"] is True
            for event in events
        )
        assert adapter.application.snapshot(adapter.session_id).speech["speech-early"].state == SpeechState.EMITTED
        await adapter.close()

    asyncio.run(case())
