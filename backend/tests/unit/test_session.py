"""T-RET-01: session retention and explicit retirement."""

from datetime import timedelta

from interlock.domain.enums import RuntimeMode
from interlock.runtime.session import SessionRegistry


def test_t_ret_01_idle_expiry_and_reset():
    registry = SessionRegistry(session_retention_s=60)
    record = registry.create_session(mode=RuntimeMode.TEST, session_id="s")
    assert registry.get_session("s") is record
    assert registry.is_expired(record, record.last_activity_at + timedelta(seconds=61))
    assert registry.expire_session("s")
    assert registry.get_session("s") is None
    assert not registry.expire_session("s")


def test_t_ret_01_halt_metadata():
    registry = SessionRegistry()
    registry.create_session(session_id="s")
    registry.halt_session("s", "protocol violation")
    assert registry.get_session("s").halted is True
    assert registry.get_session("s").halt_reason == "protocol violation"


def test_t_ret_01_process_restart_clears_memory_and_omits_secrets():
    registry = SessionRegistry(session_retention_s=3600)
    record = registry.create_session(session_id="volatile-1", mode=RuntimeMode.TEST)
    assert registry.get_session("volatile-1") is record
    assert "volatile-1" in registry.list_active_sessions()

    # Process restart simulation: fresh in-memory registry contains zero prior sessions
    restarted = SessionRegistry(session_retention_s=3600)
    assert restarted.get_session("volatile-1") is None
    assert restarted.list_active_sessions() == []

    # Verify session record contains no sensitive credentials or secret auth tokens
    assert not hasattr(record, "secret_token")
    assert not hasattr(record, "credentials")
    assert not hasattr(record, "api_key")
