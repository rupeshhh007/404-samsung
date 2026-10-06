"""T-VOICE-01: deterministic, network-free LiveKit boundary contract."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from importlib.metadata import version
from typing import Any, Callable

import pytest

from interlock.adapters.livekit_agent import (
    LiveKitSessionAdapter, VoiceProviders, compose_voice_room, run_livekit_voice_agent,
)
from interlock.config import Settings
from interlock.domain.enums import (
    Authorization,
    ClaimCertainty,
    ClaimState,
    EventSource,
    IntentMaturity,
    SpeechActType,
    SpeechState,
    RuntimeMode,
)
from interlock.domain.models import ClaimRecord, EventEnvelope, IntentRevision, SessionState, SpeechAct
from interlock.main import Application, RuntimeDependencies
from interlock.runtime.commands import RequestSpeechCorrection
from interlock.runtime.journal import EventCandidate
from interlock.runtime.reducer import Reducer
from interlock.truth.speech import CorrectionPolicy, validate_correction_proposal


def test_verified_livekit_agents_version_is_installed() -> None:
    assert version("livekit-agents") == "1.8.4"


def test_normal_voice_composition_is_isolated_and_has_no_livekit_llm_or_tools(monkeypatch: Any) -> None:
    import interlock.adapters.livekit_agent as voice

    sessions: list[Any] = []
    agents: list[Any] = []

    def session_factory(**kwargs: Any) -> Any:
        sessions.append(kwargs)
        return FakeAgentSession()

    def agent_factory(**kwargs: Any) -> Any:
        agents.append(kwargs)
        return object()

    monkeypatch.setattr(voice, "AgentSession", session_factory)
    monkeypatch.setattr(voice, "Agent", agent_factory)
    stt, tts = object(), object()
    providers = VoiceProviders(stt=stt, tts=tts, dependencies=RuntimeDependencies())
    settings = Settings(INTERLOCK_MODE="TEST")
    first_session, first_adapter, first_agent = compose_voice_room("room-1", providers, settings=settings)
    second_session, second_adapter, second_agent = compose_voice_room("room-2", providers, settings=settings)

    assert first_session is not second_session
    assert first_adapter.application is not second_adapter.application
    assert first_adapter.session_id == "room-1"
    assert second_adapter.session_id == "room-2"
    assert first_adapter.application.dependencies.output is first_adapter
    assert second_adapter.application.dependencies.output is second_adapter
    assert first_agent is not second_agent
    assert all(item == {"stt": stt, "tts": tts, "vad": None, "llm": None} for item in sessions)
    assert all(item["llm"] is None and item["tools"] == [] for item in agents)


def test_normal_voice_worker_fails_closed_without_transport_config(monkeypatch: Any) -> None:
    for name in ("LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(RuntimeError, match="LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET"):
        run_livekit_voice_agent(lambda _ctx: VoiceProviders(object(), object(), RuntimeDependencies()),
                                settings=Settings(INTERLOCK_MODE="LIVE"))
    with pytest.raises(ValueError, match="explicit STT and TTS"):
        compose_voice_room("room", VoiceProviders(None, object(), RuntimeDependencies()),
                           settings=Settings(INTERLOCK_MODE="TEST"))


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
            created_at=2.1,
        )
        await adapter.application.drain(adapter.session_id)
        state = adapter.application.snapshot(adapter.session_id)
        active = state.revisions[state.intents["intent-1"].active_revision_id]
        assert first.event_id == duplicate.event_id
        assert active.values["slot"] == "12:00"
        assert len(state.intents["intent-1"].revisions) == 2
        await adapter.close()

    asyncio.run(case())


def test_evolving_partials_keep_original_text_and_one_final_identity() -> None:
    async def case() -> None:
        adapter, livekit = await _adapter()
        first = await adapter.accept_transcript(
            transcript="book eleven", final=False, item_id="utterance-1", created_at=1.0,
        )
        repeated = await adapter.accept_transcript(
            transcript="book eleven", final=False, item_id="utterance-1", created_at=1.1,
        )
        corrected = await adapter.accept_transcript(
            transcript="book twelve", final=False, item_id="utterance-1", created_at=1.2,
        )
        final = await adapter.accept_transcript(
            transcript="book twelve please", final=True, item_id="utterance-1", created_at=1.3,
        )
        duplicate_final = await adapter.accept_transcript(
            transcript="book twelve please", final=True, item_id="utterance-1", created_at=1.4,
        )
        await adapter.application.drain(adapter.session_id)
        assert repeated.event_id == first.event_id
        assert duplicate_final.event_id == final.event_id
        events = [event for event in adapter.application.events(adapter.session_id)
                  if event.event_type == "TranscriptHypothesisObserved"]
        assert [(event.payload["text"], event.payload["final"]) for event in events] == [
            ("book eleven", False), ("book twelve", False),
            ("book twelve please", True),
        ]
        assert len({event.payload["evidence_id"] for event in events}) == 3
        assert not any(event.event_type in {"IntentAuthorizationChanged", "ToolDispatchRequested"}
                       for event in adapter.application.events(adapter.session_id))
        for _ in range(4):
            if not adapter._output_origins:
                break
            for handle in livekit.handles:
                handle.finish()
            await asyncio.sleep(0)
            await adapter.application.drain(adapter.session_id)
        await adapter.close()
    asyncio.run(case())


def test_empty_transcript_is_not_journaled_or_fatal_to_live_intake() -> None:
    async def case() -> None:
        adapter, livekit = await _adapter()
        with pytest.raises(ValueError, match="speech text"):
            await adapter.accept_transcript(transcript=" \t ", final=True, item_id="empty")
        listener = livekit.listeners["user_input_transcribed"][0]
        listener(type("TranscriptEvent", (), {
            "transcript": "  ", "is_final": True, "item_id": "empty", "created_at": 1.0,
        })())
        assert adapter.application.snapshot(adapter.session_id).last_sequence == 1
        assert adapter.callback_failures() == ()
        assert adapter._accepting
        accepted = await adapter.accept_transcript(
            transcript="okay", final=True, item_id="next", created_at=2.0,
        )
        assert accepted.event_type == "TranscriptHypothesisObserved"
        await adapter.application.drain(adapter.session_id)
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
        repeated = await adapter.request_barge_in()
        await adapter.application.drain(adapter.session_id)
        assert accepted and livekit.handles[0].interrupted
        assert repeated and repeated[0].event_id == accepted[0].event_id
        assert len([event for event in adapter.application.events(adapter.session_id)
                    if event.event_type == "SpeechCancellationRequested"]) == 1
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


def test_ambiguous_playout_failure_neither_invents_unheard_nor_retries() -> None:
    async def case() -> None:
        class FailedHandle(FakeSpeechHandle):
            async def wait_for_playout(self) -> None:
                await self._done.wait()
                raise RuntimeError("transport status is ambiguous")

            def exception(self) -> RuntimeError:
                return RuntimeError("transport status is ambiguous")

        class FailedSession(FakeAgentSession):
            def say(self, text: str, *, allow_interruptions: bool, add_to_chat_ctx: bool):
                self.spoken.append((text, allow_interruptions, add_to_chat_ctx))
                handle = FailedHandle()
                self.handles.append(handle)
                return handle

        livekit = FailedSession()
        adapter = LiveKitSessionAdapter(
            livekit, session_id="ambiguous-output", application_factory=_factory(),
        )
        await adapter.start()
        await _queue_progress(adapter)
        livekit.handles[0].finish()
        await asyncio.sleep(0)
        await adapter.application.drain(adapter.session_id)
        assert len(livekit.spoken) == 1
        assert not any(event.event_type in {"SpeechEmissionFinished", "SpeechEmissionFailed"}
                       for event in adapter.application.events(adapter.session_id))
        with pytest.raises(RuntimeError, match="terminal status is unresolved"):
            await adapter.close()
        await adapter.output_failed(
            speech_id="speech-1", error_code="LIVEKIT_OBSERVED_FAILURE", heard=True,
        )
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


def test_livekit_speaks_exact_persisted_truthlock_text() -> None:
    async def case() -> None:
        adapter, livekit = await _adapter()
        speech = SpeechAct(
            speech_id="truthlock-progress", act_type=SpeechActType.PROGRESS,
            template_id="tmpl_checking", requested_certainty=ClaimCertainty.PROGRESS,
            state=SpeechState.PROPOSED, created_by_event_id="test",
        )
        await _append(adapter, "SpeechActProposed", {
            "speech_act": speech.model_dump(mode="json"),
        })
        await adapter.application.drain(adapter.session_id)
        persisted = adapter.application.snapshot(adapter.session_id).speech[speech.speech_id]
        assert persisted.approved_policy_id == "truthlock.v1"
        assert persisted.rendered_text
        assert livekit.spoken == [(persisted.rendered_text, True, False)]
        assert [event.event_type for event in adapter.application.events(adapter.session_id)
                if event.payload.get("speech_id") == speech.speech_id][-3:] == [
                    "SpeechActApproved", "SpeechQueued", "SpeechEmissionStarted",
                ]
        livekit.handles[0].finish()
        await asyncio.sleep(0)
        await adapter.application.drain(adapter.session_id)
        assert adapter.application.snapshot(adapter.session_id).speech[speech.speech_id].heard is True
        await adapter.close()
    asyncio.run(case())


def test_heard_claim_invalidation_preserves_history_and_proposes_truth_gated_correction() -> None:
    claim = ClaimRecord(
        claim_id="booking", predicate="appointment_booked", state=ClaimState.CONFIRMED,
        required_evidence_rule="appointment_booked", supporting_evidence_ids=["provider-proof"],
        intent_revision_id="revision", updated_by_event_id="confirmed-event",
    )
    prior = SpeechAct(
        speech_id="prior", act_type=SpeechActType.RESULT, template_id="tmpl_booked",
        claim_ids=[claim.claim_id], requested_certainty=ClaimCertainty.CONFIRMED,
        state=SpeechState.EMITTED, created_by_event_id="proposal-event",
        rendered_text="The appointment is booked.", approved_policy_id="truthlock.v1",
        approved_through_sequence=1,
        approved_claim_versions={claim.claim_id: claim.updated_by_event_id}, heard=True,
    )
    state = SessionState(session_id="room", last_sequence=1,
                         claims={claim.claim_id: claim}, speech={prior.speech_id: prior})
    invalidation = EventEnvelope(
        event_id="invalidation", session_id="room", sequence=2,
        event_type="ClaimStateChanged", source=EventSource.POLICY,
        occurred_at=datetime(2030, 1, 1, tzinfo=timezone.utc), logical_time=2,
        payload={"claim_id": claim.claim_id, "from_state": "CONFIRMED", "to_state": "STALE",
                 "evidence_ids": []},
    )
    changed, commands = Reducer.reduce(state, invalidation, RuntimeMode.TEST)
    assert changed is not None
    assert changed.speech[prior.speech_id].state == SpeechState.CORRECTION_REQUIRED
    assert changed.speech[prior.speech_id].heard is True
    assert changed.speech[prior.speech_id].rendered_text == prior.rendered_text
    requests = [command for command in commands if isinstance(command, RequestSpeechCorrection)]
    assert len(requests) == 1
    proposal = CorrectionPolicy().propose(requests[0], changed, correction_speech_id="correction")
    assert proposal is not None
    assert proposal.speech_act.act_type == SpeechActType.CORRECTION
    assert proposal.speech_act.supersedes_speech_id == prior.speech_id
    assert validate_correction_proposal(proposal, changed) is None


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
