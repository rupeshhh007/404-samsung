"""T-RET-01: session retention, explicit retirement, and restart limits."""

import asyncio
from datetime import datetime, timedelta, timezone
import json

import pytest

from interlock.adapters.websocket import _safe, project_state
from interlock.config import Settings
from interlock.domain.enums import RuntimeMode
from interlock.domain.models import SessionState
from interlock.main import create_demo_asgi_app
from interlock.runtime.session import SessionRegistry, generate_uuidv7


async def _http_request(host, method, path, payload=None):
    body = b"" if payload is None else json.dumps(payload).encode("utf-8")
    sent = []
    received = False

    async def receive():
        nonlocal received
        if not received:
            received = True
            return {"type": "http.request", "body": body, "more_body": False}
        return {"type": "http.disconnect"}

    async def send(message):
        sent.append(message)

    await host(
        {
            "type": "http",
            "http_version": "1.1",
            "method": method,
            "scheme": "http",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "root_path": "",
            "server": ("test", 80),
            "client": ("test", 1),
            "headers": [
                (b"host", b"test"),
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
            ],
        },
        receive,
        send,
    )
    status = next(m["status"] for m in sent if m["type"] == "http.response.start")
    content = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
    return status, json.loads(content)


async def _ws_connect(host, path):
    incoming = []
    client_queue = asyncio.Queue()
    await client_queue.put({"type": "websocket.connect"})

    async def receive():
        return await client_queue.get()

    async def send(message):
        incoming.append(message)

    scope = {
        "type": "websocket",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "scheme": "ws",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": [(b"host", b"test")],
        "subprotocols": [],
    }
    task = asyncio.create_task(host(scope, receive, send))
    await asyncio.sleep(0.05)
    await client_queue.put({"type": "websocket.disconnect"})
    await task
    return incoming


def test_t_ret_01_idle_expiry_and_reset():
    registry = SessionRegistry(session_retention_s=60)
    record = registry.create_session(mode=RuntimeMode.TEST, session_id="s")
    assert registry.get_session("s") is record
    assert "s" in registry.list_active_sessions()

    # Touch updates activity timestamp
    prior_activity = record.last_activity_at
    registry.touch_session("s")
    assert record.last_activity_at >= prior_activity

    # Idle expiration detection and cleanup
    assert registry.is_expired(record, record.last_activity_at + timedelta(seconds=61))
    assert registry.expire_session("s")
    assert registry.get_session("s") is None
    assert not registry.expire_session("s")
    assert registry.list_active_sessions() == []

    # Explicit reset via clear()
    registry.create_session(session_id="s2", mode=RuntimeMode.TEST)
    assert len(registry.list_active_sessions()) == 1
    registry.clear()
    assert registry.list_active_sessions() == []


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

    # Verify _safe redaction sanitizes sensitive keys from logs, projections and metadata
    raw_sensitive = {
        "user_id": "usr-123",
        "api_key": "sk-secret12345",
        "password": "super-secret-password",
        "session_token": "bearer-tok-999",
        "nested": {
            "credentials": "creds-xyz",
            "auth_cookie": "sess-cookie-val",
            "normal_field": "visible_value",
        },
        "items": [{"secret_code": "hidden", "public_id": "pub-1"}],
    }
    redacted = _safe(raw_sensitive)
    assert redacted["user_id"] == "usr-123"
    assert redacted["api_key"] == "[REDACTED]"
    assert redacted["password"] == "[REDACTED]"
    assert redacted["session_token"] == "[REDACTED]"
    assert redacted["nested"]["credentials"] == "[REDACTED]"
    assert redacted["nested"]["auth_cookie"] == "[REDACTED]"
    assert redacted["nested"]["normal_field"] == "visible_value"
    assert redacted["items"][0]["secret_code"] == "[REDACTED]"
    assert redacted["items"][0]["public_id"] == "pub-1"

    # UI snapshot projection is free of raw secret content
    state = SessionState(session_id="s", last_sequence=1)
    projection = project_state(state)
    assert "password" not in json.dumps(projection)
    assert "token" not in json.dumps(projection)


def test_t_ret_01_restart_loss_limitation_visible_at_boundary():
    async def run():
        settings = Settings(
            _env_file=None,
            INTERLOCK_MODE="DEMO",
            INTERLOCK_MODEL_PROVIDER="fallback",
            INTERLOCK_FAKE_LATENCY_MS=0,
        )
        host = create_demo_asgi_app(settings)

        # 1. Start a session and confirm it is active at the boundary
        status, created = await _http_request(
            host, "POST", "/api/v1/sessions", {"mode": "DEMO", "client_request_id": "req-init"}
        )
        assert status == 201
        session_id = created["session_id"]

        status, snap = await _http_request(host, "GET", f"/api/v1/sessions/{session_id}")
        assert status == 200
        assert snap["session_id"] == session_id

        # 2. Simulate process restart / crash: a fresh process host has zero retained in-memory state
        restarted_host = create_demo_asgi_app(settings)

        # Application state is lost (KeyError at application layer)
        with pytest.raises(KeyError):
            restarted_host.application.snapshot(session_id)

        # HTTP boundary cleanly discloses session loss via 404 Not Found
        status, err_resp = await _http_request(restarted_host, "GET", f"/api/v1/sessions/{session_id}")
        assert status == 404
        assert err_resp["detail"] == "session not found"

        # WebSocket boundary cleanly discloses session loss via SESSION_NOT_FOUND and 1008 close
        ws_frames = await _ws_connect(restarted_host, f"/api/v1/sessions/{session_id}/stream")
        assert any(frame.get("type") == "websocket.accept" for frame in ws_frames)
        error_frames = [
            json.loads(frame["text"])
            for frame in ws_frames
            if frame.get("type") == "websocket.send" and "text" in frame
        ]
        assert any(
            f.get("type") == "error" and f.get("code") == "SESSION_NOT_FOUND" and not f.get("recoverable")
            for f in error_frames
        )
        close_frames = [frame for frame in ws_frames if frame.get("type") == "websocket.close"]
        assert any(frame.get("code") == 1008 for frame in close_frames)

        # 3. Explicit demo reset also retires session and discloses loss limitation
        reset_status, reset_resp = await _http_request(
            host,
            "POST",
            f"/api/v1/sessions/{session_id}/demo/reset",
            {"fixture_id": "samsung-demo-v1", "client_request_id": "reset-1"},
        )
        assert reset_status == 200
        new_session_id = reset_resp["session_id"]
        assert new_session_id != session_id

        # Prior session is retired and now returns 404
        status, _ = await _http_request(host, "GET", f"/api/v1/sessions/{session_id}")
        assert status == 404

        # New session is active and queryable
        status, snap2 = await _http_request(host, "GET", f"/api/v1/sessions/{new_session_id}")
        assert status == 200
        assert snap2["session_id"] == new_session_id

    asyncio.run(run())
