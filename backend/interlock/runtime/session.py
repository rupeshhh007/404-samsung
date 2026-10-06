"""Session registry and retention management for INTERLOCK.

Implements session lifecycle, metadata tracking, idle expiration, and
retention limits according to NFR-008 and architecture/RUNTIME_ARCHITECTURE.md.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
import os
import time
from typing import Dict, List, Optional
import uuid

from interlock.domain.enums import RuntimeMode


def generate_uuidv7() -> str:
    """Generate a UUIDv7 string.

    Uses Python 3.11 bit layout with current Unix epoch timestamp in milliseconds
    plus cryptographically secure random bits, conforming to RFC 9562.
    """
    ms_timestamp = int(time.time() * 1000)
    rand_bytes = os.urandom(10)
    rand_a = int.from_bytes(rand_bytes[:2], "big") & 0x0FFF
    rand_b = int.from_bytes(rand_bytes[2:], "big") & 0x3FFFFFFFFFFFFFFF

    # UUIDv7 layout: 48 bits timestamp | 4 bits ver (0111) | 12 bits rand_a | 2 bits var (10) | 62 bits rand_b
    high = (ms_timestamp << 16) | (0x7 << 12) | rand_a
    low = (0x2 << 62) | rand_b
    int_val = (high << 64) | low
    return str(uuid.UUID(int=int_val))


@dataclass
class SessionRecord:
    """In-memory session tracking metadata."""

    session_id: str
    mode: RuntimeMode
    created_at: datetime
    last_activity_at: datetime
    halted: bool = False
    halt_reason: Optional[str] = None


class SessionRegistry:
    """Session lifecycle and in-memory retention registry.

    Provides asyncio/single-event-loop safe session management.
    Enforces idle session retention limits per NFR-008.
    """

    def __init__(self, session_retention_s: int = 3600) -> None:
        self.session_retention_s = session_retention_s
        self._sessions: Dict[str, SessionRecord] = {}

    def create_session(
        self,
        mode: RuntimeMode = RuntimeMode.DEMO,
        session_id: Optional[str] = None,
    ) -> SessionRecord:
        """Create and register a new session record."""
        sid = session_id if session_id else generate_uuidv7()
        now = datetime.now(timezone.utc)
        record = SessionRecord(
            session_id=sid,
            mode=mode,
            created_at=now,
            last_activity_at=now,
            halted=False,
            halt_reason=None,
        )
        self._sessions[sid] = record
        return record

    def get_session(self, session_id: str) -> Optional[SessionRecord]:
        """Retrieve a session if it exists and has not expired."""
        record = self._sessions.get(session_id)
        if record is None:
            return None
        if self.is_expired(record):
            self.expire_session(session_id)
            return None
        return record

    def touch_session(self, session_id: str) -> None:
        """Update last activity timestamp for the session."""
        record = self._sessions.get(session_id)
        if record is not None:
            record.last_activity_at = datetime.now(timezone.utc)

    def halt_session(self, session_id: str, reason: str) -> None:
        """Halt a session due to fatal error or protocol violation."""
        record = self._sessions.get(session_id)
        if record is not None:
            record.halted = True
            record.halt_reason = reason
            record.last_activity_at = datetime.now(timezone.utc)

    def is_expired(self, record: SessionRecord, now: Optional[datetime] = None) -> bool:
        """Check if a session record has exceeded idle retention."""
        current_time = now if now is not None else datetime.now(timezone.utc)
        elapsed = (current_time - record.last_activity_at).total_seconds()
        return elapsed > self.session_retention_s

    def expire_session(self, session_id: str) -> bool:
        """Remove a session from the registry upon expiration or reset."""
        if session_id in self._sessions:
            del self._sessions[session_id]
            return True
        return False

    def list_active_sessions(self) -> List[str]:
        """List all non-expired session IDs."""
        now = datetime.now(timezone.utc)
        active: List[str] = []
        for sid, rec in list(self._sessions.items()):
            if self.is_expired(rec, now):
                self.expire_session(sid)
            else:
                active.append(sid)
        return active

    def clear(self) -> None:
        """Clear all registered sessions (used during reset or testing)."""
        self._sessions.clear()
