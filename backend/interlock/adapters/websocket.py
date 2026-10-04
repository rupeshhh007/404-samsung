"""Bounded, read-only WebSocket projections for API-002.

The hub consumes reducer-issued ``PublishProjection`` commands and reads only
detached, sequence-pinned Application state.  It is transport bookkeeping, not
an authoritative state store: acknowledgements, reconnect cursors, subscriber
queues, and retained deltas never feed the reducer.
"""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Awaitable, Callable, Mapping
from copy import deepcopy
from dataclasses import dataclass, field
import json
import re
from typing import Any, Protocol, TYPE_CHECKING
from urllib.parse import parse_qs, quote

from interlock.domain.models import EventEnvelope, SessionState
from interlock.runtime.commands import BaseCommand, PublishProjection
from interlock.runtime.dispatcher import DispatchContext

if TYPE_CHECKING:
    from interlock.main import Application


SCHEMA_VERSION = 1
STREAM_PATH = "/api/v1/sessions/{session_id}/stream"
_STREAM_RE = re.compile(r"^/api/v1/sessions/([^/]+)/stream$")
_COLLECTIONS = (
    "operations", "effects", "evidence", "claims", "divergences", "plans", "speech",
)
_SENSITIVE_KEYS = ("password", "secret", "token", "api_key", "apikey", "credential", "cookie")


class ProjectionError(ValueError):
    """A projection violates session or sequence isolation."""


class WebSocketConnection(Protocol):
    async def accept(self) -> None: ...
    async def send_json(self, message: Mapping[str, Any]) -> None: ...
    async def receive_json(self) -> Any: ...
    async def close(self, code: int = 1000, reason: str = "") -> None: ...


