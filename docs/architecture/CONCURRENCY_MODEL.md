# Concurrency Model

Each session has a FIFO intake queue and one reducer task. Journal acceptance under a session lock assigns sequence; the reducer processes sequences strictly without gaps. Different sessions may reduce concurrently. Model, BranchCache, tool, output, and reconciliation tasks are async workers that receive immutable command payloads and return events. They never hold state references.

Dependency fingerprints are SHA-256 over canonical JSON `[{path,value_hash,evidence_ids sorted}]`.

Pre-dispatch validation and dispatch authorization ownership are partitioned cleanly:
- `SafePointPolicy`: Evaluates the pre-dispatch safe point against trusted descriptors, dependency bindings/fingerprints, current intent revision, authorization state, session pause, and cancellation policy. On `CONTINUE`, it emits a `ToolDispatchRequested` event pinned to the exact sequence snapshot (`validated_through_sequence`) evaluated.
- `ToolDispatchRequested`: Carries `validated_through_sequence` representing the sequence through which all pre-dispatch constraints were validated. A missing pin is a fail-closed protocol violation (`MISSING_SAFEPOINT_PIN`).
- `Reducer`: When reducing `ToolDispatchRequested`, classifies the sequence pin before evaluating operation state or dispatch guards:
  - `validated_through_sequence < state.last_sequence`: Legitimate stale concurrency race; the reducer consumes the event as a normal no-op, advances `last_sequence` and metrics to the event sequence, publishes a projection in live execution (zero commands in replay), does NOT mint a token or emit `DispatchTool`, and preserves the current operation exactly as-is in its current state (whether `READY`, `CANCELLED`, `SUPERSEDED`, etc.).
  - `validated_through_sequence == state.last_sequence`: Current decision; only now evaluates operation `READY` state, token absence, session pause, authoritative revision/intent, and cancellation policy guards before minting `dispatch_requested_event_id` and emitting `DispatchTool`.
  - `validated_through_sequence > state.last_sequence`: Claims validation against future authoritative state; fails closed with `RecordProtocolViolation(code="FUTURE_SAFEPOINT_PIN")`, preserves business/entity state, consumes the accepted event in reducer cursor/metrics, and performs no dispatch.
- `ToolRuntime`: Receives `DispatchTool` and performs final trusted descriptor capability identity checks immediately before external provider I/O.
No provider I/O occurs in policy or reducer.

## Critical races

```text
t0 seq 20: operation READY for 11
t1 seq 21: ToolDispatchRequested; worker crosses provider boundary
t2 seq 22: correction to 12 supersedes operation
t3 seq 23: CancellationRequested
t4 provider commits 11 (outside reducer)
t5 seq 24: CancellationAcknowledged (does not prove rollback)
t6 seq 25: ToolResultObserved(commit 11)
t7 seq 26: WorldEffectObserved → divergence
```

Late and duplicate callbacks are correlated by provider request/effect ID and dedupe key. Identical duplicates are no-ops with a metric; conflicting duplicates are violations and force uncertainty. Concurrent corrections serialize; later sequence wins, but each revision remains inspectable. A new correction during reconciliation supersedes the plan and prevents undispatched steps; committed steps remain ledger facts.

Replay consumes journal order and suppresses all dispatcher commands. It reconstructs projections but cannot recover in-memory events after a crash. Shutdown stops intake, drains accepted events, requests cancellation where legal, marks dispatched unresolved writes unknown, and closes clients.

Possible guarantees: deterministic local state, no reducer races, local duplicate suppression, no speculative writes, and honest uncertainty. Impossible without provider support: preventing a crossed-boundary commit, proving remote cancellation from local cancellation, exactly-once remote effects, or learning effects after process loss.

## Ownership and algorithms

The journal owns acceptance order; the reducer owns `SessionState`; workers own only their local task/cancellation token; provider adapters own transport handles; no worker may retain a mutable domain object. Projection publication occurs only after state replacement for the same sequence.

```text
append(candidate):
  lock session
  reject conflicting event_id/dedupe_key
  assign sequence = last_accepted + 1
  store immutable envelope; unlock; enqueue

reduce_loop:
  dequeue next sequence
  assert sequence == state.last_sequence + 1
  new_state, commands = reduce(state, event)
  atomically replace state; publish projection
  if live: submit commands in returned order
```

Workers completing simultaneously race only to journal acceptance. Sequence decides reduction order, but truth policy still evaluates causation, provider identity, and authority rather than treating the last arrival as correct. A callback that arrives before its local cancellation acknowledgement is valid; both facts reduce in assigned order. A callback referencing an unknown operation is quarantined and cannot create an effect.

Backpressure is per session: bounded intake rejects new user commands with retryable overload before acceptance, while already accepted provider callbacks use a reserved lane so real effects are not lost behind user traffic. Session halt stops new commands but continues sanitizing/logging callbacks as far as safely possible. Tests: `T-CON-01`, `T-CON-02`, `T-JRN-01`, `T-RPL-01`.
