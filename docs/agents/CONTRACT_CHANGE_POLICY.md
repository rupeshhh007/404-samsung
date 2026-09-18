# Contract Change Policy

Agents must not silently alter entities, enums, events, transitions, interfaces, API/WS/tool/model schemas, frozen architecture, or ticket IDs.

Create a change request containing ID, problem/evidence, canonical owner, proposed old/new contract, compatibility class (additive/breaking), affected producers/consumers/files/tickets/tests/demo, migration/fallback, risk, and reviewers. First determine whether a private implementation choice can solve the issue without contract change.

For an approved change: add/supersede an ADR when architectural; update the canonical owner first; bump schema/manifest version for breaking serialization; support dual-read/write or explicit incompatible cutover; update all dependent component examples, blueprint/backlog, traceability, tests/golden traces, and API/frontend contracts in one reviewed change. Review requires canonical owner plus every directly affected owner. Run contract, replay, invariant, and demo regression tests.

Backward-compatible additions must be optional with deterministic defaults. Never reinterpret an existing enum/event meaning in place. Record decision/status and completion report. Until approved, implement against the current contract or mark the ticket blocked with evidence.
