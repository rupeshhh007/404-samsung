"""T-VOICE-01: deterministic, network-free LiveKit boundary contract."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from importlib.metadata import version
from typing import Any, Callable

import pytest

from interlock.adapters.livekit_agent import (
    BrowserVoiceWorkerTransport, LiveKitSessionAdapter, VoiceProviders,
    compose_voice_room, run_livekit_voice_agent,
)
from interlock.adapters.voice_transport import VoiceTransportRegistry
from interlock.adapters.websocket import ProjectionHub
from interlock.config import Settings
from interlock.domain.enums import (
    Authorization,
    CancellationAckScope,
    CancellationState,
    ClaimCertainty,
    ClaimState,
    ControlKind,
    DivergenceState,
    EffectState,
    EventSource,
    IntentMaturity,
    SpeechActType,
    SpeechState,
    RuntimeMode,
    OperationState,
)
from interlock.domain.models import ClaimRecord, EventEnvelope, IntentRevision, SessionState, SpeechAct
from interlock.main import Application, RuntimeDependencies
from interlock.main import create_demo_asgi_app
from interlock.runtime.commands import RequestSpeechCorrection
from interlock.runtime.journal import EventCandidate
from interlock.runtime.reducer import Reducer
from interlock.truth.speech import CorrectionPolicy, validate_correction_proposal


def test_verified_livekit_agents_version_is_installed() -> None:
    assert version("livekit-agents") == "1.8.4"


def _voice_env(monkeypatch: Any) -> None:
    monkeypatch.setenv("LIVEKIT_URL", "wss://voice.example.invalid")
    monkeypatch.setenv("LIVEKIT_API_KEY", "test-key")
    monkeypatch.setenv("LIVEKIT_API_SECRET", "a" * 40)
    monkeypatch.setenv("INTERLOCK_VOICE_WORKER_SECRET", "b" * 40)


def test_browser_voice_token_is_scoped_and_no_client_grants(monkeypatch: Any) -> None:
    import httpx
    import jwt
    from livekit import api

    async def case() -> None:
        host = create_demo_asgi_app()
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=host),
                                     base_url="http://testserver") as client:
            absent = await client.post("/api/v1/voice/sessions", json={})
            assert absent.status_code == 503
            _voice_env(monkeypatch)
            privileged = await client.post("/api/v1/voice/sessions", json={"room_admin": True})
            assert privileged.status_code == 422
            first = await client.post("/api/v1/voice/sessions", json={})
            second = await client.post("/api/v1/voice/sessions", json={})
            assert first.status_code == second.status_code == 201
            one, two = first.json(), second.json()
            assert set(one) == {"session_id", "room_name", "livekit_url", "participant_token", "ws_url"}
            assert one["session_id"] != two["session_id"]
            assert one["room_name"] != two["room_name"]
            assert one["participant_token"] != two["participant_token"]
            assert "a" * 40 not in str(one) and "b" * 40 not in str(one)
            assert one["session_id"] in one["ws_url"]
            claims = api.TokenVerifier("test-key", "a" * 40).verify(one["participant_token"])
            assert claims.video.room == one["room_name"]
            assert claims.video.room_join is True
            assert claims.video.can_publish is True
            assert claims.video.can_subscribe is True
            assert claims.video.can_publish_data is False
            assert claims.video.can_publish_sources == ["microphone"]
            assert not claims.video.room_admin and not claims.video.room_create
            assert not claims.video.room_list and not claims.video.room_record
            raw_claims = jwt.decode(one["participant_token"], "a" * 40,
                                    algorithms=["HS256"], issuer="test-key")
            assert raw_claims["exp"] - raw_claims["nbf"] <= 300
            assert host.application.snapshot(one["session_id"]).session_id == one["session_id"]
        await host.application.close()
        await host.hub.shutdown()

    asyncio.run(case())


def test_worker_transcript_advances_the_same_backend_projection(monkeypatch: Any) -> None:
    _voice_env(monkeypatch)

    class WorkerSocket:
        def __init__(self) -> None:
            self.messages: list[dict[str, Any]] = []

        async def send_json(self, message: dict[str, Any]) -> None:
            self.messages.append(message)

    async def case() -> None:
        host = create_demo_asgi_app()
        transport: VoiceTransportRegistry = host.voice_registry
        binding, _, token = await transport.create()
        assert transport.application is host.application
        assert transport.authenticate(binding.session_id, binding.room_name, "b" * 40) is binding
        for wrong_session, wrong_room, secret in (
            ("wrong", binding.room_name, "b" * 40),
            (binding.session_id, "wrong", "b" * 40),
            (binding.session_id, binding.room_name, token),
        ):
            with pytest.raises(ValueError):
                transport.authenticate(wrong_session, wrong_room, secret)
        socket = WorkerSocket()
        generation = await transport.connect(binding, socket)  # type: ignore[arg-type]
        fact = {"type": "TRANSCRIPT", "worker_event_id": "transcript-1",
                "item_id": "utterance", "text": "book eleven", "final": False,
                "created_at": None}
        await transport.accept(binding, generation, fact)
        await transport.accept(binding, generation, fact)
        await host.application.drain(binding.session_id)
        state = host.application.snapshot(binding.session_id)
        assert [event.event_type for event in host.application.events(binding.session_id)].count(
            "TranscriptHypothesisObserved") == 1
        assert not any(event.event_type == "ToolDispatchRequested"
                       for event in host.application.events(binding.session_id))
        subscriber = await host.hub.subscribe(binding.session_id)
        projected = subscriber.queue.get_nowait()
        assert projected["session_id"] == binding.session_id
        assert projected["through_sequence"] == state.last_sequence
        assert projected["projection"]["evidence"]
        with pytest.raises(ValueError):
            await transport.accept(binding, generation, {"type": "FAKE_EVENT", "worker_event_id": "bad"})
        with pytest.raises(ValueError):
            await transport.accept(binding, generation, {**fact, "worker_event_id": "bad-extra",
                                                        "event_type": "ToolDispatchRequested"})
        transport.disconnect(binding, generation)
        with pytest.raises(ValueError):
            await transport.accept(binding, generation, {**fact, "worker_event_id": "stale"})
        await host.application.close()
        await host.hub.shutdown()

    asyncio.run(case())


def test_remote_voice_output_waits_for_real_start_and_exact_text(monkeypatch: Any) -> None:
    _voice_env(monkeypatch)

    class WorkerSocket:
        def __init__(self) -> None:
            self.messages: list[dict[str, Any]] = []
            self.speak_sent = asyncio.Event()

        async def send_json(self, message: dict[str, Any]) -> None:
            self.messages.append(message)
            if message.get("type") == "SPEAK":
                self.speak_sent.set()

    async def case() -> None:
        host = create_demo_asgi_app()
        transport: VoiceTransportRegistry = host.voice_registry
        binding, _, _ = await transport.create()
        socket = WorkerSocket()
        generation = await transport.connect(binding, socket)  # type: ignore[arg-type]
        speech = SpeechAct(
            speech_id="voice-progress", act_type=SpeechActType.PROGRESS,
            template_id="tmpl_checking", requested_certainty=ClaimCertainty.PROGRESS,
            state=SpeechState.PROPOSED, created_by_event_id="proposal",
        )
        await host.application.append(EventCandidate(
            session_id=binding.session_id, event_type="SpeechActProposed",
            source=EventSource.POLICY,
            payload={"speech_act": speech.model_dump(mode="json")},
        ))
        await asyncio.wait_for(socket.speak_sent.wait(), timeout=2)
        persisted = host.application.snapshot(binding.session_id).speech[speech.speech_id]
        assert socket.messages == [{
            "type": "SPEAK", "speech_id": speech.speech_id,
            "rendered_text": persisted.rendered_text,
        }]
        assert not any(event.event_type == "SpeechEmissionStarted"
                       for event in host.application.events(binding.session_id))
        with pytest.raises(ValueError, match="lacks start proof"):
            await transport.accept(binding, generation, {
                "type": "PLAYOUT_FINISHED", "worker_event_id": "premature-finish",
                "speech_id": speech.speech_id, "heard": True,
            })
        await transport.accept(binding, generation, {
            "type": "PLAYOUT_STARTED", "worker_event_id": "start-1",
            "speech_id": speech.speech_id,
        })
        async def started() -> None:
            while not any(event.event_type == "SpeechEmissionStarted"
                          for event in host.application.events(binding.session_id)):
                await asyncio.sleep(0.01)
        await asyncio.wait_for(started(), timeout=2)
        assert any(event.event_type == "SpeechEmissionStarted"
                   for event in host.application.events(binding.session_id))
        await transport.accept(binding, generation, {
            "type": "USER_SPEAKING", "worker_event_id": "barge-1",
        })
        await asyncio.sleep(0)
        assert any(event.event_type == "SpeechCancellationRequested"
                   for event in host.application.events(binding.session_id))
        assert not any(event.event_type == "CancellationRequested"
                       for event in host.application.events(binding.session_id))
        await transport.accept(binding, generation, {
            "type": "PLAYOUT_FINISHED", "worker_event_id": "finish-1",
            "speech_id": speech.speech_id, "heard": True,
        })
        await host.application.drain(binding.session_id)
        assert host.application.snapshot(binding.session_id).speech[speech.speech_id].heard is True
        transport.disconnect(binding, generation)
        await host.application.close()
        await host.hub.shutdown()

    asyncio.run(case())


def test_browser_worker_owns_only_transport_and_emits_playout_proof() -> None:
    class Handle:
        def __init__(self) -> None:
            self.id = "one-handle"
            self.interrupted = False
            self.played = asyncio.Event()

        async def wait_for_playout(self) -> None:
            await self.played.wait()

        def exception(self) -> None:
            return None

    class Session:
        agent_state = "speaking"

        def __init__(self) -> None:
            self.handle = Handle()
            self.current_speech = self.handle
            self.text: str | None = None

        def say(self, text: str, *, allow_interruptions: bool,
                add_to_chat_ctx: bool) -> Handle:
            assert allow_interruptions is False
            assert add_to_chat_ctx is False
            self.text = text
            return self.handle

    class Socket:
        def __init__(self) -> None:
            self.messages: list[dict[str, Any]] = []

        async def send(self, raw: str) -> None:
            import json
            self.messages.append(json.loads(raw))

    async def case() -> None:
        session = Session()
        socket = Socket()
        worker = BrowserVoiceWorkerTransport(  # type: ignore[arg-type]
            session, room_name="voice-opaque", backend_ws_url="ws://localhost/api/v1",
            worker_secret="worker-only",
        )
        assert not hasattr(worker, "application")
        worker._socket = socket
        exact = "I cannot confirm the new booking yet."
        task = asyncio.create_task(worker._speak("speech-1", exact))
        async def started() -> None:
            while not socket.messages:
                await asyncio.sleep(0.01)
        await asyncio.wait_for(started(), timeout=2)
        assert session.text == exact
        assert [(message["type"], message["speech_id"]) for message in socket.messages] == [
            ("PLAYOUT_STARTED", "speech-1"),
        ]
        session.handle.played.set()
        await asyncio.wait_for(task, timeout=2)
        assert [(message["type"], message["speech_id"]) for message in socket.messages] == [
            ("PLAYOUT_STARTED", "speech-1"), ("PLAYOUT_FINISHED", "speech-1"),
        ]
        assert socket.messages[-1]["heard"] is True

    asyncio.run(case())


def test_browser_worker_interruption_after_start_reports_heard_failure() -> None:
    import json

    class Handle:
        id = "speech-handle-1"

        def __init__(self) -> None:
            self.interrupted = False
            self.played = asyncio.Event()

        async def wait_for_playout(self) -> None:
            await self.played.wait()

        def done(self) -> bool:
            return self.played.is_set()

        def interrupt(self, *, force: bool) -> None:
            assert force is True
            self.interrupted = True
            self.played.set()

        def exception(self) -> None:
            return None

    class Session:
        agent_state = "speaking"

        def __init__(self) -> None:
            self.handle = Handle()
            self.current_speech = self.handle
            self.text: str | None = None

        def say(self, text: str, *, allow_interruptions: bool,
                add_to_chat_ctx: bool) -> Handle:
            assert not allow_interruptions and not add_to_chat_ctx
            self.text = text
            return self.handle

    class Socket:
        def __init__(self) -> None:
            self.messages: list[dict[str, Any]] = []
            self.started = asyncio.Event()
            self.terminal = asyncio.Event()
            self.inbound: asyncio.Queue[str] = asyncio.Queue()

        async def send(self, raw: str) -> None:
            message = json.loads(raw)
            self.messages.append(message)
            if message["type"] == "PLAYOUT_STARTED":
                self.started.set()
            if message["type"] == "PLAYOUT_FAILED":
                self.terminal.set()

        def __aiter__(self) -> "Socket":
            return self

        async def __anext__(self) -> str:
            return await self.inbound.get()

    async def case() -> None:
        session = Session()
        socket = Socket()
        worker = BrowserVoiceWorkerTransport(  # type: ignore[arg-type]
            session, room_name="voice-opaque", backend_ws_url="ws://localhost/api/v1",
            worker_secret="worker-only",
        )
        worker._socket = socket
        reader = asyncio.create_task(worker._read())
        speaker = asyncio.create_task(worker._speak("speech-1", "Exact approved text."))
        await asyncio.wait_for(socket.started.wait(), timeout=2)
        await socket.inbound.put(json.dumps({"type": "CANCEL_SPEECH", "speech_id": "speech-1"}))
        await asyncio.wait_for(socket.terminal.wait(), timeout=2)
        await asyncio.wait_for(speaker, timeout=2)
        reader.cancel()
        await asyncio.gather(reader, return_exceptions=True)
        assert session.text == "Exact approved text."
        assert [item["type"] for item in socket.messages] == ["PLAYOUT_STARTED", "PLAYOUT_FAILED"]
        assert socket.messages[-1]["speech_id"] == "speech-1"
        assert socket.messages[-1]["error_code"] == "LIVEKIT_INTERRUPTED"
        assert socket.messages[-1]["heard"] is True

    asyncio.run(case())


def test_browser_barge_in_terminal_allows_second_speech(monkeypatch: Any) -> None:
    _voice_env(monkeypatch)

    async def case() -> None:
        host = create_demo_asgi_app()
        transport: VoiceTransportRegistry = host.voice_registry
        binding, _, _ = await transport.create()

        class WorkerSocket:
            def __init__(self) -> None:
                self.messages: list[dict[str, Any]] = []
                self.first_started = asyncio.Event()
                self.cancelled = asyncio.Event()
                self.second_finished = asyncio.Event()
                self.tasks: set[asyncio.Task[Any]] = set()

            async def send_json(self, message: dict[str, Any]) -> None:
                self.messages.append(message)
                if message["type"] == "SPEAK":
                    speech_id = message["speech_id"]

                    async def playout() -> None:
                        await transport.accept(binding, 1, {
                            "type": "PLAYOUT_STARTED", "worker_event_id": f"start-{speech_id}",
                            "speech_id": speech_id,
                        })
                        if speech_id == "speech-1":
                            self.first_started.set()
                        else:
                            await transport.accept(binding, 1, {
                                "type": "PLAYOUT_FINISHED", "worker_event_id": f"finish-{speech_id}",
                                "speech_id": speech_id, "heard": True,
                            })
                            self.second_finished.set()

                    task = asyncio.create_task(playout())
                    self.tasks.add(task)
                    task.add_done_callback(self.tasks.discard)
                elif message["type"] == "CANCEL_SPEECH":
                    assert message["speech_id"] == "speech-1"
                    self.cancelled.set()
                    task = asyncio.create_task(transport.accept(binding, 1, {
                        "type": "PLAYOUT_FAILED", "worker_event_id": "interrupted-speech-1",
                        "speech_id": "speech-1", "error_code": "LIVEKIT_INTERRUPTED", "heard": True,
                    }))
                    self.tasks.add(task)
                    task.add_done_callback(self.tasks.discard)

        socket = WorkerSocket()
        await transport.connect(binding, socket)  # type: ignore[arg-type]

        async def propose(speech_id: str) -> None:
            act = SpeechAct(
                speech_id=speech_id, act_type=SpeechActType.PROGRESS,
                template_id="tmpl_checking", requested_certainty=ClaimCertainty.PROGRESS,
                state=SpeechState.PROPOSED, created_by_event_id=f"proposal-{speech_id}",
            )
            await host.application.append(EventCandidate(
                session_id=binding.session_id, event_type="SpeechActProposed",
                source=EventSource.POLICY, payload={"speech_act": act.model_dump(mode="json")},
            ))

        await propose("speech-1")
        await asyncio.wait_for(socket.first_started.wait(), timeout=2)
        async def emission_started() -> None:
            while not any(e.event_type == "SpeechEmissionStarted" and e.payload.get("speech_id") == "speech-1"
                          for e in host.application.events(binding.session_id)):
                await asyncio.sleep(0)
        await asyncio.wait_for(emission_started(), timeout=2)
        await transport.accept(binding, 1, {
            "type": "USER_SPEAKING", "worker_event_id": "barge-speech-1",
        })
        await asyncio.wait_for(socket.cancelled.wait(), timeout=2)
        await asyncio.wait_for(host.application.drain(binding.session_id), timeout=2)
        state = host.application.snapshot(binding.session_id)
        assert state.speech["speech-1"].heard is True
        assert state.speech["speech-1"].state == SpeechState.EMITTED
        assert any(e.event_type == "SpeechCancellationRequested"
                   for e in host.application.events(binding.session_id))
        assert any(e.event_type == "SpeechEmissionFailed" and e.payload.get("speech_id") == "speech-1"
                   for e in host.application.events(binding.session_id))
        assert not any(e.event_type == "CancellationRequested"
                       for e in host.application.events(binding.session_id))

        await propose("speech-2")
        await asyncio.wait_for(socket.second_finished.wait(), timeout=2)
        await asyncio.wait_for(host.application.drain(binding.session_id), timeout=2)
        assert host.application.snapshot(binding.session_id).speech["speech-2"].state == SpeechState.EMITTED
        assert host.application.snapshot(binding.session_id).speech["speech-2"].heard is True
        assert [m["speech_id"] for m in socket.messages if m["type"] == "SPEAK"] == [
            "speech-1", "speech-2",
        ]
        await asyncio.gather(*tuple(socket.tasks))
        transport.disconnect(binding, 1)
        await host.application.close()
        await host.hub.shutdown()

    asyncio.run(case())


def test_voice_binding_expiry_and_ambiguous_disconnect_fail_closed(monkeypatch: Any) -> None:
    from time import monotonic

    _voice_env(monkeypatch)

    class Socket:
        async def send_json(self, _message: dict[str, Any]) -> None:
            return

    async def case() -> None:
        host = create_demo_asgi_app()
        registry: VoiceTransportRegistry = host.voice_registry
        binding, _, _ = await registry.create()
        generation = await registry.connect(binding, Socket())  # type: ignore[arg-type]
        before = len(host.application.events(binding.session_id))
        registry.disconnect(binding, generation)
        assert len(host.application.events(binding.session_id)) == before
        assert not any(event.event_type in {"SpeechEmissionFinished", "SpeechEmissionFailed"}
                       for event in host.application.events(binding.session_id))
        binding.expiry = monotonic() - 1
        with pytest.raises(ValueError, match="expired"):
            registry.binding(binding.session_id)
        with pytest.raises(ValueError):
            registry.authenticate(binding.session_id, binding.room_name, "b" * 40)
        await host.application.close()
        await host.hub.shutdown()

    asyncio.run(case())


def test_two_browser_rooms_have_private_samsung_worlds_and_narrow_aliases(monkeypatch: Any) -> None:
    _voice_env(monkeypatch)

    async def case() -> None:
        host = create_demo_asgi_app(Settings(INTERLOCK_FAKE_LATENCY_MS=0))
        transport: VoiceTransportRegistry = host.voice_registry

        class WorkerSocket:
            def __init__(self, binding: Any, generation: int) -> None:
                self.binding = binding
                self.generation = generation
                self.tasks: set[asyncio.Task[Any]] = set()

            async def send_json(self, message: dict[str, Any]) -> None:
                if message.get("type") != "SPEAK":
                    return

                async def playout() -> None:
                    await asyncio.sleep(0)
                    await transport.accept(self.binding, self.generation, {
                        "type": "PLAYOUT_STARTED", "worker_event_id": uuid4().hex,
                        "speech_id": message["speech_id"],
                    })
                    await asyncio.sleep(0.02)
                    await transport.accept(self.binding, self.generation, {
                        "type": "PLAYOUT_FINISHED", "worker_event_id": uuid4().hex,
                        "speech_id": message["speech_id"], "heard": True,
                    })

                task = asyncio.create_task(playout())
                self.tasks.add(task)
                task.add_done_callback(self.tasks.discard)

        from uuid import uuid4

        bindings = []
        sockets = []
        for _ in range(2):
            binding, _, _ = await transport.create()
            socket = WorkerSocket(binding, 1)
            await transport.connect(binding, socket)  # type: ignore[arg-type]
            bindings.append(binding)
            sockets.append(socket)
        a, b = bindings
        assert a.provider is not b.provider
        assert a.provider.physical_action_count == b.provider.physical_action_count == 0

        for binding, utterance in ((a, "book eleven"), (b, "Book twelve.")):
            await transport.accept(binding, 1, {
                "type": "TRANSCRIPT", "worker_event_id": uuid4().hex,
                "item_id": uuid4().hex, "text": utterance, "final": True,
                "created_at": None,
            })
            await asyncio.wait_for(host.application.drain(binding.session_id), timeout=5)
            assert binding.provider.physical_action_count == 1
            assert any(event.event_type == "ToolDispatchRequested"
                       for event in host.application.events(binding.session_id))
        assert a.provider is not b.provider
        assert next(iter(a.provider.bookings.values()))["confirmed_slot"].endswith("11:00:00+05:30")
        assert next(iter(b.provider.bookings.values()))["confirmed_slot"].endswith("12:00:00+05:30")
        assert host.application.snapshot(a.session_id).session_id == a.session_id
        assert host.application.snapshot(b.session_id).session_id == b.session_id
        assert set(host.application.snapshot(a.session_id).effects).isdisjoint(
            host.application.snapshot(b.session_id).effects)
        before = sum(event.event_type == "ToolDispatchRequested"
                     for event in host.application.events(a.session_id))
        await transport.accept(a, 1, {
            "type": "TRANSCRIPT", "worker_event_id": uuid4().hex,
            "item_id": uuid4().hex, "text": "don't make it twelve", "final": True,
            "created_at": None,
        })
        await asyncio.wait_for(host.application.drain(a.session_id), timeout=5)
        assert sum(event.event_type == "ToolDispatchRequested"
                   for event in host.application.events(a.session_id)) == before
        await transport.accept(a, 1, {
            "type": "TRANSCRIPT", "worker_event_id": uuid4().hex,
            "item_id": uuid4().hex, "text": "actually make it twelve", "final": True,
            "created_at": None,
        })
        await asyncio.wait_for(host.application.drain(a.session_id), timeout=5)
        active = host.application.snapshot(a.session_id)
        active_intent = active.intents[active.active_intent_id]
        assert active.revisions[active_intent.active_revision_id].values["requested_slot"].endswith("12:00:00+05:30")
        assert a.provider.physical_action_count == 1

        negated, _, _ = await transport.create()
        negated_socket = WorkerSocket(negated, 1)
        await transport.connect(negated, negated_socket)  # type: ignore[arg-type]
        for phrase in ("don't book eleven", "do not book eleven"):
            await transport.accept(negated, 1, {
                "type": "TRANSCRIPT", "worker_event_id": uuid4().hex,
                "item_id": uuid4().hex, "text": phrase, "final": True,
                "created_at": None,
            })
        await asyncio.wait_for(host.application.drain(negated.session_id), timeout=5)
        assert negated.provider.physical_action_count == 0
        assert not any(event.event_type == "ToolDispatchRequested"
                       for event in host.application.events(negated.session_id))
        await asyncio.gather(*tuple(negated_socket.tasks))
        transport.disconnect(negated, 1)
        for binding, socket in zip(bindings, sockets):
            await asyncio.gather(*tuple(socket.tasks))
            transport.disconnect(binding, 1)
        await host.application.close()
        await host.hub.shutdown()

    asyncio.run(case())


async def _demo_control(application: Application, session_id: str, kind: ControlKind) -> None:
    from uuid import uuid4

    await application.append(EventCandidate(
        session_id=session_id, event_type="ControlIntentInterpreted",
        source=EventSource.MODEL,
        payload={"control": {
            "control_id": uuid4().hex, "kind": kind.value, "confidence": 1.0,
            "consequential": False, "target_refs": [], "raw_evidence_id": "test-control",
            "clarification": None,
        }},
    ))


async def _demo_voice_transcript(
    registry: VoiceTransportRegistry, binding: Any, text: str,
) -> None:
    from uuid import uuid4

    await registry.accept(binding, binding.generation, {
        "type": "TRANSCRIPT", "worker_event_id": uuid4().hex,
        "item_id": uuid4().hex, "text": text, "final": True, "created_at": None,
    })


class _AutoVoicePlayout:
    def __init__(self, registry: VoiceTransportRegistry, binding: Any) -> None:
        self.registry = registry
        self.binding = binding
        self.tasks: set[asyncio.Task[Any]] = set()

    async def send_json(self, message: dict[str, Any]) -> None:
        if message["type"] != "SPEAK":
            return

        async def complete() -> None:
            from uuid import uuid4
            await self.registry.accept(self.binding, self.binding.generation, {
                "type": "PLAYOUT_STARTED", "worker_event_id": uuid4().hex,
                "speech_id": message["speech_id"],
            })
            await self.registry.accept(self.binding, self.binding.generation, {
                "type": "PLAYOUT_FINISHED", "worker_event_id": uuid4().hex,
                "speech_id": message["speech_id"], "heard": True,
            })

        task = asyncio.create_task(complete())
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)


def test_missing_final_transcript_gets_controlled_repeat_prompt(monkeypatch: Any) -> None:
    _voice_env(monkeypatch)

    async def case() -> None:
        host = create_demo_asgi_app(Settings(INTERLOCK_FAKE_LATENCY_MS=0))
        registry: VoiceTransportRegistry = host.voice_registry
        binding, _, _ = await registry.create()
        socket = _AutoVoicePlayout(registry, binding)
        await registry.connect(binding, socket)  # type: ignore[arg-type]

        from uuid import uuid4

        await registry.accept(binding, binding.generation, {
            "type": "TRANSCRIPTION_TIMEOUT",
            "worker_event_id": uuid4().hex,
            "speech_duration_ms": 1400,
        })
        await asyncio.wait_for(host.application.drain(binding.session_id), timeout=5)

        async def repeat_prompt_emitted() -> None:
            while True:
                state = host.application.snapshot(binding.session_id)
                if any(
                    speech.template_id == "tmpl_clarification_repeat"
                    and speech.state == SpeechState.EMITTED
                    for speech in state.speech.values()
                ):
                    return
                await asyncio.sleep(0)

        await asyncio.wait_for(repeat_prompt_emitted(), timeout=5)
        events = host.application.events(binding.session_id)
        assert any(event.event_type == "VoiceTranscriptionTimeoutObserved" for event in events)
        assert not any(event.event_type == "ToolDispatchRequested" for event in events)
        assert binding.provider.physical_action_count == 0

        await asyncio.gather(*tuple(socket.tasks))
        registry.disconnect(binding, binding.generation)
        await host.application.close()
        await host.hub.shutdown()

    asyncio.run(case())


def test_short_vad_blip_timeout_does_not_prompt_or_write(monkeypatch: Any) -> None:
    _voice_env(monkeypatch)

    async def case() -> None:
        host = create_demo_asgi_app(Settings(INTERLOCK_FAKE_LATENCY_MS=0))
        registry: VoiceTransportRegistry = host.voice_registry
        binding, _, _ = await registry.create()
        socket = _AutoVoicePlayout(registry, binding)
        await registry.connect(binding, socket)  # type: ignore[arg-type]

        from uuid import uuid4

        await registry.accept(binding, binding.generation, {
            "type": "TRANSCRIPTION_TIMEOUT",
            "worker_event_id": uuid4().hex,
            "speech_duration_ms": 250,
        })
        await asyncio.wait_for(host.application.drain(binding.session_id), timeout=5)
        state = host.application.snapshot(binding.session_id)
        assert not state.speech
        assert binding.provider.physical_action_count == 0

        registry.disconnect(binding, binding.generation)
        await host.application.close()
        await host.hub.shutdown()

    asyncio.run(case())


def test_late_correction_retains_eleven_and_never_repairs_automatically(monkeypatch: Any) -> None:
    _voice_env(monkeypatch)

    async def case() -> None:
        host = create_demo_asgi_app(Settings(INTERLOCK_FAKE_LATENCY_MS=0))
        registry: VoiceTransportRegistry = host.voice_registry
        binding, _, _ = await registry.create()
        socket = _AutoVoicePlayout(registry, binding)
        await registry.connect(binding, socket)  # type: ignore[arg-type]
        await _demo_voice_transcript(registry, binding, "book eleven")
        await asyncio.wait_for(host.application.drain(binding.session_id), timeout=5)
        committed = host.application.snapshot(binding.session_id)
        assert binding.provider.physical_action_count == 1
        assert len(committed.effects) == 1
        original = next(iter(committed.effects.values()))
        assert original.parameters["confirmed_slot"].endswith("11:00:00+05:30")
        assert original.state == EffectState.COMMITTED

        await _demo_voice_transcript(registry, binding, "Actually, make it twelve.")
        await asyncio.wait_for(host.application.drain(binding.session_id), timeout=5)
        final = host.application.snapshot(binding.session_id)
        active = final.intents[final.active_intent_id]
        desired = final.revisions[active.active_revision_id]
        assert desired.values["requested_slot"].endswith("12:00:00+05:30")
        assert binding.provider.physical_action_count == 1
        assert len(final.effects) == 1 and original.effect_id in final.effects
        assert len([case for case in final.divergences.values()
                    if case.state == DivergenceState.OPEN and original.effect_id in case.observed_effect_ids]) == 1
        assert not any(op.intent_revision_id == desired.revision_id and op.tool_name == "appointment.book"
                       for op in final.operations.values())
        assert not any(effect.parameters.get("confirmed_slot", "").endswith("12:00:00+05:30")
                       for effect in final.effects.values())
        assert not any(claim.intent_revision_id == desired.revision_id and claim.state == ClaimState.CONFIRMED
                       for claim in final.claims.values())
        assert not any(speech.act_type == SpeechActType.RESULT and speech.state == SpeechState.EMITTED
                       and any(final.claims[cid].intent_revision_id == desired.revision_id
                               for cid in speech.claim_ids) for speech in final.speech.values())
        assert not final.plans
        assert not any(event.event_type == "DivergenceResolved"
                       for event in host.application.events(binding.session_id))
        await asyncio.gather(*tuple(socket.tasks))
        registry.disconnect(binding, binding.generation)
        await host.application.close()
        await host.hub.shutdown()

    asyncio.run(case())


def test_dispatched_unknown_eleven_never_licenses_blind_twelve(monkeypatch: Any) -> None:
    from dataclasses import replace
    import interlock.adapters.voice_transport as voice_transport

    _voice_env(monkeypatch)
    original_factory = voice_transport.create_demo_session_dependencies
    provider_acted = asyncio.Event()
    release_result = asyncio.Event()

    class GateAfterProviderAction:
        def __init__(self, delegate: Any) -> None:
            self.delegate = delegate

        async def invoke(self, invocation: Any) -> Any:
            result = await self.delegate.invoke(invocation)
            provider_acted.set()
            await release_result.wait()
            return result

        async def cancel(self, request: Any) -> Any:
            return await self.delegate.cancel(request)

    def gated_factory(*args: Any, **kwargs: Any) -> Any:
        registry, dependencies, provider = original_factory(*args, **kwargs)
        return registry, replace(
            dependencies, tool_transport=GateAfterProviderAction(dependencies.tool_transport),
        ), provider

    monkeypatch.setattr(voice_transport, "create_demo_session_dependencies", gated_factory)

    async def case() -> None:
        host = create_demo_asgi_app(Settings(INTERLOCK_FAKE_LATENCY_MS=0))
        registry: VoiceTransportRegistry = host.voice_registry
        binding, _, _ = await registry.create()
        socket = _AutoVoicePlayout(registry, binding)
        await registry.connect(binding, socket)  # type: ignore[arg-type]
        await _demo_voice_transcript(registry, binding, "book eleven")
        await asyncio.wait_for(provider_acted.wait(), timeout=5)
        in_flight = host.application.snapshot(binding.session_id)
        old = next(op for op in in_flight.operations.values() if op.tool_name == "appointment.book")
        assert old.dispatch_requested_event_id is not None
        assert binding.provider.physical_action_count == 1
        assert not in_flight.effects

        await _demo_voice_transcript(registry, binding, "actually make it twelve")

        async def child_authorized() -> None:
            while True:
                state = host.application.snapshot(binding.session_id)
                node = state.intents.get(state.active_intent_id) if state.active_intent_id else None
                revision = state.revisions.get(node.active_revision_id) if node else None
                if revision and revision.parent_revision_id is not None \
                        and revision.authorization == Authorization.AUTHORIZED:
                    return
                await asyncio.sleep(0)

        await asyncio.wait_for(child_authorized(), timeout=5)
        uncertain = host.application.snapshot(binding.session_id)
        assert not uncertain.effects
        assert not any(op.intent_revision_id != old.intent_revision_id and op.tool_name == "appointment.book"
                       for op in uncertain.operations.values())
        release_result.set()
        await asyncio.wait_for(host.application.drain(binding.session_id), timeout=5)
        final = host.application.snapshot(binding.session_id)
        assert binding.provider.physical_action_count == 1
        assert any(effect.operation_id == old.operation_id for effect in final.effects.values())
        assert not any(op.intent_revision_id != old.intent_revision_id and op.tool_name == "appointment.book"
                       for op in final.operations.values())
        await asyncio.gather(*tuple(socket.tasks))
        registry.disconnect(binding, binding.generation)
        await host.application.close()
        await host.hub.shutdown()

    asyncio.run(case())


def test_correction_before_parent_operation_creation_executes_latest_revision(monkeypatch: Any) -> None:
    _voice_env(monkeypatch)

    async def case() -> None:
        host = create_demo_asgi_app(Settings(INTERLOCK_FAKE_LATENCY_MS=0))
        registry: VoiceTransportRegistry = host.voice_registry
        binding, _, _ = await registry.create()
        socket = _AutoVoicePlayout(registry, binding)
        await registry.connect(binding, socket)  # type: ignore[arg-type]

        root = IntentRevision(
            revision_id="voice-race-root",
            intent_id="voice-race-intent",
            values={
                "goal_type": "appointment_booking",
                "center_id": "ctr-01",
                "requested_slot": "2030-01-15T11:00:00+05:30",
            },
            maturity=IntentMaturity.COMMITTED,
            authorization=Authorization.NOT_REQUESTED,
            created_by_event_id="voice-race-root-event",
            dependency_fingerprint="voice-race-root-fingerprint",
        )
        child = IntentRevision(
            revision_id="voice-race-child",
            intent_id=root.intent_id,
            parent_revision_id=root.revision_id,
            values={
                "goal_type": "appointment_booking",
                "center_id": "ctr-01",
                "requested_slot": "2030-01-15T12:00:00+05:30",
            },
            maturity=IntentMaturity.COMMITTED,
            authorization=Authorization.NOT_REQUESTED,
            created_by_event_id="voice-race-child-event",
            dependency_fingerprint="voice-race-child-fingerprint",
        )

        await host.application.append(EventCandidate(
            session_id=binding.session_id, event_type="IntentRevisionCommitted",
            source=EventSource.MODEL,
            payload={"revision": root.model_dump(mode="json")},
        ))
        await host.application.append(EventCandidate(
            session_id=binding.session_id, event_type="IntentRevisionCommitted",
            source=EventSource.MODEL,
            payload={"revision": child.model_dump(mode="json")},
        ))
        await host.application.append(EventCandidate(
            session_id=binding.session_id, event_type="IntentAuthorizationChanged",
            source=EventSource.USER,
            payload={
                "revision_id": child.revision_id,
                "authorization": Authorization.AUTHORIZED.value,
                "evidence_id": "voice-race-auth",
            },
        ))
        await asyncio.wait_for(host.application.drain(binding.session_id), timeout=5)

        final = host.application.snapshot(binding.session_id)
        assert not any(
            operation.intent_revision_id == root.revision_id
            for operation in final.operations.values()
        )
        child_operations = [
            operation for operation in final.operations.values()
            if operation.intent_revision_id == child.revision_id
            and operation.tool_name == "appointment.book"
        ]
        assert len(child_operations) == 1
        assert binding.provider.physical_action_count == 1
        assert len(binding.provider.bookings) == 1
        assert next(iter(binding.provider.bookings.values()))["confirmed_slot"].endswith(
            "12:00:00+05:30"
        )
        assert final.effects
        assert all(
            effect.operation_id == child_operations[0].operation_id
            for effect in final.effects.values()
        )
        assert not final.divergences

        await asyncio.gather(*tuple(socket.tasks))
        registry.disconnect(binding, binding.generation)
        await host.application.close()
        await host.hub.shutdown()

    asyncio.run(case())


def test_early_correction_replaces_only_locally_cancelled_pre_dispatch_booking(monkeypatch: Any) -> None:
    _voice_env(monkeypatch)

    async def case() -> None:
        host = create_demo_asgi_app(Settings(INTERLOCK_FAKE_LATENCY_MS=0))
        registry: VoiceTransportRegistry = host.voice_registry
        binding, _, _ = await registry.create()
        socket = _AutoVoicePlayout(registry, binding)
        await registry.connect(binding, socket)  # type: ignore[arg-type]
        await _demo_control(host.application, binding.session_id, ControlKind.PAUSE)
        assert host.application.snapshot(binding.session_id).paused is True
        await _demo_voice_transcript(registry, binding, "book eleven")
        await asyncio.wait_for(host.application.drain(binding.session_id), timeout=5)
        before = host.application.snapshot(binding.session_id)
        parent = next(op for op in before.operations.values() if op.tool_name == "appointment.book")
        assert parent.state == OperationState.READY
        assert parent.dispatch_requested_event_id is None
        assert binding.provider.physical_action_count == 0

        await _demo_voice_transcript(registry, binding, "actually make it twelve")
        await asyncio.wait_for(host.application.drain(binding.session_id), timeout=5)
        pending = host.application.snapshot(binding.session_id)
        old = pending.operations[parent.operation_id]
        assert old.state == OperationState.CANCELLED
        assert old.cancellation_state == CancellationState.ACKNOWLEDGED
        assert CancellationAckScope.LOCAL_TASK in old.cancellation_ack_scopes
        assert old.effect_state == EffectState.NOT_STARTED
        assert old.dispatch_requested_event_id is None
        assert binding.provider.physical_action_count == 0
        child = next(op for op in pending.operations.values() if op.operation_id != old.operation_id)
        assert child.args["requested_slot"].endswith("12:00:00+05:30")
        events = host.application.events(binding.session_id)
        child_auth = next(i for i, event in enumerate(events)
                          if event.event_type == "IntentAuthorizationChanged"
                          and event.payload["revision_id"] == child.intent_revision_id)
        local_ack = next(i for i, event in enumerate(events)
                         if event.event_type == "CancellationAcknowledged"
                         and event.payload["operation_id"] == old.operation_id)
        created = next(i for i, event in enumerate(events)
                       if event.event_type == "OperationCreated"
                       and event.payload["operation"]["operation_id"] == child.operation_id)
        assert child_auth < local_ack < created

        await _demo_control(host.application, binding.session_id, ControlKind.RESUME)
        await asyncio.wait_for(host.application.drain(binding.session_id), timeout=5)
        final = host.application.snapshot(binding.session_id)
        assert binding.provider.physical_action_count == 1
        assert len(binding.provider.bookings) == 1
        assert next(iter(binding.provider.bookings.values()))["confirmed_slot"].endswith("12:00:00+05:30")
        assert len(final.effects) == 1
        assert next(iter(final.effects.values())).operation_id == child.operation_id
        assert not any(effect.operation_id == old.operation_id for effect in final.effects.values())
        assert any(event.event_type == "ToolDispatchRequested"
                   and event.payload["operation_id"] == child.operation_id for event in host.application.events(binding.session_id))
        active = final.intents[final.active_intent_id]
        assert final.revisions[active.active_revision_id].values["requested_slot"].endswith("12:00:00+05:30")
        assert any(claim.state == ClaimState.CONFIRMED and claim.intent_revision_id == child.intent_revision_id
                   for claim in final.claims.values())
        assert not any(speech.act_type == SpeechActType.RESULT
                       and "11" in speech.rendered_text and speech.state == SpeechState.EMITTED
                       for speech in final.speech.values())
        await asyncio.gather(*tuple(socket.tasks))
        registry.disconnect(binding, binding.generation)
        await host.application.close()
        await host.hub.shutdown()

    asyncio.run(case())


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


def test_browser_voice_worker_entrypoint_is_picklable() -> None:
    import pickle
    from livekit.agents import AgentServer
    from interlock.adapters.livekit_agent import _browser_voice_entrypoint

    pickled = pickle.dumps(_browser_voice_entrypoint)
    unpickled = pickle.loads(pickled)
    assert unpickled is _browser_voice_entrypoint

    server = AgentServer()
    server.rtc_session(_browser_voice_entrypoint)
    server_pickled = pickle.dumps(server)
    server_unpickled = pickle.loads(server_pickled)
    assert server_unpickled._entrypoint_fnc is _browser_voice_entrypoint


def test_browser_voice_worker_entrypoint_configures_manual_turn_handling_and_no_autonomous_interruptions(monkeypatch: Any) -> None:
    from unittest.mock import AsyncMock, MagicMock
    from interlock.adapters import livekit_agent

    captured_session_kwargs: dict[str, Any] = {}
    captured_agent_kwargs: dict[str, Any] = {}

    class MockAgentSession:
        def __init__(self, **kwargs: Any) -> None:
            captured_session_kwargs.update(kwargs)

        def on(self, *args: Any, **kwargs: Any) -> None:
            pass

        async def start(self, *, room: Any, agent: Any) -> None:
            pass

        async def aclose(self) -> None:
            pass

    class MockAgent:
        def __init__(self, **kwargs: Any) -> None:
            captured_agent_kwargs.update(kwargs)

    monkeypatch.setattr(livekit_agent, "AgentSession", MockAgentSession)
    monkeypatch.setattr(livekit_agent, "Agent", MockAgent)
    monkeypatch.setattr(livekit_agent.BrowserVoiceWorkerTransport, "connect", AsyncMock())

    monkeypatch.setenv("DEEPGRAM_API_KEY", "fake-dg")
    monkeypatch.setenv("CARTESIA_API_KEY", "fake-cartesia")
    monkeypatch.setenv("INTERLOCK_VOICE_TTS_VOICE_ID", "voice-1")
    monkeypatch.setenv("INTERLOCK_VOICE_BACKEND_WS_URL", "ws://127.0.0.1:8000/api/v1")
    monkeypatch.setenv("INTERLOCK_VOICE_WORKER_SECRET", "secret-1")

    ctx = MagicMock()
    ctx.room.name = "voice-test-session"
    ctx.add_shutdown_callback = MagicMock()

    asyncio.run(livekit_agent._browser_voice_entrypoint(ctx))

    expected_turn_handling = {"turn_detection": "manual", "interruption": {"enabled": False}}
    assert captured_session_kwargs.get("turn_handling") == expected_turn_handling
    assert captured_agent_kwargs.get("turn_handling") == expected_turn_handling
