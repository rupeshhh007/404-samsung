"""T-WS-01: projection stream cursor, dedupe, gap and reconnect."""

import asyncio
from datetime import datetime, timezone
import json

import pytest

from interlock.adapters.websocket import ProjectionHub
from interlock.config import Settings
from interlock.domain.enums import EventSource
from interlock.domain.models import EventEnvelope, SessionState
from interlock.main import create_demo_asgi_app


_NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _event(sequence, session_id="s"):
    return EventEnvelope(
        event_id=f"event-{sequence}",
        session_id=session_id,
        sequence=sequence,
        event_type="SessionStarted" if sequence == 1 else "UserInputObserved",
        source=EventSource.SYSTEM,
        occurred_at=_NOW,
        logical_time=sequence,
        payload={"mode": "TEST"} if sequence == 1 else {
            "evidence_id": f"e-{sequence}",
            "modality": "TEXT",
            "content_ref": "input",
        },
    )


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


class ASGIWebSocketClient:
    def __init__(self, host, path, query_string=""):
        self.host = host
        self.path = path
        self.query_string = query_string
        self.to_server: asyncio.Queue = asyncio.Queue()
        self.from_server: asyncio.Queue = asyncio.Queue()
        self.task: asyncio.Task | None = None

    async def connect(self):
        scope = {
            "type": "websocket",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "scheme": "ws",
            "path": self.path,
            "raw_path": self.path.encode(),
            "query_string": self.query_string.encode() if isinstance(self.query_string, str) else self.query_string,
            "root_path": "",
            "headers": [(b"host", b"test")],
            "subprotocols": [],
        }

        async def receive():
            return await self.to_server.get()

        async def send(message):
            await self.from_server.put(message)

        self.task = asyncio.create_task(self.host(scope, receive, send))
        await self.to_server.put({"type": "websocket.connect"})
        resp = await asyncio.wait_for(self.from_server.get(), timeout=2.0)
        return resp

    async def receive_json(self, timeout=2.0):
        while True:
            msg = await asyncio.wait_for(self.from_server.get(), timeout=timeout)
            if msg.get("type") == "websocket.send":
                text = msg.get("text")
                if text is not None:
                    return json.loads(text)
            elif msg.get("type") == "websocket.close":
                return {"type": "close", "code": msg.get("code", 1000), "reason": msg.get("reason", "")}

    async def send_json(self, payload):
        await self.to_server.put({
            "type": "websocket.receive",
            "text": json.dumps(payload),
        })

    async def close(self):
        if self.task and not self.task.done():
            await self.to_server.put({"type": "websocket.disconnect"})
            try:
                await asyncio.wait_for(self.task, timeout=1.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                pass


def test_t_ws_01_snapshot_delta_duplicate_gap_and_reconnect():
    async def run():
        class ApplicationView:
            state = SessionState(session_id="s", last_sequence=1)

            def snapshot(self, session_id):
                assert session_id == "s"
                return self.state.model_copy(deep=True)

        application = ApplicationView()
        hub = ProjectionHub()
        hub.bind(application)
        try:
            assert await hub.publish(_event(1), application.state)
            subscriber = await hub.subscribe("s")
            snapshot = await subscriber.receive()
            assert snapshot["type"] == "snapshot"
            assert snapshot["through_sequence"] == 1
            application.state = SessionState(session_id="s", last_sequence=2)
            assert await hub.publish(_event(2), application.state)
            assert (await subscriber.receive())["sequence"] == 2
            assert not await hub.publish(_event(2), application.state)
            reconnect = await hub.subscribe("s", after_sequence=1)
            assert (await reconnect.receive())["sequence"] == 2
            gap = SessionState(session_id="s", last_sequence=4)
            assert not await hub.publish(_event(4), gap)
            assert (await subscriber.receive())["type"] == "resync_required"
            await hub.unsubscribe(subscriber)
            await hub.unsubscribe(reconnect)
        finally:
            await hub.shutdown()

    asyncio.run(run())


def test_t_ws_01_asgi_websocket_transport_full_lifecycle():
    async def run():
        settings = Settings(
            _env_file=None,
            INTERLOCK_MODE="DEMO",
            INTERLOCK_MODEL_PROVIDER="fallback",
            INTERLOCK_FAKE_LATENCY_MS=0,
        )
        host = create_demo_asgi_app(settings)

        # 1. Create a session via HTTP command boundary
        status, created = await _http_request(
            host, "POST", "/api/v1/sessions", {"mode": "DEMO", "client_request_id": "ws-test-create"}
        )
        assert status == 201
        session_id = created["session_id"]

        # 2. Connect via ASGI WebSocket boundary
        ws = ASGIWebSocketClient(host, f"/api/v1/sessions/{session_id}/stream")
        resp = await ws.connect()
        assert resp["type"] == "websocket.accept"

        try:
            # 3. Receive initial snapshot frame
            snapshot_frame = await ws.receive_json()
            assert snapshot_frame["type"] == "snapshot"
            assert snapshot_frame["session_id"] == session_id
            assert snapshot_frame["through_sequence"] == 1
            assert "projection" in snapshot_frame

            # 4. Advance session by injecting user input via HTTP
            input_status, _ = await _http_request(
                host,
                "POST",
                f"/api/v1/sessions/{session_id}/inputs",
                {"modality": "TEXT", "content": "I need to book an appointment.", "client_request_id": "input-ws-1"},
            )
            assert input_status == 202

            # 5. Receive streamed event delta frame for UserInputObserved (sequence 2)
            event_frame = await ws.receive_json()
            assert event_frame["type"] == "event"
            assert event_frame["session_id"] == session_id
            assert event_frame["sequence"] == 2
            assert event_frame["event_type"] == "UserInputObserved"
            assert event_frame["projection_delta"]["through_sequence"] == 2

            # Wait briefly for downstream demo events to settle and drain them
            await asyncio.sleep(0.15)
            latest_seq = 2
            while True:
                try:
                    next_frame = await ws.receive_json(timeout=0.05)
                    if next_frame.get("type") == "event":
                        latest_seq = max(latest_seq, next_frame["sequence"])
                except (asyncio.TimeoutError, TimeoutError):
                    break

            # 6. Client message protocol: valid ping and ack
            await ws.send_json({"type": "ping", "nonce": "nonce-42"})
            await ws.send_json({"type": "ack", "through_sequence": latest_seq})

            # 7. Duplicate sequence is ignored by hub and does not disrupt stream
            events = host.application.events(session_id)
            ev2 = events[1]
            state_at_2 = host.application.replay(events[:2])
            assert not await host.hub.publish(ev2, state_at_2)

            # 8. Reconnect with ?after_sequence=1 receives contiguous missed event (sequence 2)
            ws_reconnect = ASGIWebSocketClient(
                host, f"/api/v1/sessions/{session_id}/stream", query_string="after_sequence=1"
            )
            await ws_reconnect.connect()
            reconnect_msg = await ws_reconnect.receive_json()
            assert reconnect_msg["type"] == "event"
            assert reconnect_msg["sequence"] == 2
            await ws_reconnect.close()

            # 9. Sequence gap triggers resync_required
            current_state = host.application.snapshot(session_id)
            gap_seq = current_state.last_sequence + 5
            gap_state = current_state.model_copy(deep=True)
            gap_state.last_sequence = gap_seq
            gap_ev = _event(gap_seq, session_id=session_id)
            assert not await host.hub.publish(gap_ev, gap_state)
            resync_msg = await ws.receive_json()
            assert resync_msg["type"] == "resync_required"
            assert resync_msg["reason"] == "GAP_OR_EXPIRED"
            assert resync_msg["snapshot_url"] == f"/api/v1/sessions/{session_id}"

            # 10. Snapshot recovery path succeeds via snapshot_url
            snap_status, recovered_snap = await _http_request(host, "GET", resync_msg["snapshot_url"])
            assert snap_status == 200
            assert recovered_snap["session_id"] == session_id
            assert recovered_snap["through_sequence"] == current_state.last_sequence
            assert "projection" in recovered_snap

            # 11. Invalid client messages trigger proper error handling
            await ws.send_json({"type": "unknown_type"})
            err1 = await ws.receive_json()
            assert err1["type"] == "error"
            assert err1["code"] == "INVALID_CLIENT_MESSAGE"
            assert err1["recoverable"] is True

            # Second invalid message is non-recoverable and causes policy closure (code 1008)
            await ws.send_json({"type": "second_bad_message"})
            err2 = await ws.receive_json()
            assert err2["type"] == "error"
            assert err2["code"] == "INVALID_CLIENT_MESSAGE"
            assert err2["recoverable"] is False

            close_frame = await ws.receive_json()
            assert close_frame["type"] == "close"
            assert close_frame["code"] == 1008

        finally:
            await ws.close()
            await host.application.close()
            await host.hub.shutdown()

    asyncio.run(run())


def test_t_ws_01_asgi_unknown_session_and_path_rejection():
    async def run():
        settings = Settings(
            _env_file=None,
            INTERLOCK_MODE="DEMO",
            INTERLOCK_MODEL_PROVIDER="fallback",
            INTERLOCK_FAKE_LATENCY_MS=0,
        )
        host = create_demo_asgi_app(settings)

        # 1. Connection to nonexistent session is accepted then closed with SESSION_NOT_FOUND (1008)
        ws_unknown = ASGIWebSocketClient(host, "/api/v1/sessions/unknown-session-999/stream")
        accept = await ws_unknown.connect()
        assert accept["type"] == "websocket.accept"
        err = await ws_unknown.receive_json()
        assert err["type"] == "error"
        assert err["code"] == "SESSION_NOT_FOUND"
        assert err["recoverable"] is False
        close_frame = await ws_unknown.receive_json()
        assert close_frame["type"] == "close"
        assert close_frame["code"] == 1008
        await ws_unknown.close()

        # 2. Connection to invalid path is rejected immediately with 1008
        scope = {
            "type": "websocket",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "scheme": "ws",
            "path": "/api/v1/invalid/stream/path",
            "raw_path": b"/api/v1/invalid/stream/path",
            "query_string": b"",
            "root_path": "",
            "headers": [(b"host", b"test")],
            "subprotocols": [],
        }
        sent = []

        async def receive():
            return {"type": "websocket.connect"}

        async def send(message):
            sent.append(message)

        await host(scope, receive, send)
        assert any(msg.get("type") == "websocket.close" and msg.get("code") == 1008 for msg in sent)

        await host.application.close()
        await host.hub.shutdown()

    asyncio.run(run())
