# WebSocket Protocol

Connect to `/api/v1/sessions/{session_id}/stream?after_sequence=N`. Server first sends a snapshot if `N` is absent/outside retained deltas, otherwise ordered deltas.

```json
{"type":"snapshot","schema_version":1,"session_id":"demo","through_sequence":1,"projection":{"intent":null,"operations":[],"effects":[],"evidence":[],"claims":[],"divergences":[],"plans":[],"speech":[],"metrics":{}}}
```

```json
{"type":"event","schema_version":1,"session_id":"demo","sequence":42,"event_type":"DivergenceDetected","projection_delta":{"through_sequence":42,"changed":{"divergences":[{"divergence_id":"div-booking","state":"OPEN"}]},"removed":{}},"trace":{"correlation_id":"op-book-11"}}
```

Other server messages: `{"type":"resync_required","reason":"GAP_OR_EXPIRED","snapshot_url":"..."}`, `{"type":"error","code":"INVALID_CLIENT_MESSAGE","recoverable":true}`, and `{"type":"closing","reason":"SHUTDOWN","through_sequence":42}`. Client messages are only `{"type":"ack","through_sequence":42}` and `{"type":"ping","nonce":"..."}`; domain commands use HTTP.

The client applies an event only when `sequence == local+1`, ignores exact duplicates `<=local`, and pauses/render-stale on gaps until snapshot resync. On reconnect it sends its last applied sequence. Projection deltas are sanitized, read-only views—not authoritative event payloads. Snapshot replacement is atomic. Unknown message/schema versions close with policy error; malformed messages receive one error then repeated abuse closes. Per-session send order matches journal order.

A snapshot `projection` contains the full `intent, operations, effects, evidence, claims, divergences, plans, speech, metrics` view; an empty collection is explicit and `intent` may be null. Every `projection_delta` has `{through_sequence, changed:{intent?,operations?,effects?,evidence?,claims?,divergences?,plans?,speech?,metrics?}, removed:{...ids}}`; absent keys mean unchanged, while explicit empty arrays mean known empty. `through_sequence` must equal the outer event sequence. The frontend never applies a delta whose session differs, whose sequence skips, or whose schema version is unsupported. Server buffers are bounded; overflow sends `resync_required` rather than silently dropping an event.
