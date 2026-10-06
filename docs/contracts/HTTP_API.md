# HTTP API

Base `/api/v1`; JSON; demo assumes localhost and no authentication. Production authentication is out of scope. Every mutation returns `202` after journal acceptance, not task completion.

| Method/path | Purpose / request | Success | Errors / generated event |
|---|---|---|---|
| `POST /sessions` | `{ "mode":"DEMO|LIVE|TEST", "client_request_id":"..." }` | `201 {session_id,last_sequence,ws_url}` | 409 conflicting request ID, 422 invalid; `SessionStarted` |
| `GET /sessions/{id}` | snapshot | `200 {session_id,through_sequence,projection}` | 404 |
| `POST /sessions/{id}/inputs` | `{modality:"TEXT|FRAME_REF|AUDIO_REF",content?,content_ref?,client_request_id}`; TEXT requires nonempty `content` and forbids `content_ref`; reference modalities require `content_ref` and forbid inline media | `202 {event_id,sequence}` | 409 conflicting dedupe, 413 size, 422; `UserInputObserved` |
| `POST /sessions/{id}/authorizations` | exactly one of `revision_id` or `plan_id`, plus `decision:"AUTHORIZE|DENY",client_request_id` | `202 {event_id,sequence}` | 409 stale/fingerprint-changed target, 422 ambiguous target; revision emits `IntentAuthorizationChanged(AUTHORIZED|DENIED)`; plan emits `ReconciliationAuthorized` or `ReconciliationDenied` |
| `POST /sessions/{id}/speech/{speech_id}/cancel` | `{client_request_id}` | `202` | 404/409; `SpeechCancellationRequested` |
| `POST /sessions/{id}/demo/faults` | `{fault_id,enabled}` demo-only | `202` | 403 outside demo; `FaultActivated` |
| `POST /sessions/{id}/demo/reset` | `{fixture_id:"samsung-demo-v1",client_request_id}` | `200 {session_id:new_id,last_sequence:1}` | 409 operation drain timeout; creates a new clean session identity and retires the old stream |
| `GET /sessions/{id}/events?after_sequence=N` | resync sanitized events | `200 {events,through_sequence,has_more}` | 410 beyond retention |
| `GET /health` | liveness/config mode | `200 {status,mode}` | 503 startup invalid |

Browser voice (DEMO semantic mode) uses `POST /voice/sessions` with an empty body. The backend alone generates a new INTERLOCK session, opaque LiveKit room and participant identity, fresh simulated Samsung provider world, and a short-lived least-privilege room token. The response is exactly `{session_id,room_name,livekit_url,participant_token,ws_url}`; no API or worker secret is returned. Missing LiveKit credentials fail closed. The returned `session_id` is the only Console projection identity.

The internal worker WebSocket `/internal/voice/{session_id}/transport` is authenticated with a separate server/worker secret and validates the bound room, expiry, and current generation. Its accepted observations are only `TRANSCRIPT`, `USER_SPEAKING`, `PLAYOUT_STARTED`, `PLAYOUT_FINISHED`, and `PLAYOUT_FAILED`; unknown or extra fields are rejected. The backend translates them into canonical facts, never accepts arbitrary event envelopes, and sends only exact `SPEAK` or targeted `CANCEL_SPEECH` commands. Browser tokens cannot authenticate this channel. This protocol is private transport, not a second authoritative state API.

Example input:

```json
{"modality":"TEXT","content":"Actually, make it 12.","client_request_id":"ui-008"}
```

Responses never expose provider secrets or claim completion. Validation failure changes no session state. HTTP request IDs become dedupe keys; frontend may safely retry the same ID.

`GET /sessions/{id}` and snapshots expose sanitized projections, never the mutable `SessionState`. `GET .../events` returns the WebSocket `event` message shape without transport framing. An accepted response proves journal acceptance only; it never proves model interpretation, dispatch, provider receipt, or external commit.
