# Event Journal and Reducer

`EventJournal.append` validates type/version/session, checks `event_id` and `dedupe_key`, assigns the next sequence under a per-session lock, stores a journal-owned immutable-history envelope, and exposes only detached copies to callers and the reducer queue. The single session reducer requires `sequence=last_sequence+1`, calls deterministic policies, atomically replaces state, then publishes projection deltas and commands. A journal-accepted semantic violation preserves business/entity state but advances reducer cursor/metrics through that sequence and emits `RecordProtocolViolation`; unexpected reducer exceptions leave old state intact, halt that session, and surface a sanitized fatal error.

Workers return facts through the journal. The reducer performs no network, filesystem, clock sleep, model, or tool call. Replay starts from empty state (or future versioned snapshot), applies stored envelopes in sequence, compares hashes in tests, and discards commands. Duplicate identical callbacks are audited/metriced without reduction; conflicting duplicates become protocol violations.

Key commands: `InterpretInput`, `PrepareBranch`, `PrepareOperation`, `DispatchTool`, `RequestToolCancellation`, `VerifyOutcome`, `BuildReconciliationPlan`, `ValidateSpeech`, `QueueOutput`, `EmitOutput`, `PublishProjection`. Builtin dispatcher acceptance of preparation/output commands returns `BranchPreparationStarted`, `OperationPreparationStarted`, or `SpeechQueued`. For `PrepareOperation`, `CommandDispatcher.register(..., replace_builtin=True)` allows EXE-004/RUN-004 composition to replace the default acceptance handler with the real ToolRuntime preparation worker that emits `OperationPreparationStarted` followed by `OperationPrepared`. Tests: T-JRN-01, T-RED-01, T-RPL-01, T-CON-01. Ownership: Runtime; contracts: JournalPort/Reducer.

## Implementation contract

- Purpose/responsibilities: linearize accepted facts, dedupe, reduce legal transitions, emit commands/projections, replay without effects.
- Non-responsibilities: interpretation, provider I/O, wall-clock waiting, tool cancellation, speech rendering, or persistence across process restart.
- State owned: entire `SessionState` (including authoritative `IntentRevision` snapshots in `revisions`), journal entries, last accepted/reduced sequence, session halt flag. Workers own no state.
- Inputs/outputs: `JournalPort.append` and `Reducer.reduce` exactly as defined in `INTERFACES.md`; payloads are from `EVENT_MODEL.md`.
- Events consumed: every canonical event. Produced through commands: result events are produced by their designated worker; journal itself assigns envelopes but invents no domain fact.

Decision procedure: validate envelope → dedupe → sequence/store → reduce next contiguous event → validate transition/invariants → atomically replace → publish delta → dispatch commands in live mode. If projection publication fails, state remains committed and clients recover by snapshot. If command submission fails before worker acceptance, journal a typed failure for that command; never roll back the triggering fact. Unexpected reducer exceptions halt only that session and expose a sanitized error.

Acceptance: `T-JRN-01`, `T-RED-01`, `T-RPL-01`, `T-CON-01`, `T-OBS-01`, and invariant tests I11/I12. Dependencies: INT-001 domain/event models. Owner A; reviewer D.
