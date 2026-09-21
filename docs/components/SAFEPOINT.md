# SAFEPOINT

Consequential work follows local `PREPARE → BEFORE_PROVIDER_DISPATCH safe point → COMMIT`. Providers need not implement prepare: validation, prerequisite reads, argument construction, and authorization checks are local.

At every named safe point policy compares current revision/fingerprint, pause state, authorization, cancellation request, and descriptor. `IMMEDIATE` may cancel local pre-dispatch work; `AT_SAFEPOINT` stops only at a declared point; `NONCANCELLABLE` records the request but continues observation. An acknowledgement proves only its descriptor-defined scope, never absence of a remote effect.

```text
dispatch crosses boundary | correction | cancel request | provider commit | callback
        cannot retract -----------^             effect must be recorded
```

Pre-dispatch stale/unauthorized work is cancelled without effect. After crossing the boundary, cancellation races are represented, results remain admissible, and timeout becomes unknown. Failures before dispatch are safe failures; provider errors after dispatch follow confirmation semantics/verification. Tests: `T-SAF-01`, `T-SAF-02`, and race golden traces.

## Implementation contract

- Purpose: make the last local decision before provider dispatch and apply descriptor-specific preemption.
- Non-responsibilities: killing arbitrary remote work, proving cancellation, interpreting commit evidence, or repairing divergence.
- State read: operation, cancellation, active revision/fingerprint, authorization, pause flag, descriptor capability hash. It consumes `SafePointReached`, `CancellationRequested`, revision/authorization facts, and dispatch status; state writes occur only through reducer events.
- Interface: `SafePointPolicy.decide` returns `CONTINUE`, `CANCEL`, `HOLD`, or `UNKNOWN` plus commands; it performs no I/O.

| Condition at `BEFORE_PROVIDER_DISPATCH` | Decision | State/event consequence |
|---|---|---|
| current descriptor missing/unknown | HOLD | no dispatch; protocol/configuration error |
| operation creation-time descriptor capability hash unavailable (`None`) | HOLD | no dispatch; capability provenance unavailable |
| stored creation-time descriptor capability hash differs from current registry hash | HOLD | no dispatch; descriptor changed |
| speculative and not READ_ONLY/NONE | CANCEL | operation CANCELLED; I2 violation metric |
| fingerprint stale or intent superseded | CANCEL | cancellation requested/operation SUPERSEDED; no call |
| consequential and not COMMITTED+AUTHORIZED | HOLD | request clarification/authorization; no call |
| `SessionState.paused=true` | HOLD | remain READY until resume/revalidation |
| cancellation REQUESTED and policy IMMEDIATE (or AT_SAFEPOINT with `BEFORE_PROVIDER_DISPATCH` in descriptor safe points) | CANCEL | acknowledge local pre-dispatch cancellation |
| current and permitted | CONTINUE | emit `ToolDispatchRequested` carrying `validated_through_sequence` snapshot pin |

### SafePoint Sequence Pin and Dispatch Authorization
On `CONTINUE`, the follow-up `ToolDispatchRequested` event carries `validated_through_sequence`, representing the exact sequence from the reducer state snapshot against which `SafePointPolicy.decide` evaluated all pre-dispatch constraints. The reducer classifies the pin before checking operation state or dispatch guards:
- **Matching pin (`validated_through_sequence == state.last_sequence`)**: Current decision; the reducer evaluates operation `READY` state, token absence, and session/revision invariants before minting `dispatch_requested_event_id` and emitting `DispatchTool`. A matching pin permits reducer consideration; it is NOT automatic authorization for external provider I/O.
- **Stale pin (`validated_through_sequence < state.last_sequence`)**: Legitimate stale concurrency race where the session advanced between safe-point evaluation and event acceptance. The reducer consumes the event as a normal no-op, advances `last_sequence` and metrics to the event sequence, publishes a projection in live execution (zero commands in replay), does NOT mint a dispatch token, emits no commands, and preserves the current operation exactly as-is in its current state (e.g. `READY`, `CANCELLED`, `SUPERSEDED`, etc.). No protocol violation is recorded.
- **Future pin (`validated_through_sequence > state.last_sequence`)**: Claims validation against future authoritative state; fails closed with `RecordProtocolViolation(code="FUTURE_SAFEPOINT_PIN")`, preserves business/entity state, consumes the accepted event in reducer cursor/metrics, and performs no dispatch.
- **Missing / malformed pin (`validated_through_sequence is None`)**: Malformed internal protocol input; fails closed with `RecordProtocolViolation(code="MISSING_SAFEPOINT_PIN")`, preserves business/entity state, and consumes the accepted event in reducer cursor/metrics.
- **AT_SAFEPOINT cancellation**: `AT_SAFEPOINT` cancellation is descriptor- and named-safe-point-specific. `SafePointPolicy` checks whether `SafePointName.BEFORE_PROVIDER_DISPATCH` is declared in the trusted descriptor's `safe_points`. The reducer does not blanket-block `AT_SAFEPOINT` cancellation without descriptor context, relying on `SafePointPolicy` and the sequence pin.

A matching stored and current capability hash passes only the descriptor-consistency check; it never implies dispatch authorization. SAFEPOINT must still evaluate revision and fingerprint freshness, authorization, pause state, cancellation policy/state, speculative restrictions, operation state, and every other applicable condition. The stored creation-time hash is also the expected capability identity for ToolRuntime's existing pre-I/O capability check, closing a descriptor-change race between SAFEPOINT evaluation and provider dispatch.

`SessionState.paused=true` holds pre-dispatch work; `paused=false` only permits evaluation of the remaining checks and does not itself authorize dispatch. Pause is reversible runtime control, not cancellation and not the fatal `SessionRegistry` halt state.

After `ToolDispatchRequested`, the commit boundary is considered crossed for safety even if `ToolDispatchAccepted` has not arrived; a timeout is not proof of absence. Cancellation commands may still be sent, but results remain admissible. `NONCANCELLABLE` records `REQUESTED` and continues observation. Duplicate cancellation is idempotent. Conflicting acknowledgements become protocol violations/unknown outcome.

Recovery: before boundary, correct inputs and re-prepare a new operation; after boundary, verify outcome and reconcile. Acceptance: `T-SAF-01`, `T-SAF-02`, `T-WLD-01`, `T-UNK-01`, `T-INV-I3-P`, `T-INV-I3-N`, `T-INV-I14-P`, and `T-INV-I14-N`. Owner C; dependencies EXE-001, EXE-002, and active intent contracts.
