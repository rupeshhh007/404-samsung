"""LiveKit Agents transport boundary for one isolated INTERLOCK conversation.

The adapter deliberately owns no domain state.  It translates LiveKit callbacks
to journal candidates, implements the runtime ``OutputPort`` with exact approved
text, and delegates every authoritative transition to ``Application``.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from hashlib import sha256
from time import monotonic_ns
from typing import Any, Protocol, cast
from uuid import uuid4

from livekit.agents import Agent, AgentServer, AgentSession, UserInputTranscribedEvent, UserStateChangedEvent
from livekit.agents.voice import SpeechHandle

from interlock.config import Settings
from interlock.domain.enums import EventSource, SpeechState
from interlock.domain.models import EventEnvelope, SessionState
from interlock.main import Application, RuntimeDependencies
from interlock.runtime.journal import EventCandidate
from interlock.truth.speech import OutputPort, OutputPortFailure


class _LiveKitSession(Protocol):
    """The verified AgentSession surface used by this adapter and its fakes."""

    def on(self, event: str, callback: Callable[[Any], None] | None = None) -> Callable[..., Any]: ...
    def off(self, event: str, callback: Callable[[Any], None]) -> None: ...
    def say(
        self, text: str, *, allow_interruptions: bool, add_to_chat_ctx: bool
    ) -> SpeechHandle: ...
    async def aclose(self) -> None: ...
    @property
    def current_speech(self) -> Any: ...
    @property
    def agent_state(self) -> str: ...



ApplicationFactory = Callable[[OutputPort], Application]


@dataclass(frozen=True)
class VoiceProviders:
    """Per-room provider ports supplied by deployment, never by LiveKit policy."""

    stt: Any
    tts: Any
    dependencies: RuntimeDependencies
    vad: Any = None


def compose_voice_room(
    session_id: str, providers: VoiceProviders, *, settings: Settings
) -> tuple[AgentSession[Any], LiveKitSessionAdapter, Agent]:
    """Create one transport and one authoritative INTERLOCK session per room.

    LiveKit has no LLM or tools here: transcript interpretation and all output
    decisions belong to INTERLOCK; LiveKit only transcribes and plays exact text.
    """

    if providers.stt is None or providers.tts is None:
        raise ValueError("voice deployment requires explicit STT and TTS providers")
    if not session_id:
        raise ValueError("voice room identity must be nonempty")
    session = AgentSession(stt=providers.stt, tts=providers.tts, vad=providers.vad, llm=None)
    adapter = LiveKitSessionAdapter(
        session,
        session_id=session_id,
        application_factory=lambda output: Application(
            settings=settings,
            dependencies=replace(providers.dependencies, output=output),
        ),
    )
    agent = Agent(instructions="INTERLOCK transport only; responses are externally approved.", llm=None, tools=[])
    return session, adapter, agent


def run_livekit_voice_agent(
    provider_factory: Callable[[Any], VoiceProviders], *, settings: Settings
) -> None:
    """Run a normal LiveKit worker with provider construction at its outer edge.

    The deployment supplies fresh STT/TTS and INTERLOCK inward ports for each
    job. No credentials, vendor selection, or model-side tool calls live here.
    """

    if settings.INTERLOCK_MODE != "LIVE":
        raise ValueError("voice worker requires INTERLOCK_MODE=LIVE")
    missing = [name for name in ("LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET")
               if not os.environ.get(name, "").strip()]
    if missing:
        raise RuntimeError("voice worker requires " + ", ".join(missing))

    server = AgentServer()

    @server.rtc_session()
    async def entrypoint(ctx: Any) -> None:
        session, adapter, agent = compose_voice_room(
            ctx.room.name, provider_factory(ctx), settings=settings
        )
        await adapter.start()
        ctx.add_shutdown_callback(lambda _reason="": adapter.close())
        await session.start(room=ctx.room, agent=agent)

    from livekit import agents

    agents.cli.run_app(server)


def _stable_id(*parts: object) -> str:
    return sha256(repr(parts).encode()).hexdigest()


class LiveKitSessionAdapter(OutputPort):
    """Transport one LiveKit conversation through one fresh Application.

    ``AgentSession.start`` stays with the deployment entrypoint because it needs
    provider-specific Agent/room configuration.  ``start`` here creates the
    isolated INTERLOCK session and binds the documented LiveKit events.
    """

    def __init__(
        self,
        livekit_session: AgentSession[Any] | _LiveKitSession,
        *,
        session_id: str,
        application_factory: ApplicationFactory | None = None,
        max_background_tasks: int = 64,
    ) -> None:
        if not session_id:
            raise ValueError("session_id must be nonempty")
        if type(max_background_tasks) is not int or max_background_tasks < 1:
            raise ValueError("max_background_tasks must be positive")
        self._livekit = cast(_LiveKitSession, livekit_session)
        self.session_id = session_id
        self._max_background_tasks = max_background_tasks
        self._tasks: set[asyncio.Task[Any]] = set()
        self._task_failures: deque[str] = deque(maxlen=max_background_tasks)
        self._handles: dict[str, SpeechHandle] = {}
        self._output_origins: dict[str, str] = {}
        self._accepting = False
        self._started = False
        self._closed = False
        self._listeners_bound = False
        self._livekit_closed = False
        self._transcript_listener: Callable[[Any], None] = self._on_transcript
        self._user_state_listener: Callable[[Any], None] = self._on_user_state
        self._timing_samples_ms: dict[str, deque[float]] = {
            "transcript_accept": deque(maxlen=max_background_tasks),
            "barge_in_request": deque(maxlen=max_background_tasks),
        }
        self._start_timeout_s = 5.0
        self._start_waiters: dict[str, asyncio.Event] = {}
        self._agent_state_listener: Callable[[Any], None] = self._on_agent_state
        factory = application_factory or (
            lambda output: Application(
                settings=Settings(), dependencies=RuntimeDependencies(output=output)
            )
        )
        self.application = factory(self)

    async def start(self, *, logical_time: int = 0) -> SessionState:
        if self._started or self._closed:
            raise RuntimeError("voice conversation cannot be started twice")
        state = await self.application.start_session(
            self.session_id, logical_time=logical_time
        )
        self._livekit.on("user_input_transcribed", self._transcript_listener)
        self._livekit.on("user_state_changed", self._user_state_listener)
        try:
            self._livekit.on("agent_state_changed", self._agent_state_listener)
        except Exception:
            pass
        self._listeners_bound = True
        self._accepting = True
        self._started = True
        return state

    def _spawn(self, awaitable: Any) -> None:
        if self._closed:
            if hasattr(awaitable, "close"):
                awaitable.close()
            return
        if len(self._tasks) >= self._max_background_tasks:
            if hasattr(awaitable, "close"):
                awaitable.close()
            self._accepting = False
            raise RuntimeError("LiveKit callback capacity exhausted")
        task = asyncio.create_task(awaitable)
        self._tasks.add(task)
        task.add_done_callback(self._task_done)

    def _task_done(self, task: asyncio.Task[Any]) -> None:
        self._tasks.discard(task)
        if task.cancelled():
            return
        failure = task.exception()
        if failure is not None:
            # Consume the exception so callback failures cannot become an
            # unobserved task warning.  Keep only a bounded, non-sensitive type.
            self._task_failures.append(type(failure).__name__)
            self._accepting = False

    def _on_transcript(self, event: UserInputTranscribedEvent | Any) -> None:
        if isinstance(event.transcript, str) and not event.transcript.strip():
            return
        self._spawn(self.accept_transcript(
            transcript=event.transcript,
            final=event.is_final,
            item_id=getattr(event, "item_id", None),
            created_at=getattr(event, "created_at", None),
        ))

    def _on_user_state(self, event: UserStateChangedEvent | Any) -> None:
        if getattr(event, "new_state", None) == "speaking":
            self._spawn(self.request_barge_in())

    def _on_agent_state(self, event: Any) -> None:
        if getattr(event, "new_state", None) == "speaking":
            current = getattr(self._livekit, "current_speech", None)
            if current is not None:
                for speech_id, waiter in tuple(self._start_waiters.items()):
                    handle = self._handles.get(speech_id)
                    if handle is not None and (
                        current is handle
                        or (
                            getattr(current, "id", None) is not None
                            and getattr(current, "id", None) == getattr(handle, "id", None)
                        )
                    ):
                        if not waiter.is_set():
                            waiter.set()



    async def accept_transcript(
        self,
        *,
        transcript: str,
        final: bool,
        item_id: str | None = None,
        created_at: float | None = None,
    ) -> EventEnvelope:
        """Append one partial/final transcript; acceptance never means completion."""

        if not self._started or not self._accepting or self._closed:
            raise RuntimeError("voice intake is closed")
        if type(final) is not bool:
            raise TypeError("final must be a boolean")
        if not isinstance(transcript, str):
            raise TypeError("transcript must be text")
        if not transcript.strip():
            raise ValueError("transcript must contain speech text")
        received_ns = monotonic_ns()
        identity = (_stable_id(item_id, transcript, final)
                    if item_id is not None else _stable_id(transcript, final, created_at))
        evidence_id = f"voice-{identity}"
        event = await self.application.append(EventCandidate(
            session_id=self.session_id,
            event_type="TranscriptHypothesisObserved",
            source=EventSource.INPUT_ADAPTER,
            payload={"evidence_id": evidence_id, "text": transcript, "final": final},
            logical_time=max(0, int(created_at * 1000)) if created_at is not None else 0,
            correlation_id=self.session_id,
            dedupe_key=f"livekit:transcript:{identity}",
        ))
        self._timing_samples_ms["transcript_accept"].append(
            (monotonic_ns() - received_ns) / 1_000_000
        )
        return event

    async def request_barge_in(self) -> tuple[EventEnvelope, ...]:
        """Request speech cancellation without touching operation cancellation."""

        if not self._started or not self._accepting or self._closed:
            return ()
        started_ns = monotonic_ns()
        state = self.application.snapshot(self.session_id)
        accepted: list[EventEnvelope] = []
        for speech_id, speech in sorted(state.speech.items()):
            if speech.state not in (SpeechState.QUEUED, SpeechState.EMITTING):
                continue
            accepted.append(await self.application.append(EventCandidate(
                session_id=self.session_id,
                event_type="SpeechCancellationRequested",
                source=EventSource.INPUT_ADAPTER,
                payload={"speech_id": speech_id},
                correlation_id=self.session_id,
                dedupe_key=f"livekit:barge-in:{speech_id}",
            )))
        if accepted:
            self._timing_samples_ms["barge_in_request"].append(
                (monotonic_ns() - started_ns) / 1_000_000
            )
        return tuple(accepted)

    async def emit(
        self, *, session_id: str, speech_id: str, rendered_text: str
    ) -> None:
        if session_id != self.session_id or self._closed:
            raise OutputPortFailure("LIVEKIT_SESSION_MISMATCH", heard=False)
        if speech_id in self._handles:
            return
        origins = [
            event.event_id
            for event in self.application.events(self.session_id)
            if event.event_type == "SpeechQueued"
            and event.payload.get("speech_id") == speech_id
        ]
        if not origins:
            # No transport I/O has happened, so unheard is known rather than
            # inferred from an ambiguous LiveKit failure.
            raise OutputPortFailure("LIVEKIT_OUTPUT_LINEAGE_MISSING", heard=False)
        if len(self._tasks) >= self._max_background_tasks:
            raise OutputPortFailure("LIVEKIT_OUTPUT_CAPACITY", heard=False)

        # ``say`` receives exactly the persisted TRUTHLOCK text.  Disabling chat
        # insertion also prevents a LiveKit LLM from treating it as rewrite input.
        handle = self._livekit.say(
            rendered_text, allow_interruptions=True, add_to_chat_ctx=False
        )
        self._handles[speech_id] = handle
        self._output_origins[speech_id] = origins[-1]

        start_event = asyncio.Event()
        self._start_waiters[speech_id] = start_event

        # Check if this specific handle is already established as the active speech
        current = getattr(self._livekit, "current_speech", None)
        if current is not None and (
            current is handle
            or (
                getattr(current, "id", None) is not None
                and getattr(current, "id", None) == getattr(handle, "id", None)
            )
        ):
            if getattr(self._livekit, "agent_state", None) in ("speaking", None):
                start_event.set()

        self._spawn(self._observe_full_playout(speech_id, handle))

        try:
            await self._wait_for_start_signal(speech_id, handle, start_event)
        finally:
            self._start_waiters.pop(speech_id, None)

    async def _wait_for_start_signal(
        self, speech_id: str, handle: SpeechHandle, start_event: asyncio.Event
    ) -> None:
        if start_event.is_set():
            return

        wait_tasks: list[asyncio.Task[Any]] = [
            asyncio.create_task(start_event.wait())
        ]
        if hasattr(handle, "wait_for_start"):
            async def _from_handle() -> None:
                try:
                    await handle.wait_for_start()
                    start_event.set()
                except Exception:
                    pass
            wait_tasks.append(asyncio.create_task(_from_handle()))

        async def _from_session() -> None:
            while not start_event.is_set():
                cur = getattr(self._livekit, "current_speech", None)
                if cur is not None and (
                    cur is handle
                    or (
                        getattr(cur, "id", None) is not None
                        and getattr(cur, "id", None) == getattr(handle, "id", None)
                    )
                ):
                    state = getattr(self._livekit, "agent_state", None)
                    if state in ("speaking", None):
                        start_event.set()
                        break
                await asyncio.sleep(0.01)
        wait_tasks.append(asyncio.create_task(_from_session()))


        early_finish = asyncio.Event()
        async def _watch_early_finish() -> None:
            try:
                if hasattr(handle, "wait_for_playout"):
                    await handle.wait_for_playout()
                elif hasattr(handle, "done"):
                    while not handle.done():
                        await asyncio.sleep(0.01)
                early_finish.set()
            except (asyncio.CancelledError, Exception):
                pass
        wait_tasks.append(asyncio.create_task(_watch_early_finish()))

        done, pending = await asyncio.wait(
            wait_tasks,
            timeout=self._start_timeout_s,
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)

        if start_event.is_set():
            return

        if early_finish.is_set():
            exception = handle.exception() if hasattr(handle, "exception") else None
            interrupted = getattr(handle, "interrupted", False)
            if exception is None and not interrupted:
                # Early successful playout completion proves output started and played.
                start_event.set()
                return
            # Ambiguous playout failure or interruption before start was confirmed.
            # Successful playout is not evidence of unheard audio, and interrupted
            # speech may have been partially heard; do not invent heard=False.
            self._handles.pop(speech_id, None)
            self._output_origins.pop(speech_id, None)
            raise RuntimeError("voice output playout failed or was interrupted before start")

        self._handles.pop(speech_id, None)
        self._output_origins.pop(speech_id, None)
        if hasattr(handle, "interrupt") and not (hasattr(handle, "done") and handle.done()):
            handle.interrupt(force=False)
        raise OutputPortFailure("LIVEKIT_OUTPUT_START_TIMEOUT", heard=False)

    async def _observe_full_playout(
        self, speech_id: str, handle: SpeechHandle
    ) -> None:
        try:
            await handle.wait_for_playout()
        except Exception:
            # LiveKit exceptions do not prove whether audio was heard.  The host
            # must call ``output_failed`` with an explicit observed heard value.
            return
        if getattr(handle, "interrupted", False):
            return
        exception = handle.exception() if hasattr(handle, "exception") else None
        if exception is None and speech_id in self._output_origins:
            await self.output_finished(speech_id=speech_id, heard=True)

    async def cancel(self, *, session_id: str, speech_id: str) -> None:
        if session_id != self.session_id:
            raise OutputPortFailure("LIVEKIT_SESSION_MISMATCH", heard=False)
        handle = self._handles.get(speech_id)
        if handle is not None and not handle.done():
            handle.interrupt(force=False)

    async def output_finished(self, *, speech_id: str, heard: bool) -> EventEnvelope:
        """Record a terminal playout observation with explicit audible truth."""

        origin = self._output_origins[speech_id]
        event = await self.application.output_finished(
            self.session_id,
            speech_id,
            heard=heard,
            logical_time=0,
            origin_event_id=origin,
        )
        self._output_origins.pop(speech_id, None)
        self._handles.pop(speech_id, None)
        return event

    async def output_failed(
        self,
        *,
        speech_id: str,
        error_code: str,
        heard: bool,
        retryable: bool = False,
    ) -> EventEnvelope:
        """Record a typed failure only when the transport observed ``heard``."""

        origin = self._output_origins[speech_id]
        event = await self.application.output_failed(
            self.session_id,
            speech_id,
            failure=OutputPortFailure(
                error_code, heard=heard, retryable=retryable
            ),
            logical_time=0,
            origin_event_id=origin,
        )
        self._output_origins.pop(speech_id, None)
        self._handles.pop(speech_id, None)
        return event

    def measurements(self) -> dict[str, tuple[float, ...]]:
        """Return only samples actually observed by this conversation."""

        return {
            name: tuple(values)
            for name, values in self._timing_samples_ms.items()
            if values
        }

    def callback_failures(self) -> tuple[str, ...]:
        """Return bounded failure classifications without raw exception text."""

        return tuple(self._task_failures)

    async def close(
        self,
        *,
        terminal_observations: Mapping[str, bool | OutputPortFailure] | None = None,
    ) -> SessionState:
        """Stop intake, detach LiveKit, quiesce tasks, then retire runtime state."""

        if not self._started or self._closed:
            raise RuntimeError("voice conversation is not active")

        # Accept explicit truthful terminal observations before teardown.
        if terminal_observations:
            for speech_id, obs in terminal_observations.items():
                if speech_id in self._output_origins:
                    if isinstance(obs, OutputPortFailure):
                        await self.output_failed(
                            speech_id=speech_id,
                            error_code=obs.error_code,
                            heard=obs.heard,
                            retryable=obs.retryable,
                        )
                    elif isinstance(obs, bool):
                        if obs:
                            await self.output_finished(speech_id=speech_id, heard=True)
                        else:
                            await self.output_failed(
                                speech_id=speech_id,
                                error_code="LIVEKIT_INTERRUPTED",
                                heard=False,
                            )

        # Must not irreversibly destroy transport while output truth remains unresolved.
        if self._output_origins:
            raise RuntimeError("voice output terminal status is unresolved")

        self._accepting = False
        if self._listeners_bound:
            self._livekit.off("user_input_transcribed", self._transcript_listener)
            self._livekit.off("user_state_changed", self._user_state_listener)
            try:
                self._livekit.off("agent_state_changed", self._agent_state_listener)
            except Exception:
                pass
            self._listeners_bound = False
        for handle in tuple(self._handles.values()):
            if not handle.done():
                handle.interrupt(force=False)
        if not self._livekit_closed:
            await self._livekit.aclose()
            self._livekit_closed = True
        if self._tasks:
            done, pending = await asyncio.wait(tuple(self._tasks), timeout=1.0)
            del done
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)

        final = await self.application.close_session(self.session_id)
        self._handles.clear()
        self._closed = True
        return final


__all__ = ["LiveKitSessionAdapter", "VoiceProviders", "compose_voice_room", "run_livekit_voice_agent"]


class BrowserVoiceWorkerTransport:
    """LiveKit audio endpoint; never constructs Application or SessionState."""

    def __init__(self, session: AgentSession[Any], *, room_name: str,
                 backend_ws_url: str, worker_secret: str) -> None:
        if not room_name.startswith("voice-") or len(room_name) <= len("voice-"):
            raise ValueError("unbound browser voice room")
        self.session = session
        self.room_name = room_name
        self.session_id = room_name[len("voice-"):]
        self.backend_ws_url = backend_ws_url.rstrip("/")
        self.worker_secret = worker_secret
        self._socket: Any = None
        self._send_lock = asyncio.Lock()
        self._tasks: set[asyncio.Task[Any]] = set()
        self._handles: dict[str, SpeechHandle] = {}
        self._closed = False

    async def connect(self) -> None:
        import websockets

        url = f"{self.backend_ws_url}/internal/voice/{self.session_id}/transport"
        self._socket = await websockets.connect(
            url,
            additional_headers={
                "x-interlock-voice-room": self.room_name,
                "x-interlock-worker-secret": self.worker_secret,
            },
            max_size=65_536,
        )
        self.session.on("user_input_transcribed", self._on_transcript)
        self.session.on("user_state_changed", self._on_user_state)
        self._spawn(self._read())

    def _spawn(self, awaitable: Any) -> None:
        if self._closed:
            awaitable.close()
            return
        if len(self._tasks) >= 64:
            awaitable.close()
            raise RuntimeError("browser voice worker capacity exhausted")
        task = asyncio.create_task(awaitable)
        self._tasks.add(task)
        task.add_done_callback(self._task_done)

    def _task_done(self, task: asyncio.Task[Any]) -> None:
        self._tasks.discard(task)
        if not task.cancelled():
            failure = task.exception()
            if failure is not None:
                self._closed = True

    async def _send(self, fact: dict[str, Any]) -> None:
        if self._socket is None or self._closed:
            raise RuntimeError("browser voice transport is disconnected")
        async with self._send_lock:
            await self._socket.send(json.dumps({"worker_event_id": uuid4().hex, **fact}))

    def _on_transcript(self, event: Any) -> None:
        text = getattr(event, "transcript", None)
        if not isinstance(text, str) or not text.strip():
            return
        self._spawn(self._send({
            "type": "TRANSCRIPT", "item_id": getattr(event, "item_id", None),
            "text": text, "final": bool(event.is_final),
            "created_at": getattr(event, "created_at", None),
        }))

    def _on_user_state(self, event: Any) -> None:
        if getattr(event, "new_state", None) == "speaking":
            self._spawn(self._send({"type": "USER_SPEAKING"}))

    async def _read(self) -> None:
        async for raw in self._socket:
            message = json.loads(raw)
            if message.get("type") == "ACK":
                continue
            if message.get("type") == "SPEAK" and set(message) == {"type", "speech_id", "rendered_text"}:
                self._spawn(self._speak(message["speech_id"], message["rendered_text"]))
            elif message.get("type") == "CANCEL_SPEECH" and set(message) == {"type", "speech_id"}:
                handle = self._handles.get(message["speech_id"])
                if handle is not None and not handle.done():
                    handle.interrupt(force=True)
            else:
                raise RuntimeError("invalid backend voice command")
        self._closed = True

    async def _speak(self, speech_id: str, rendered_text: str) -> None:
        if speech_id in self._handles or not isinstance(rendered_text, str):
            return
        # The backend supplies the exact persisted TRUTHLOCK text. No LLM,
        # rewrite, chat-context insertion, or worker-side business decision.
        # Interruption is managed authoritatively by INTERLOCK backend cancellation;
        # disable autonomous LiveKit VAD/audio-activity interruptions to prevent speaker echo cutoffs.
        handle = self.session.say(
            rendered_text, allow_interruptions=False, add_to_chat_ctx=False,
        )
        self._handles[speech_id] = handle
        started = False
        try:
            await self._wait_for_start(handle)
            await self._send({"type": "PLAYOUT_STARTED", "speech_id": speech_id})
            started = True
            await handle.wait_for_playout()
        except Exception:
            if not started or not getattr(handle, "interrupted", False):
                # A pre-start interruption, timeout, or transport loss does not
                # prove that the browser heard nothing.
                return
        if getattr(handle, "interrupted", False):
            try:
                await self._send({
                    "type": "PLAYOUT_FAILED", "speech_id": speech_id,
                    "error_code": "LIVEKIT_INTERRUPTED", "heard": True,
                })
            except Exception:
                # The backend cannot infer delivery from a broken socket.
                pass
            return
        try:
            if handle.exception() is None:
                await self._send({"type": "PLAYOUT_FINISHED", "speech_id": speech_id, "heard": True})
        except Exception:
            # An unrelated failure does not establish a terminal heard value.
            return

    async def _wait_for_start(self, handle: SpeechHandle) -> None:
        async def active() -> None:
            while True:
                current = getattr(self.session, "current_speech", None)
                if current is handle or (
                    current is not None and getattr(current, "id", None) is not None
                    and getattr(current, "id", None) == getattr(handle, "id", None)
                ):
                    if getattr(self.session, "agent_state", None) in ("speaking", None):
                        return
                await asyncio.sleep(0.01)

        poll = asyncio.create_task(active())
        playout = asyncio.create_task(handle.wait_for_playout())
        try:
            done, _ = await asyncio.wait({poll, playout}, timeout=5.0,
                                         return_when=asyncio.FIRST_COMPLETED)
            if poll in done and poll.exception() is None:
                return
            if playout in done and playout.exception() is None and not handle.interrupted \
                    and handle.exception() is None:
                return  # successful full playout also proves a start
            raise RuntimeError("voice playout start not established")
        finally:
            for task in (poll, playout):
                if not task.done():
                    task.cancel()
            await asyncio.gather(poll, playout, return_exceptions=True)

    async def close(self, _reason: str = "") -> None:
        self._closed = True
        for handle in tuple(self._handles.values()):
            if not handle.done():
                handle.interrupt(force=True)
        for task in tuple(self._tasks):
            task.cancel()
        await asyncio.gather(*tuple(self._tasks), return_exceptions=True)
        if self._socket is not None:
            await self._socket.close()
        await self.session.aclose()


def _browser_stt_options() -> dict[str, Any]:
    """Return accuracy-first Deepgram tuning for the browser voice demo.

    Nova-3 defaults to very aggressive endpointing.  A longer endpoint keeps
    mid-thought pauses such as "actually ... book twelve" inside one utterance,
    while smart formatting/numerals reduce word-vs-digit variation before the
    deterministic semantic boundary sees the final transcript.
    """

    language = os.environ.get("INTERLOCK_VOICE_STT_LANGUAGE", "en-IN").strip() or "en-IN"
    configured = os.environ.get(
        "INTERLOCK_VOICE_STT_KEYTERMS",
        "book,appointment,eleven,twelve,noon,midday,actually,reschedule,change,move,"
        "book twelve,make it twelve,actually book twelve",
    )
    keyterms = [term.strip() for term in configured.split(",") if term.strip()]
    endpointing_ms = int(os.environ.get("INTERLOCK_VOICE_STT_ENDPOINTING_MS", "500"))
    utterance_end_ms = int(os.environ.get("INTERLOCK_VOICE_STT_UTTERANCE_END_MS", "1000"))
    if not 100 <= endpointing_ms <= 2000:
        raise RuntimeError("INTERLOCK_VOICE_STT_ENDPOINTING_MS must be 100..2000")
    if not 1000 <= utterance_end_ms <= 5000:
        raise RuntimeError("INTERLOCK_VOICE_STT_UTTERANCE_END_MS must be 1000..5000")
    return {
        "language": language,
        "keyterm": keyterms,
        "interim_results": True,
        "punctuate": True,
        "smart_format": True,
        "numerals": True,
        "filler_words": False,
        "endpointing_ms": endpointing_ms,
        "utterance_end_ms": utterance_end_ms,
    }


async def _browser_voice_entrypoint(ctx: Any) -> None:
    from livekit.plugins import cartesia, deepgram, silero

    stt_model = os.environ.get("INTERLOCK_VOICE_STT_MODEL", "nova-3")
    tts_model = os.environ.get("INTERLOCK_VOICE_TTS_MODEL", "sonic-3")
    manual_turn_handling = {"turn_detection": "manual", "interruption": {"enabled": False}}
    session = AgentSession(
        stt=deepgram.STT(
            model=stt_model,
            api_key=os.environ["DEEPGRAM_API_KEY"],
            **_browser_stt_options(),
        ),
        tts=cartesia.TTS(model=tts_model, voice=os.environ["INTERLOCK_VOICE_TTS_VOICE_ID"],
                         api_key=os.environ["CARTESIA_API_KEY"]),
        vad=silero.VAD.load(), llm=None,
        transcription_timeout=2.5,
        turn_handling=manual_turn_handling,
    )
    transport = BrowserVoiceWorkerTransport(
        session, room_name=ctx.room.name,
        backend_ws_url=os.environ["INTERLOCK_VOICE_BACKEND_WS_URL"],
        worker_secret=os.environ["INTERLOCK_VOICE_WORKER_SECRET"],
    )
    await transport.connect()
    ctx.add_shutdown_callback(transport.close)
    await session.start(room=ctx.room, agent=Agent(
        instructions="INTERLOCK transport only; no model-side actions.", llm=None, tools=[],
        turn_handling=manual_turn_handling,
    ))


def run_browser_voice_worker() -> None:
    """Run the browser-only transport worker; backend retains all authority."""

    required = (
        "LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET",
        "INTERLOCK_VOICE_WORKER_SECRET", "INTERLOCK_VOICE_BACKEND_WS_URL",
        "DEEPGRAM_API_KEY", "CARTESIA_API_KEY", "INTERLOCK_VOICE_TTS_VOICE_ID",
    )
    missing = [name for name in required if not os.environ.get(name, "").strip()]
    if missing:
        raise RuntimeError("browser voice worker requires " + ", ".join(missing))
    from livekit import agents

    server = AgentServer()
    server.rtc_session(_browser_voice_entrypoint)
    agents.cli.run_app(server)


__all__.extend(["BrowserVoiceWorkerTransport", "run_browser_voice_worker", "_browser_voice_entrypoint"])


if __name__ == "__main__":
    if not sys.argv[1:] or sys.argv[1] != "browser-worker":
        raise SystemExit("usage: python -m interlock.adapters.livekit_agent browser-worker start")
    sys.argv = [sys.argv[0], *sys.argv[2:]]
    run_browser_voice_worker()
