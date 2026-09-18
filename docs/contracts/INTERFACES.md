# Cross-Module Interfaces

Signatures are language-neutral contracts, not executable code.

| Interface | Owner; caller | Input → output; behavior | Failures, effects, events/invariants |
|---|---|---|---|
| `JournalPort.append` | Runtime; adapters/workers | unsequenced validated fact → accepted `EventEnvelope` | async serialized; duplicate returns prior acceptance; invalid rejects; FR-001 |
| `Reducer.reduce` | Runtime; journal | `SessionState, EventEnvelope, mode` → `new_state, Command[]` | sync/pure; invalid transition violation command; I11/I12 |
| `CommandDispatcher.submit` | Runtime; reducer loop | immutable command → eventual event(s) | async; no direct state; correlated errors |
| `ControlInterpreter.interpret` | Intelligence; dispatcher | evidence + snapshot summary → `ControlIntent, IntentDelta?` | timeout/invalid → fallback or clarification; no mutation; I7 |
| `IntentGraph.apply_delta` | Intelligence policy; reducer | active graph + delta → proposed revision/bindings | deterministic validation; emits revision event |
| `BranchPlanner.predict` | Intelligence; dispatcher | active intent + descriptors + budget → candidates | read-only candidates only; I2 |
| `SafePointPolicy.decide` | Execution policy; reducer | operation + current revision + event → `CONTINUE|CANCEL|HOLD|UNKNOWN` commands | pure; I3/I14 |
| `ToolRegistry.register` | Execution; composition | raw manifest → `ToolDescriptor` | conservative normalization or reject |
| `ToolExecutor.invoke` | Execution; dispatcher | descriptor, args, idempotency key, cancel token → normalized observations | external side effect; timeouts/callbacks evented; I5 |
| `EffectInterpreter.observe` | Execution; reducer policy | result + descriptor semantics → evidence/effect events | stale retained; conflicting authority → unknown; I4/I9 |
| `Reconciler.plan` | Execution; dispatcher | desired revision, effects, capabilities → plan | no execution; requires authorization when consequential; I10 |
| `EvidenceStore.add` | Truth/Intelligence; reducer | immutable record → insert/idempotent existing | conflicting same ID violation; I8 |
| `ClaimEvaluator.evaluate` | Truth; reducer policy | claim + evidence/effects + sequence → state-change events | no I/O; freshness/authority rules; FR-014 |
| `Truthlock.validate` | Truth; dispatcher | SpeechAct + pinned claims/evidence → decision + controlled text | stale pin retries; unsupported blocks; I6 |
| `OutputPort.emit/cancel` | Truth adapter; dispatcher | approved text/speech ID → lifecycle events | cancelling output never cancels operation |
| `ProjectionHub.publish` | Runtime; reducer loop | sequence + sanitized projection delta → clients | gaps resolved through snapshot endpoint |
| `Clock.now/schedule` | Testing/runtime; workers | duration/callback → logical schedule handle | virtual in tests, monotonic in live |

```mermaid
flowchart LR
  Adapters --> JournalPort --> Reducer
  Reducer --> CommandDispatcher
  CommandDispatcher --> ControlInterpreter
  CommandDispatcher --> ToolExecutor
  CommandDispatcher --> Truthlock
  ToolExecutor --> JournalPort
  Truthlock --> JournalPort
```

All interfaces are session-scoped. Cancellation is cooperative according to descriptors; idempotency applies to logical action IDs and declared provider support.

## Normative interface details

### `JournalPort.append(candidate)`

- Input: validated event type, `session_id`, `source`, payload, optional causal/dedupe fields; callers never assign sequence.
- Output: accepted envelope or the previously accepted envelope for an identical dedupe key.
- Errors: `UNKNOWN_SESSION`, `SCHEMA_INVALID`, `UNSUPPORTED_VERSION`, `DEDUPE_CONFLICT`, `SESSION_HALTED`.
- Concurrency: linearized under the per-session journal lock; cancellation before acceptance changes nothing, after acceptance cannot retract the fact.
- Side effect: appends in memory and wakes the reducer; never calls external providers.

### `Reducer.reduce(state, envelope, mode)`

- Preconditions: envelope session matches state and sequence is exactly `last_sequence + 1` (except `SessionStarted` creating state).
- Output: a fully new state value, ordered command list, and sanitized projection delta pinned to the sequence.
- Errors: invalid transition returns unchanged state plus `RecordProtocolViolation`; an unexpected reducer defect halts the session rather than partially committing.
- Replay: `mode=REPLAY` computes state/projection but the loop discards every command.

### `ToolExecutor.invoke(invocation)`

`invocation` contains `operation_id`, descriptor capability hash, validated arguments, logical action ID, idempotency key, deadline, speculative flag, and cancellation token. It emits `ToolDispatchAccepted`, zero or more acknowledgement `ToolResultObserved` events, and one terminal result/timeout event. It must not emit `WorldEffectObserved`; effect interpretation is reducer policy. Cancellation behavior comes only from the descriptor. Reusing a write idempotency key with different normalized arguments is `IDEMPOTENCY_CONFLICT` and no provider call.

### `Reconciler.plan(snapshot)`

Input is an immutable sequence-pinned desired revision, authoritative effects, open divergence, normalized provider capabilities, and authorization scope. Output is either a deterministic `ReconciliationPlan`, `MANUAL_ONLY(reason)`, or `NEEDS_AUTHORIZATION(scope)`. Planning has no side effect. Executing each plan step uses normal Operation Manager/SAFEPOINT/ToolRuntime interfaces; the reconciler has no privileged write path.

### `Truthlock.validate(request)`

Input contains the SpeechAct, claim versions and evidence records at `through_sequence`, plus policy version. Output is `APPROVE(template,text)`, `BLOCK(reason,max_certainty)`, or `RETRY_STALE_SNAPSHOT`. The dispatcher journals the corresponding event; it does not enqueue audio directly. Validation is idempotent for `(speech_id, through_sequence, policy_version)`.
