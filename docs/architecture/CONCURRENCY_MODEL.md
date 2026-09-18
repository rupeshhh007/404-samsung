# Concurrency Model

Each session has a FIFO intake queue and one reducer task. Journal acceptance under a session lock assigns sequence; the reducer processes sequences strictly without gaps. Different sessions may reduce concurrently. Model, BranchCache, tool, output, and reconciliation tasks are async workers that receive immutable command payloads and return events. They never hold state references.

Dependency fingerprints are SHA-256 over canonical JSON `[{path,value_hash,evidence_ids sorted}]`. Before dispatch, the reducer recomputes bindings against the active revision and requires equality, authorization, and descriptor policy.

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
