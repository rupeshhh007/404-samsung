# Samsung Adapter Boundary

## Status

Verified external requirements: none were supplied. Project context identifies a Samsung PRISM GenAI hackathon and a Device/Service Copilot demonstration only. No official API, manifest, message, credential, availability, warranty, booking, or cancellation contract is claimed.

Project assumptions: adapters can exchange session input, dynamic tool declarations, tool calls/results, and output messages. These are provisional internal contracts isolated in `adapters/samsung.py`.

## Mapping

Inbound adapter maps external session/message IDs to internal IDs, media to content references, text/audio to input evidence, and rejects unsupported versions. Manifest adapter converts declarations to `ToolDescriptor` with conservative defaults. Outbound maps `DispatchTool` into provider invocation and converts responses/errors/callbacks into normalized events. Output maps approved SpeechActs to text/TTS messages without changing certainty.

The complete local mock exposes `device.lookup_error` (read-only), `service.find_centers` (read-only), `appointment.availability` (read-only), `appointment.book` (reversible state change), `appointment.cancel` (reversible), and `appointment.get` (read-only verification), using [demo fixtures](../demo/DEMO_FIXTURES.md). It accepts deterministic fault plans and idempotency keys.

When official information arrives, replace transport/session/auth/error and manifest/result mappings only; update descriptors and contract tests. Generic domain events, state machines, and safety policy must remain unchanged unless a reviewed contract change proves otherwise. Without access, use the mock and label every UI/demo datum `SIMULATED`.
