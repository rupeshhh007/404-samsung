"""T-API-01: real ASGI acceptance, validation and idempotent retries."""

import asyncio
import json

from interlock.config import Settings
from interlock.main import create_demo_asgi_app


async def _request(host, method, path, payload=None):
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
        {"type": "http", "http_version": "1.1", "method": method,
         "scheme": "http", "path": path, "raw_path": path.encode(),
         "query_string": b"", "root_path": "", "server": ("test", 80),
         "client": ("test", 1), "headers": [
             (b"host", b"test"),
             (b"content-type", b"application/json"),
             (b"content-length", str(len(body)).encode()),
         ]},
        receive, send,
    )
    status = next(message["status"] for message in sent
                  if message["type"] == "http.response.start")
    content = b"".join(message.get("body", b"") for message in sent
                       if message["type"] == "http.response.body")
    return status, json.loads(content)


def test_t_api_01_session_input_and_validation():
    async def run():
        host = create_demo_asgi_app(Settings(
            _env_file=None, INTERLOCK_MODE="DEMO",
            INTERLOCK_MODEL_PROVIDER="fallback", INTERLOCK_FAKE_LATENCY_MS=0,
        ))
        try:
            assert await _request(host, "GET", "/api/v1/health") == (
                200, {"status": "ok", "mode": "DEMO"})
            request = {"mode": "DEMO", "client_request_id": "create-1"}
            created = await _request(host, "POST", "/api/v1/sessions", request)
            repeated = await _request(host, "POST", "/api/v1/sessions", request)
            assert created == repeated
            assert created[0] == 201
            session_id = created[1]["session_id"]
            snapshot = await _request(host, "GET", f"/api/v1/sessions/{session_id}")
            assert snapshot[0] == 200
            assert snapshot[1]["through_sequence"] >= 1
            accepted = await _request(
                host, "POST", f"/api/v1/sessions/{session_id}/inputs",
                {"modality": "TEXT", "content": "Book 11:00.",
                 "client_request_id": "input-1"},
            )
            assert accepted[0] == 202
            assert "event_id" in accepted[1]
            retried = await _request(
                host, "POST", f"/api/v1/sessions/{session_id}/inputs",
                {"modality": "TEXT", "content": "Book 11:00.",
                 "client_request_id": "input-1"},
            )
            assert retried == accepted
            bad = await _request(
                host, "POST", f"/api/v1/sessions/{session_id}/inputs",
                {"modality": "TEXT", "content": "", "client_request_id": "bad"},
            )
            assert bad[0] == 422
            assert (await _request(host, "GET", "/api/v1/sessions/unknown"))[0] == 404
        finally:
            await host.application.close()
            await host.output.shutdown()
            await host.hub.shutdown()
    asyncio.run(run())
