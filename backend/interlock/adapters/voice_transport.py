"""Backend-owned browser voice binding and narrow, authenticated worker bridge.

Only transport metadata lives here. The Application journal and reducer remain
the sole authority for every intent, operation, effect, claim, and speech fact.
"""

from __future__ import annotations

import asyncio
import os
import secrets
from collections import OrderedDict
from datetime import timedelta
from hashlib import sha256
from time import monotonic
from typing import Any, Literal
from urllib.parse import urlsplit
from uuid import uuid4

from fastapi import WebSocket
from starlette.websockets import WebSocketDisconnect
from livekit import api
from pydantic import BaseModel, ConfigDict, Field, StrictBool, ValidationError

from interlock.config import Settings
from interlock.domain.enums import EventSource, SpeechState
from interlock.main import Application, create_demo_session_dependencies
from interlock.runtime.journal import EventCandidate
from interlock.truth.speech import OutputPort, OutputPortFailure


class _TransportFact(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    worker_event_id: str = Field(min_length=1, max_length=128)


class Transcript(_TransportFact):
    type: Literal["TRANSCRIPT"]
    item_id: str | None = None
    text: str = Field(min_length=1, max_length=16_384)
    final: StrictBool
    created_at: float | None = None


class UserSpeaking(_TransportFact):
    type: Literal["USER_SPEAKING"]


class TranscriptionTimeout(_TransportFact):
    type: Literal["TRANSCRIPTION_TIMEOUT"]
    speech_duration_ms: int = Field(..., ge=0, le=120_000)


class PlayoutStarted(_TransportFact):
    type: Literal["PLAYOUT_STARTED"]
    speech_id: str = Field(min_length=1, max_length=128)


class PlayoutFinished(_TransportFact):
    type: Literal["PLAYOUT_FINISHED"]
    speech_id: str = Field(min_length=1, max_length=128)
    heard: Literal[True]


class PlayoutFailed(_TransportFact):
    type: Literal["PLAYOUT_FAILED"]
    speech_id: str = Field(min_length=1, max_length=128)
    error_code: str = Field(min_length=1, max_length=128)
    heard: StrictBool


_FACTS = {
    "TRANSCRIPT": Transcript,
    "USER_SPEAKING": UserSpeaking,
    "TRANSCRIPTION_TIMEOUT": TranscriptionTimeout,
    "PLAYOUT_STARTED": PlayoutStarted,
    "PLAYOUT_FINISHED": PlayoutFinished,
    "PLAYOUT_FAILED": PlayoutFailed,
}


def parse_worker_fact(raw: Any) -> _TransportFact:
    if not isinstance(raw, dict) or raw.get("type") not in _FACTS:
        raise ValueError("unknown worker transport fact")
    return _FACTS[raw["type"]].model_validate(raw)


class RemoteVoiceOutput(OutputPort):
    """A sent SPEAK is not an emission start; only matching worker proof is."""

    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        self._application: Application | None = None
        self._socket: WebSocket | None = None
        self._generation = 0
        self._send_lock = asyncio.Lock()
        self._starts: dict[tuple[int, str], asyncio.Future[None]] = {}
        self._started: set[tuple[int, str]] = set()
        self._origins: dict[str, str] = {}

    def bind_application(self, application: Application) -> None:
        self._application = application

    def bind(self, socket: WebSocket, generation: int) -> None:
        if self._socket is not None:
            raise RuntimeError("voice worker already connected")
        self._socket = socket
        self._generation = generation

    def disconnect(self, generation: int) -> None:
        if generation != self._generation:
            return
        self._socket = None
        for (owner, _), waiter in tuple(self._starts.items()):
            if owner == generation and not waiter.done():
                waiter.set_exception(RuntimeError("voice worker disconnected before start proof"))

    async def _send(self, message: dict[str, Any]) -> None:
        async with self._send_lock:
            if self._socket is None:
                raise RuntimeError("voice worker not connected")
            await self._socket.send_json(message)

    async def acknowledge(self, worker_event_id: str) -> None:
        await self._send({"type": "ACK", "worker_event_id": worker_event_id})

    async def emit(self, *, session_id: str, speech_id: str, rendered_text: str) -> None:
        if session_id != self.session_id:
            raise RuntimeError("voice output session mismatch")
        if self._socket is None:
            raise RuntimeError("voice worker not connected")
        if self._application is None:
            raise RuntimeError("voice output has no authoritative application")
        key = (self._generation, speech_id)
        if key in self._starts or speech_id in self._origins:
            return  # never retry a potentially audible output
        loop = asyncio.get_running_loop()
        waiter: asyncio.Future[None] = loop.create_future()
        self._starts[key] = waiter
        origins = [event.event_id for event in self._application.events(session_id)
                   if event.event_type == "SpeechQueued"
                   and event.payload.get("speech_id") == speech_id]
        if not origins:
            self._starts.pop(key, None)
            raise RuntimeError("voice output lacks queued lineage")
        self._origins[speech_id] = origins[-1]
        try:
            await self._send({"type": "SPEAK", "speech_id": speech_id, "rendered_text": rendered_text})
            await asyncio.wait_for(waiter, timeout=30.0)
        finally:
            self._starts.pop(key, None)

    async def cancel(self, *, session_id: str, speech_id: str) -> None:
        if session_id != self.session_id:
            raise RuntimeError("voice output session mismatch")
        if self._socket is not None:
            await self._send({"type": "CANCEL_SPEECH", "speech_id": speech_id})

    def started(self, generation: int, speech_id: str) -> None:
        waiter = self._starts.get((generation, speech_id))
        if waiter is None:
            raise ValueError("unrequested voice playout start")
        if not waiter.done():
            self._started.add((generation, speech_id))
            waiter.set_result(None)

    def origin(self, generation: int, speech_id: str) -> str:
        if (generation, speech_id) not in self._started:
            raise ValueError("voice playout terminal lacks start proof")
        try:
            return self._origins[speech_id]
        except KeyError as exc:
            raise ValueError("unrequested voice playout terminal") from exc

    def retire_origin(self, generation: int, speech_id: str) -> None:
        self._origins.pop(speech_id, None)
        self._started.discard((generation, speech_id))


class VoiceBinding:
    def __init__(self, session_id: str, room_name: str, participant_identity: str,
                 expiry: float, output: RemoteVoiceOutput, provider: Any) -> None:
        self.session_id = session_id
        self.room_name = room_name
        self.participant_identity = participant_identity
        self.expiry = expiry
        self.output = output
        self.provider = provider
        self.generation = 0
        self.connected = False
        self.worker_events: OrderedDict[str, str] = OrderedDict()


class VoiceTransportRegistry:
    """Bounded room metadata; contains no SessionState or second reducer."""

    TOKEN_TTL = timedelta(minutes=5)
    BINDING_TTL = timedelta(hours=1)

    def __init__(self, application: Application, *, settings: Settings,
                 projection: Any, max_bindings: int = 128) -> None:
        self.application = application
        self.settings = settings
        self.projection = projection
        self.max_bindings = max_bindings
        self._bindings: dict[str, VoiceBinding] = {}
        self._lock = asyncio.Lock()

    @staticmethod
    def _credentials() -> tuple[str, str, str, str]:
        names = ("LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET",
                 "INTERLOCK_VOICE_WORKER_SECRET")
        values = tuple(os.environ.get(name, "").strip() for name in names)
        if any(not value for value in values):
            raise RuntimeError("voice transport configuration is incomplete")
        parsed = urlsplit(values[0])
        if parsed.scheme not in ("ws", "wss") or not parsed.hostname \
                or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise RuntimeError("LiveKit URL is invalid")
        if len(values[3]) < 32:
            raise RuntimeError("voice worker secret must have at least 32 characters")
        return values  # type: ignore[return-value]

    async def create(self) -> tuple[VoiceBinding, str, str]:
        url, api_key, api_secret, _ = self._credentials()
        if self.settings.INTERLOCK_MODE != "DEMO":
            raise RuntimeError("browser Samsung voice requires DEMO semantic mode")
        async with self._lock:
            self._bindings = {
                key: binding for key, binding in self._bindings.items()
                if binding.connected or monotonic() < binding.expiry
            }
            if len(self._bindings) >= self.max_bindings:
                raise RuntimeError("voice session capacity reached")
            session_id = uuid4().hex
            room_name = f"voice-{session_id}"
            participant_identity = f"browser-{uuid4().hex}"
            output = RemoteVoiceOutput(session_id)
            registry, dependencies, provider = create_demo_session_dependencies(
                self.settings, output=output, projection=self.projection,
            )
            token = (
                api.AccessToken(api_key, api_secret)
                .with_identity(participant_identity)
                .with_ttl(self.TOKEN_TTL)
                .with_grants(api.VideoGrants(
                    room_join=True, room=room_name, can_publish=True,
                    can_subscribe=True, can_publish_data=False,
                    can_publish_sources=["microphone"], room_admin=False,
                    room_create=False, room_list=False, room_record=False,
                ))
                .to_jwt()
            )
            await self.application.start_session(
                session_id, mode="DEMO", registry=registry, dependencies=dependencies,
            )
            output.bind_application(self.application)
            binding = VoiceBinding(
                session_id, room_name, participant_identity,
                monotonic() + self.BINDING_TTL.total_seconds(), output, provider,
            )
            self._bindings[session_id] = binding
            return binding, url, token

    def binding(self, session_id: str) -> VoiceBinding:
        binding = self._bindings.get(session_id)
        if binding is None or monotonic() >= binding.expiry:
            raise ValueError("voice binding missing or expired")
        self.application.snapshot(session_id)  # existing authoritative session
        return binding

    def authenticate(self, session_id: str, room_name: str, credential: str) -> VoiceBinding:
        _, _, _, worker_secret = self._credentials()
        if not secrets.compare_digest(credential, worker_secret):
            raise ValueError("worker authentication failed")
        binding = self.binding(session_id)
        if binding.room_name != room_name:
            raise ValueError("voice room mismatch")
        if binding.connected:
            raise ValueError("voice worker already connected")
        return binding

    async def connect(self, binding: VoiceBinding, socket: WebSocket) -> int:
        async with self._lock:
            if binding.connected or monotonic() >= binding.expiry:
                raise ValueError("voice binding unavailable")
            binding.generation += 1
            binding.connected = True
            binding.output.bind(socket, binding.generation)
            return binding.generation

    def disconnect(self, binding: VoiceBinding, generation: int) -> None:
        if binding.generation == generation:
            binding.connected = False
            binding.output.disconnect(generation)

    async def accept(self, binding: VoiceBinding, generation: int, raw: Any) -> None:
        if not binding.connected or binding.generation != generation or monotonic() >= binding.expiry:
            raise ValueError("stale voice worker generation")
        fact = parse_worker_fact(raw)
        digest = sha256(fact.model_dump_json().encode()).hexdigest()
        prior = binding.worker_events.get(fact.worker_event_id)
        if prior is not None:
            if prior != digest:
                raise ValueError("conflicting worker event identity")
            return
        if len(binding.worker_events) >= 2048:
            raise RuntimeError("worker dedupe capacity reached")
        await self._apply(binding, generation, fact)
        binding.worker_events[fact.worker_event_id] = digest

    async def _apply(self, binding: VoiceBinding, generation: int, fact: _TransportFact) -> None:
        session_id = binding.session_id
        if isinstance(fact, Transcript):
            if not fact.text.strip():
                return
            identity = sha256(repr((fact.item_id, fact.text, fact.final)
                                   if fact.item_id is not None else
                                   (fact.text, fact.final, fact.created_at)).encode()).hexdigest()
            await self.application.append(EventCandidate(
                session_id=session_id, event_type="TranscriptHypothesisObserved",
                source=EventSource.INPUT_ADAPTER,
                payload={"evidence_id": f"voice-{identity}", "text": fact.text, "final": fact.final},
                dedupe_key=f"livekit:transcript:{identity}", correlation_id=session_id,
            ))
            return
        if isinstance(fact, TranscriptionTimeout):
            await self.application.append(EventCandidate(
                session_id=session_id,
                event_type="VoiceTranscriptionTimeoutObserved",
                source=EventSource.INPUT_ADAPTER,
                payload={"speech_duration_ms": fact.speech_duration_ms},
                dedupe_key=f"livekit:transcription-timeout:{fact.worker_event_id}",
                correlation_id=session_id,
            ))
            return
        if isinstance(fact, UserSpeaking):
            state = self.application.snapshot(session_id)
            for speech_id, speech in sorted(state.speech.items()):
                if speech.state in (SpeechState.QUEUED, SpeechState.EMITTING):
                    await self.application.append(EventCandidate(
                        session_id=session_id, event_type="SpeechCancellationRequested",
                        source=EventSource.INPUT_ADAPTER, payload={"speech_id": speech_id},
                        dedupe_key=f"livekit:barge-in:{speech_id}", correlation_id=session_id,
                    ))
            return
        if isinstance(fact, PlayoutStarted):
            binding.output.started(generation, fact.speech_id)
            return
        if isinstance(fact, (PlayoutFinished, PlayoutFailed)):
            origin = binding.output.origin(generation, fact.speech_id)
            if isinstance(fact, PlayoutFinished):
                await self.application.output_finished(
                    session_id, fact.speech_id, heard=True, logical_time=0,
                    origin_event_id=origin,
                )
            else:
                await self.application.output_failed(
                    session_id, fact.speech_id,
                    failure=OutputPortFailure(fact.error_code, heard=fact.heard),
                    logical_time=0, origin_event_id=origin,
                )
            binding.output.retire_origin(generation, fact.speech_id)


async def serve_worker_transport(socket: WebSocket, transport: VoiceTransportRegistry,
                                 session_id: str) -> None:
    room = socket.headers.get("x-interlock-voice-room", "")
    credential = socket.headers.get("x-interlock-worker-secret", "")
    try:
        binding = transport.authenticate(session_id, room, credential)
    except (RuntimeError, ValueError):
        await socket.close(code=1008)
        return
    await socket.accept()
    try:
        generation = await transport.connect(binding, socket)
    except ValueError:
        await socket.close(code=1008)
        return
    try:
        while True:
            raw = await socket.receive_json()
            await transport.accept(binding, generation, raw)
            await binding.output.acknowledge(raw["worker_event_id"])
    except (ValidationError, ValueError, KeyError):
        await socket.close(code=1008)
    except WebSocketDisconnect:
        # A disconnect proves no playout outcome.
        pass
    finally:
        transport.disconnect(binding, generation)
