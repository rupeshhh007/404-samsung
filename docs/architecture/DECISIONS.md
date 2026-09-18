# Architecture Decisions

| ID | Status | Context → selected design | Alternatives rejected / consequences | Affected docs |
|---|---|---|---|---|
| ADR-001 | Accepted | Prototype needs deterministic consistency → modular monolith. | Microservices add distributed ordering; scale limited. | system, blueprint |
| ADR-002 | Accepted | Concurrent tasks need one truth → per-session serialized journal/reducer. | Locks in every module invite races; reducer must stay I/O-free. | runtime, concurrency |
| ADR-003 | Accepted | Ordering and causality differ → monotonic sequence plus causation/correlation IDs; UUIDv7 event IDs. | timestamps alone rejected. | domain, events |
| ADR-004 | Accepted | Replay must be safe → events are facts, reducer commands suppressed on replay. | event sourcing with reissued effects rejected. | events, guarantees |
| ADR-005 | Accepted | Fine correction scope → field bindings and canonical SHA-256 fingerprints. | global revision invalidation wastes work. | intent, domain |
| ADR-006 | Accepted | Speculation risk → only descriptors explicitly classified read-only/no-effect. | name/HTTP inference and prompt-only safety rejected. | tools, BranchCache |
| ADR-007 | Accepted | Cancel can race commit → separate operation/cancellation/effect dimensions. | single status loses reality. | state machines |
| ADR-008 | Accepted | Remote exactly-once unavailable → session dedupe plus provider idempotency when declared; otherwise unknown outcome verification. | blind retry rejected. | tools, guarantees |
| ADR-009 | Accepted | Language must not overclaim → structured SpeechActs, evidence rules, controlled consequential templates. | unrestricted rewrite rejected. | claims, truthlock |
| ADR-010 | Accepted | Demo lacks official Samsung contract → provisional adapter plus deterministic fake. | invented official API rejected. | Samsung contract |
| ADR-011 | Accepted | In-memory hackathon state → no persistence; crash truth is explicitly unknown. | adding database/Redis violates scope. | config, risks |
| ADR-012 | Accepted | Offline mode needed → rule-based scripted interpretation and fake provider. | hard LLM dependency rejected. | LLM, demo |
| ADR-013 | Accepted | Booking confirmation must prove the exact requested resource → canonical demo booking requests use `center_id` and `requested_slot`; a confirmed response must echo `provider_request_id`, `provider_booking_id`, `center_id`, `requested_slot`, and `confirmed_slot`. | A generic success flag or booking ID cannot prove the correct center/slot. This is an internal simulated contract, not a Samsung API claim. | domain, events, tool descriptor, effects, claims, demo |
| ADR-014 | Accepted | Scenario assertions previously mixed an intermediate checkpoint with a final time → virtual time is absolute session time and the late-reconciliation scenario asserts divergence at 1100 ms, then final resolution at 2000 ms. | Leaving an open-divergence assertion at 2200 ms contradicted the 1900 ms golden resolution. | scenario DSL, golden traces, demo |
| ADR-015 | Accepted | Operation `DISPATCHED→WAITING` lacked a triggering fact → `ToolDispatchRequested` moves READY to DISPATCHED; `ToolDispatchAccepted` moves DISPATCHED to WAITING and effect NOT_STARTED to IN_FLIGHT. | Adding a new event was unnecessary; this assigns precise meanings to existing events. | events, state machines, SAFEPOINT, operations |

Any change to an accepted decision requires a superseding ADR and contract-change review.