def _safe(value: Any) -> Any:
    """Return a detached JSON-safe value with credential-shaped fields redacted."""

    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    if isinstance(value, Mapping):
        safe: dict[str, Any] = {}
        for key, item in value.items():
            name = str(key)
            folded = name.casefold()
            safe[name] = "[REDACTED]" if any(part in folded for part in _SENSITIVE_KEYS) else _safe(item)
        return safe
    if isinstance(value, (list, tuple)):
        return [_safe(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def project_state(state: SessionState) -> dict[str, Any]:
    """Build the canonical detached transport projection from reducer state."""

    detached = state.model_copy(deep=True)
    node = detached.intents.get(detached.active_intent_id) if detached.active_intent_id else None
    active_revision = detached.revisions.get(node.active_revision_id) if node and node.active_revision_id else None
    intent = None
    if node is not None:
        intent = _safe(node)
        intent["active_revision"] = _safe(active_revision) if active_revision is not None else None

    projection: dict[str, Any] = {"intent": intent}
    for name in _COLLECTIONS:
        records = getattr(detached, name)
        projection[name] = [_safe(records[key]) for key in sorted(records)]
    projection["metrics"] = _safe(detached.metrics)
    return deepcopy(projection)


def snapshot_message(state: SessionState) -> dict[str, Any]:
    return {
        "type": "snapshot",
        "schema_version": SCHEMA_VERSION,
        "session_id": state.session_id,
        "through_sequence": state.last_sequence,
        "projection": project_state(state),
    }


def _ids(items: list[dict[str, Any]], category: str) -> set[str]:
    singular = {"evidence": "evidence_id", "speech": "speech_id"}.get(category, f"{category[:-1]}_id")
    return {str(item[singular]) for item in items if singular in item}


def _delta(previous: Mapping[str, Any], current: Mapping[str, Any], sequence: int) -> dict[str, Any]:
    changed: dict[str, Any] = {}
    removed: dict[str, list[str]] = {}
    if previous.get("intent") != current.get("intent"):
        changed["intent"] = deepcopy(current.get("intent"))
        old = previous.get("intent")
        new = current.get("intent")
        if isinstance(old, Mapping) and (not isinstance(new, Mapping) or old.get("intent_id") != new.get("intent_id")):
            removed["intent"] = [str(old.get("intent_id"))]
    for category in _COLLECTIONS:
        old_items = list(previous.get(category, []))
        new_items = list(current.get(category, []))
        if old_items != new_items:
            changed[category] = deepcopy(new_items)
            deleted = sorted(_ids(old_items, category) - _ids(new_items, category))
            if deleted:
                removed[category] = deleted
    if previous.get("metrics") != current.get("metrics"):
        changed["metrics"] = deepcopy(current.get("metrics", {}))
    return {"through_sequence": sequence, "changed": changed, "removed": removed}


def event_message(
    event: EventEnvelope,
    previous_projection: Mapping[str, Any],
    current_projection: Mapping[str, Any],
) -> dict[str, Any]:
    delta = _delta(previous_projection, current_projection, event.sequence)
    return {
        "type": "event",
        "schema_version": SCHEMA_VERSION,
        "session_id": event.session_id,
        "sequence": event.sequence,
        "event_type": event.event_type,
        "projection_delta": delta,
        "trace": {"correlation_id": event.correlation_id or event.event_id},
    }


def _resync(session_id: str) -> dict[str, Any]:
    return {
        "type": "resync_required",
        "reason": "GAP_OR_EXPIRED",
        "snapshot_url": f"/api/v1/sessions/{quote(session_id, safe='')}",
    }


@dataclass(eq=False)
class ProjectionSubscription:
    """One bounded, session-confined transport cursor."""

    session_id: str
    queue: asyncio.Queue[dict[str, Any]]
    applied_sequence: int
    enqueued_sequence: int
    paused_for_resync: bool = False
    closed: bool = False

    async def receive(self) -> dict[str, Any]:
        return deepcopy(await self.queue.get())

    def acknowledge(self, through_sequence: int) -> None:
        if type(through_sequence) is not int or through_sequence < 0:
            raise ProjectionError("ack sequence must be a non-negative integer")
        if through_sequence > self.enqueued_sequence:
            raise ProjectionError("ack sequence exceeds delivered progress")
        self.applied_sequence = max(self.applied_sequence, through_sequence)


@dataclass
class _SessionProjection:
    history: deque[dict[str, Any]]
    last_sequence: int = 0
    projection: dict[str, Any] | None = None
    event_ids: dict[int, str] = field(default_factory=dict)
    pending: dict[int, tuple[EventEnvelope, SessionState]] = field(default_factory=dict)


class ProjectionHub:
    """Bounded projection history and subscriber fan-out, scoped by session."""

    def __init__(
        self,
        *,
        history_limit: int = 256,
        subscriber_buffer: int = 64,
        max_sessions: int = 128,
        max_subscribers: int = 512,
    ) -> None:
        if type(history_limit) is not int or history_limit < 1:
            raise ValueError("history_limit must be positive")
        if type(subscriber_buffer) is not int or subscriber_buffer < 1:
            raise ValueError("subscriber_buffer must be positive")
        if type(max_sessions) is not int or max_sessions < 1:
            raise ValueError("max_sessions must be positive")
        if type(max_subscribers) is not int or max_subscribers < 1:
            raise ValueError("max_subscribers must be positive")
        self.history_limit = history_limit
        self.subscriber_buffer = subscriber_buffer
        self.max_sessions = max_sessions
        self.max_subscribers = max_subscribers
        self._application: Application | None = None
        self._sessions: dict[str, _SessionProjection] = {}
        self._subscribers: dict[str, set[ProjectionSubscription]] = {}
        self._lock = asyncio.Lock()
        self._closed = False

    def bind(self, application: Application) -> None:
        if self._application is not None and self._application is not application:
            raise RuntimeError("projection hub is already bound")
        self._application = application

    async def handle_publish(self, command: BaseCommand, context: DispatchContext) -> None:
        if not isinstance(command, PublishProjection):
            raise TypeError("projection handler requires PublishProjection")
        if context.origin_session_id != command.session_id:
            raise ProjectionError("projection context crosses session boundary")
        application = self._require_application()
        current = application.snapshot(command.session_id)
        events = [event for event in application.events(command.session_id) if event.sequence <= command.sequence]
        if not events or events[-1].sequence != command.sequence:
            await self.require_resync(command.session_id)
            return
        event = events[-1]
        if current.last_sequence == command.sequence:
            state = current
        elif [item.sequence for item in events] == list(range(1, command.sequence + 1)):
            state = application.replay(events)
        else:
            await self.require_resync(command.session_id)
            return
        await self.publish(event, state)

    async def publish(self, event: EventEnvelope, state: SessionState) -> bool:
        """Publish one pinned projection; duplicates are ignored and gaps resync."""

        event = event.model_copy(deep=True)
        state = state.model_copy(deep=True)
        if event.session_id != state.session_id:
            raise ProjectionError("event and projection belong to different sessions")
        if event.sequence != state.last_sequence:
            raise ProjectionError("projection is not pinned to the event sequence")
        async with self._lock:
            if self._closed:
                return False
            session = self._session_for_publish_locked(event.session_id)
            if event.sequence <= session.last_sequence:
                if session.event_ids.get(event.sequence) == event.event_id:
                    return False
                raise ProjectionError("sequence was reused for a different event")
            if event.sequence != session.last_sequence + 1:
                existing = session.pending.get(event.sequence)
                if existing is not None and existing[0].event_id != event.event_id:
                    raise ProjectionError("pending sequence was reused for a different event")
                if len(session.pending) >= self.history_limit and event.sequence not in session.pending:
                    session.pending.clear()
                else:
                    session.pending[event.sequence] = (event, state)
                self._require_resync_locked(event.session_id)
                return False
            self._publish_contiguous_locked(session, event, state)
            while session.last_sequence + 1 in session.pending:
                pending_event, pending_state = session.pending.pop(session.last_sequence + 1)
                self._publish_contiguous_locked(session, pending_event, pending_state)
            return True

    def _publish_contiguous_locked(
        self, session: _SessionProjection, event: EventEnvelope, state: SessionState,
    ) -> None:
        projection = project_state(state)
        previous = session.projection or {
            "intent": None,
            **{name: [] for name in _COLLECTIONS},
            "metrics": {},
        }
        message = event_message(event, previous, projection)
        session.history.append(deepcopy(message))
        session.event_ids[event.sequence] = event.event_id
        retained_sequences = {item["sequence"] for item in session.history}
        session.event_ids = {
            sequence: event_id for sequence, event_id in session.event_ids.items()
            if sequence in retained_sequences
        }
        session.last_sequence = event.sequence
        session.projection = deepcopy(projection)
        for subscriber in tuple(self._subscribers.get(event.session_id, ())):
            self._enqueue_event(subscriber, message)

    async def subscribe(
        self, session_id: str, *, after_sequence: int | None = None,
    ) -> ProjectionSubscription:
        application = self._require_application()
        subscriber = ProjectionSubscription(
            session_id=session_id,
            queue=asyncio.Queue(maxsize=self.subscriber_buffer),
            applied_sequence=after_sequence if type(after_sequence) is int and after_sequence >= 0 else 0,
            enqueued_sequence=after_sequence if type(after_sequence) is int and after_sequence >= 0 else 0,
        )
        async with self._lock:
            if self._closed:
                raise RuntimeError("projection hub is shut down")
            if sum(len(items) for items in self._subscribers.values()) >= self.max_subscribers:
                raise RuntimeError("projection subscriber capacity reached")
            # Publication uses the same lock.  Pinning the detached application
            # snapshot here prevents an event from landing between snapshot and
            # history selection and disappearing from both initial views.
            state = application.snapshot(session_id)
            if state.session_id != session_id:
                raise ProjectionError("snapshot crosses session boundary")
            session = self._sessions.get(session_id)
            usable = type(after_sequence) is int and 0 <= after_sequence <= state.last_sequence
            history = list(session.history) if session is not None else []
            pending = [item for item in history if item["sequence"] > after_sequence] if usable else []
            contiguous = (
                usable
                and (after_sequence == state.last_sequence or bool(pending))
                and [item["sequence"] for item in pending]
                == list(range(after_sequence + 1, state.last_sequence + 1))
            )
            if contiguous:
                for message in pending:
                    self._enqueue_event(subscriber, message)
            else:
                subscriber.queue.put_nowait(snapshot_message(state))
                subscriber.applied_sequence = state.last_sequence
                subscriber.enqueued_sequence = state.last_sequence
            self._subscribers.setdefault(session_id, set()).add(subscriber)
        return subscriber

    def _session_for_publish_locked(self, session_id: str) -> _SessionProjection:
        session = self._sessions.get(session_id)
        if session is not None:
            return session
        if len(self._sessions) >= self.max_sessions:
            retired = next(
                (
                    retained_id
                    for retained_id in self._sessions
                    if not self._subscribers.get(retained_id)
                ),
                None,
            )
            if retired is None:
                raise ProjectionError("projection session capacity reached")
            self._sessions.pop(retired, None)
        session = _SessionProjection(deque(maxlen=self.history_limit))
        self._sessions[session_id] = session
        return session

    async def unsubscribe(self, subscriber: ProjectionSubscription) -> None:
        async with self._lock:
            subscribers = self._subscribers.get(subscriber.session_id)
            if subscribers is not None:
                subscribers.discard(subscriber)
                if not subscribers:
                    self._subscribers.pop(subscriber.session_id, None)
            subscriber.closed = True

    async def require_resync(self, session_id: str) -> None:
        async with self._lock:
            self._require_resync_locked(session_id)

    async def shutdown(self) -> None:
        async with self._lock:
            if self._closed:
                return
            self._closed = True
            for session_id, subscribers in self._subscribers.items():
                through = self._sessions.get(session_id, _SessionProjection(deque())).last_sequence
                message = {"type": "closing", "reason": "SHUTDOWN", "through_sequence": through}
                for subscriber in tuple(subscribers):
                    self._replace_queue(subscriber, message)
                    subscriber.closed = True

    def _require_application(self) -> Application:
        if self._application is None:
            raise RuntimeError("projection hub must be bound before use")
        return self._application

    def _enqueue_event(self, subscriber: ProjectionSubscription, message: Mapping[str, Any]) -> None:
        if subscriber.closed or subscriber.paused_for_resync:
            return
        sequence = int(message["sequence"])
        if sequence <= subscriber.enqueued_sequence:
            return
        if sequence != subscriber.enqueued_sequence + 1 or subscriber.queue.full():
            self._replace_queue(subscriber, _resync(subscriber.session_id))
            subscriber.paused_for_resync = True
            return
        subscriber.queue.put_nowait(deepcopy(dict(message)))
        subscriber.enqueued_sequence = sequence

    def _require_resync_locked(self, session_id: str) -> None:
        for subscriber in tuple(self._subscribers.get(session_id, ())):
            self._replace_queue(subscriber, _resync(session_id))
            subscriber.paused_for_resync = True

    @staticmethod
    def _replace_queue(subscriber: ProjectionSubscription, message: Mapping[str, Any]) -> None:
        while not subscriber.queue.empty():
            subscriber.queue.get_nowait()
        subscriber.queue.put_nowait(deepcopy(dict(message)))


async def serve_projection_stream(
    websocket: WebSocketConnection,
    *,
    hub: ProjectionHub,
    session_id: str,
    after_sequence: int | None = None,
) -> None:
    """Serve one WebSocket using a single serialized send boundary."""

    await websocket.accept()
    send_lock = asyncio.Lock()

    async def send(message: Mapping[str, Any]) -> None:
        async with send_lock:
            await websocket.send_json(deepcopy(dict(message)))

    try:
        subscriber = await hub.subscribe(session_id, after_sequence=after_sequence)
    except (KeyError, ProjectionError, RuntimeError):
        await send({"type": "error", "code": "SESSION_NOT_FOUND", "recoverable": False})
        await websocket.close(code=1008, reason="session unavailable")
        return

    async def sender() -> str:
        while True:
            message = await subscriber.receive()
            await send(message)
            if message.get("type") == "closing":
                return "shutdown"

    async def receiver() -> str:
        invalid = 0
        while True:
            try:
                message = await websocket.receive_json()
            except (EOFError, ConnectionError, asyncio.CancelledError):
                return "disconnected"
            if not isinstance(message, Mapping):
                valid = False
            elif "schema_version" in message and message.get("schema_version") != SCHEMA_VERSION:
                await send({"type": "error", "code": "INVALID_CLIENT_MESSAGE", "recoverable": False})
                return "policy"
            elif message.get("type") == "ping":
                valid = isinstance(message.get("nonce"), str) and set(message) <= {"type", "nonce"}
            elif message.get("type") == "ack":
                valid = set(message) <= {"type", "through_sequence"}
                if valid:
                    try:
                        subscriber.acknowledge(message.get("through_sequence"))
                    except ProjectionError:
                        valid = False
            else:
                valid = False
            if valid:
                continue
            invalid += 1
            recoverable = invalid == 1
            await send({"type": "error", "code": "INVALID_CLIENT_MESSAGE", "recoverable": recoverable})
            if not recoverable:
                return "policy"

    # The protocol promises the retained catch-up or snapshot before processing
    # client traffic.  Drain that finite initial batch before starting receive.
    while not subscriber.queue.empty():
        initial = await subscriber.receive()
        await send(initial)
        if initial.get("type") == "closing":
            await hub.unsubscribe(subscriber)
            await websocket.close(code=1001, reason="shutdown")
            return

    send_task = asyncio.create_task(sender())
    receive_task = asyncio.create_task(receiver())
    try:
        done, pending = await asyncio.wait(
            (send_task, receive_task), return_when=asyncio.FIRST_COMPLETED,
        )
        completed = next(iter(done))
        try:
            result = completed.result()
        except (EOFError, ConnectionError):
            result = "disconnected"
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
    finally:
        for task in (send_task, receive_task):
            if not task.done():
                task.cancel()
        await asyncio.gather(send_task, receive_task, return_exceptions=True)
        await hub.unsubscribe(subscriber)
    if result == "shutdown":
        await websocket.close(code=1001, reason="shutdown")
    elif result == "policy":
        await websocket.close(code=1008, reason="invalid client message")


class WebSocketProjectionASGI:
    """Dependency-free ASGI endpoint for the canonical projection stream path."""

    def __init__(self, hub: ProjectionHub) -> None:
        self.hub = hub

    async def __call__(
        self,
        scope: Mapping[str, Any],
        receive: Callable[[], Awaitable[dict[str, Any]]],
        send: Callable[[dict[str, Any]], Awaitable[None]],
    ) -> None:
        match = _STREAM_RE.fullmatch(str(scope.get("path", "")))
        if scope.get("type") != "websocket" or match is None:
            await send({"type": "websocket.close", "code": 1008, "reason": "unknown stream"})
            return
        query = parse_qs(bytes(scope.get("query_string", b"")).decode("ascii", "ignore"))
        raw_after = query.get("after_sequence", [None])[-1]
        try:
            after = int(raw_after) if raw_after is not None else None
            if after is not None and after < 0:
                after = None
        except (TypeError, ValueError):
            after = None
        connection = _ASGIWebSocket(receive, send)
        await serve_projection_stream(
            connection, hub=self.hub, session_id=match.group(1), after_sequence=after,
        )


class _ASGIWebSocket:
    def __init__(
        self,
        receive: Callable[[], Awaitable[dict[str, Any]]],
        send: Callable[[dict[str, Any]], Awaitable[None]],
    ) -> None:
        self._receive = receive
        self._send = send

    async def accept(self) -> None:
        message = await self._receive()
        if message.get("type") != "websocket.connect":
            raise ConnectionError("websocket did not connect")
        await self._send({"type": "websocket.accept"})

    async def send_json(self, message: Mapping[str, Any]) -> None:
        await self._send({
            "type": "websocket.send",
            "text": json.dumps(dict(message), separators=(",", ":"), sort_keys=True),
        })

    async def receive_json(self) -> Any:
        message = await self._receive()
        if message.get("type") == "websocket.disconnect":
            raise EOFError
        if message.get("type") != "websocket.receive":
            raise ConnectionError("invalid websocket frame")
        raw = message.get("text")
        if raw is None and message.get("bytes") is not None:
            raw = bytes(message["bytes"]).decode("utf-8")
        try:
            return json.loads(raw)
        except (TypeError, UnicodeDecodeError, json.JSONDecodeError):
            return None

    async def close(self, code: int = 1000, reason: str = "") -> None:
        await self._send({"type": "websocket.close", "code": code, "reason": reason})
