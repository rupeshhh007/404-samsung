"""Serialized in-memory Event Journal implementation for INTERLOCK.

Implements JournalPort contract defined in docs/contracts/INTERFACES.md,
architecture/EVENT_MODEL.md, and components/EVENT_JOURNAL_AND_REDUCER.md.
"""

import asyncio
from datetime import datetime, timezone
import json
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, ValidationError

from interlock.domain.enums import EventSource, RuntimeMode
from interlock.domain.events import EVENT_PAYLOAD_REGISTRY
from interlock.domain.models import EventEnvelope
from interlock.runtime.session import SessionRegistry, generate_uuidv7


class JournalError(Exception):
    """Base exception for journal operations."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class UnknownSessionError(JournalError):
    """Raised when session is not registered in session registry."""

    def __init__(self, session_id: str) -> None:
        super().__init__("UNKNOWN_SESSION", f"Session '{session_id}' not found in registry")


class SessionHaltedError(JournalError):
    """Raised when appending to a halted session."""

    def __init__(self, session_id: str, reason: Optional[str] = None) -> None:
        msg = f"Session '{session_id}' is halted"
        if reason:
            msg += f": {reason}"
        super().__init__("SESSION_HALTED", msg)


class UnsupportedVersionError(JournalError):
    """Raised when schema version is unsupported."""

    def __init__(self, version: Any) -> None:
        super().__init__("UNSUPPORTED_VERSION", f"Unsupported schema version: {version}")


class SchemaInvalidError(JournalError):
    """Raised when candidate event payload or structure fails validation."""

    def __init__(self, details: str) -> None:
        super().__init__("SCHEMA_INVALID", f"Invalid event schema or payload: {details}")


class DedupeConflictError(JournalError):
    """Raised when dedupe_key is seen with conflicting payload or event parameters."""

    def __init__(self, dedupe_key: str) -> None:
        super().__init__("DEDUPE_CONFLICT", f"Conflicting payload for duplicate key: {dedupe_key}")


class EventCandidate(BaseModel):
    """Input specification for appending an event to the journal via JournalPort."""

    event_type: str = Field(..., min_length=1)
    session_id: str = Field(..., min_length=1)
    source: EventSource
    payload: Dict[str, Any] = Field(...)
    occurred_at: Optional[datetime] = None
    logical_time: Optional[int] = Field(default=None, ge=0)
    schema_version: int = Field(default=1)
    correlation_id: Optional[str] = None
    causation_id: Optional[str] = None
    dedupe_key: Optional[str] = None


class EventJournal:
    """Per-session serialized in-memory Event Journal.

    Sole acceptor of events. Guarantees monotonic sequence numbering,
    payload validation against EVENT_PAYLOAD_REGISTRY, deduplication,
    bounded retention, and wakeup notification for the reducer loop.
    """

    def __init__(
        self,
        session_registry: SessionRegistry,
        event_retention: int = 10000,
    ) -> None:
        if event_retention < 1:
            raise ValueError(f"event_retention must be >= 1, got {event_retention}")
        self.session_registry = session_registry
        self.event_retention = event_retention
        self._events: Dict[str, List[EventEnvelope]] = {}
        self._dedupe_index: Dict[str, Dict[str, EventEnvelope]] = {}
        self._event_id_index: Dict[str, Dict[str, EventEnvelope]] = {}
        self._session_locks: Dict[str, asyncio.Lock] = {}
        self._intake_queues: Dict[str, asyncio.Queue] = {}
        self._global_lock = asyncio.Lock()

    def _get_session_lock(self, session_id: str) -> asyncio.Lock:
        if session_id not in self._session_locks:
            self._session_locks[session_id] = asyncio.Lock()
        return self._session_locks[session_id]

    def _get_queue(self, session_id: str) -> asyncio.Queue:
        if session_id not in self._intake_queues:
            self._intake_queues[session_id] = asyncio.Queue()
        return self._intake_queues[session_id]

    def get_queue(self, session_id: str) -> asyncio.Queue:
        """Get the intake queue where accepted envelopes are enqueued for reducer."""
        return self._get_queue(session_id)

    def get_last_sequence(self, session_id: str) -> int:
        """Get the highest accepted sequence number for a session, or 0 if none."""
        events = self._events.get(session_id)
        if not events:
            return 0
        return events[-1].sequence

    def read_events(
        self,
        session_id: str,
        after_sequence: int = 0,
        limit: Optional[int] = None,
    ) -> List[EventEnvelope]:
        """Read detached accepted events in strictly monotonic sequence order."""
        events = self._events.get(session_id, [])
        filtered = [e for e in events if e.sequence > after_sequence]
        if limit is not None and limit > 0:
            filtered = filtered[:limit]
        return [e.model_copy(deep=True) for e in filtered]

    async def clear_session(self, session_id: str) -> None:
        """Reclaim journal event data and secondary indexes for a session under the per-session lock.

        Precondition / Lifecycle Boundary:
        Per docs/architecture/CONCURRENCY_MODEL.md and RUNTIME_ARCHITECTURE.md,
        coordinated quiescence (stopping producers, draining in-flight operations,
        and final destruction of synchronization primitives) is canonically owned
        by the orchestrator / composition root (RUN-004).

        To guarantee strict linearization against in-flight appends and prevent
        races where an in-flight append could interleave with retirement, clear_session
        synchronizes on the per-session lock:
        1. If append() is executing under the lock, clear_session awaits completion
           of the in-flight append before clearing state.
        2. Once clear_session acquires the lock, it expires the SessionRegistry
           record and clears events and secondary indexes.
        3. Any subsequent append either fails the pre-lock check or, if already
           queued on the lock, discovers under the lock that the session has been
           retired and raises UnknownSessionError.
        4. Synchronization primitives (_session_locks, _intake_queues) are preserved
           so reducer tasks and concurrent callers are never split across multiple
           locks or orphaned on abandoned queues. Coordinated destruction of
           synchronization resources is deferred to orchestrator shutdown (RUN-004).
        """
        lock = self._session_locks.get(session_id)
        if lock is not None:
            async with lock:
                self.session_registry.expire_session(session_id)
                self._events.pop(session_id, None)
                self._dedupe_index.pop(session_id, None)
                self._event_id_index.pop(session_id, None)
        else:
            self.session_registry.expire_session(session_id)
            self._events.pop(session_id, None)
            self._dedupe_index.pop(session_id, None)
            self._event_id_index.pop(session_id, None)

    async def append(self, candidate: EventCandidate) -> EventEnvelope:
        """Append a candidate fact to the journal under the per-session lock.

        Follows JournalPort.append contract:
        - Pure candidate validation (schema_version == 1, event_type, typed payload)
          runs first without side effects.
        - Non-SessionStarted events require an active registered session. Non-existent
          sessions are rejected before acquiring or allocating a session lock,
          preventing lock registry leakage.
        - Linearized under per-session lock.
        - Non-mutating deduplication check against active generation.
        - Assigns contiguous sequence = last_accepted + 1.
        - Stores immutable envelope and wakes reducer via queue.
        - Enforces bounded retention across events and secondary indexes.
        """
        candidate = candidate.model_copy(deep=True)

        # 1. Pure Candidate Validation (No side effects on session or journal)
        if candidate.schema_version != 1:
            raise UnsupportedVersionError(candidate.schema_version)

        payload_cls = EVENT_PAYLOAD_REGISTRY.get(candidate.event_type)
        if payload_cls is None:
            raise SchemaInvalidError(f"Unknown event type: {candidate.event_type}")

        try:
            validated_payload_model = payload_cls.model_validate(candidate.payload)
            normalized_payload = json.loads(validated_payload_model.model_dump_json())
        except ValidationError as e:
            raise SchemaInvalidError(str(e))

        # 2. Pre-lock Session Existence Check for Non-Bootstrap Events
        # Rejects unknown sessions before allocating any session lock, preventing memory leaks
        if candidate.event_type != "SessionStarted":
            if self.session_registry.get_session(candidate.session_id) is None:
                raise UnknownSessionError(candidate.session_id)

        # 3. Synchronized Critical Section under Per-Session Lock
        # For SessionStarted bootstrap, we serialize lock lookup/creation under _global_lock
        if candidate.event_type == "SessionStarted":
            async with self._global_lock:
                lock = self._get_session_lock(candidate.session_id)
        else:
            lock = self._get_session_lock(candidate.session_id)

        async with lock:
            # Re-verify session state under the session lock
            session = self.session_registry.get_session(candidate.session_id)

            if candidate.event_type == "SessionStarted":
                if session is not None:
                    # If session is already active, check if this is an idempotent retry
                    session_dedupe = self._dedupe_index.get(candidate.session_id)
                    if session_dedupe is not None and candidate.dedupe_key is not None:
                        existing = session_dedupe.get(candidate.dedupe_key)
                        if existing is not None:
                            if (
                                existing.event_type == candidate.event_type
                                and existing.payload == normalized_payload
                            ):
                                return existing.model_copy(deep=True)
                            else:
                                raise DedupeConflictError(candidate.dedupe_key)
                    # Non-deduped SessionStarted on an active session is an error
                    raise SchemaInvalidError(
                        f"Session '{candidate.session_id}' is already active and cannot be restarted"
                    )

                # Bootstrap fresh session
                mode_val = normalized_payload.get("mode", RuntimeMode.DEMO)
                try:
                    mode = RuntimeMode(mode_val)
                except ValueError:
                    raise SchemaInvalidError(f"Invalid RuntimeMode: {mode_val}")

                session = self.session_registry.create_session(
                    mode=mode,
                    session_id=candidate.session_id,
                )
            else:
                if session is None:
                    raise UnknownSessionError(candidate.session_id)

            if session.halted:
                raise SessionHaltedError(candidate.session_id, session.halt_reason)

            self.session_registry.touch_session(candidate.session_id)

            # 4. Non-Mutating Deduplication Check on Active Generation
            session_dedupe = self._dedupe_index.get(candidate.session_id)
            if session_dedupe is not None and candidate.dedupe_key is not None:
                existing = session_dedupe.get(candidate.dedupe_key)
                if existing is not None:
                    if (
                        existing.event_type == candidate.event_type
                        and existing.payload == normalized_payload
                    ):
                        return existing.model_copy(deep=True)
                    else:
                        raise DedupeConflictError(candidate.dedupe_key)

            # Re-verify session remains active before sequence allocation and envelope storage
            if candidate.event_type != "SessionStarted":
                if self.session_registry.get_session(candidate.session_id) is None:
                    raise UnknownSessionError(candidate.session_id)

            # 5. Sequence Allocation & Envelope Construction
            session_events = self._events.setdefault(candidate.session_id, [])
            last_seq = session_events[-1].sequence if session_events else 0
            next_seq = last_seq + 1

            occurred_at = (
                candidate.occurred_at
                if candidate.occurred_at is not None
                else datetime.now(timezone.utc)
            )
            logical_time = candidate.logical_time if candidate.logical_time is not None else 0

            envelope = EventEnvelope(
                event_id=generate_uuidv7(),
                session_id=candidate.session_id,
                sequence=next_seq,
                event_type=candidate.event_type,
                source=candidate.source,
                occurred_at=occurred_at,
                logical_time=logical_time,
                schema_version=1,
                payload=normalized_payload,
                correlation_id=candidate.correlation_id,
                causation_id=candidate.causation_id,
                dedupe_key=candidate.dedupe_key,
            )

            # 6. Store Envelope & Update Indexes
            session_events.append(envelope)
            active_dedupe = self._dedupe_index.setdefault(candidate.session_id, {})
            if candidate.dedupe_key is not None:
                active_dedupe[candidate.dedupe_key] = envelope

            session_id_index = self._event_id_index.setdefault(candidate.session_id, {})
            session_id_index[envelope.event_id] = envelope

            # 7. Bounded Event Retention
            if len(session_events) > self.event_retention:
                overflow = len(session_events) - self.event_retention
                evicted_events = session_events[:overflow]
                session_events[:overflow] = []

                for evicted in evicted_events:
                    session_id_index.pop(evicted.event_id, None)
                    if evicted.dedupe_key is not None:
                        if active_dedupe.get(evicted.dedupe_key) is evicted:
                            active_dedupe.pop(evicted.dedupe_key, None)

            # 8. Enqueue for Reducer
            queue = self._get_queue(candidate.session_id)
            await queue.put(envelope.model_copy(deep=True))

            return envelope.model_copy(deep=True)
