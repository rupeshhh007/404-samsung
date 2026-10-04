"""LiveKit Agents transport boundary for one isolated INTERLOCK conversation.

The adapter deliberately owns no domain state.  It translates LiveKit callbacks
to journal candidates, implements the runtime ``OutputPort`` with exact approved
text, and delegates every authoritative transition to ``Application``.
"""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Callable
from hashlib import sha256
from time import monotonic_ns
from typing import Any, Protocol, cast

from livekit.agents import AgentSession, UserInputTranscribedEvent, UserStateChangedEvent
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


ApplicationFactory = Callable[[OutputPort], Application]


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
        self._spawn(self.accept_transcript(
            transcript=event.transcript,
            final=event.is_final,
            item_id=getattr(event, "item_id", None),
            created_at=getattr(event, "created_at", None),
        ))

    def _on_user_state(self, event: UserStateChangedEvent | Any) -> None:
        if getattr(event, "new_state", None) == "speaking":
            self._spawn(self.request_barge_in())

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
        received_ns = monotonic_ns()
        identity = _stable_id(item_id, transcript, final, created_at)
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
        self._spawn(self._observe_full_playout(speech_id, handle))

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

    async def close(self) -> SessionState:
        """Stop intake, detach LiveKit, quiesce tasks, then retire runtime state."""

        if not self._started or self._closed:
            raise RuntimeError("voice conversation is not active")
        self._accepting = False
        if self._listeners_bound:
            self._livekit.off("user_input_transcribed", self._transcript_listener)
            self._livekit.off("user_state_changed", self._user_state_listener)
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
        # Active speech with unknown audible status is deliberately not guessed.
        # The caller must provide output_finished/output_failed before teardown.
        if self._output_origins:
            raise RuntimeError("voice output terminal status is unresolved")
        final = await self.application.close_session(self.session_id)
        self._handles.clear()
        self._closed = True
        return final


__all__ = ["LiveKitSessionAdapter"]
