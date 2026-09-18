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
| descriptor changed/unknown | HOLD | no dispatch; protocol/configuration error |
| speculative and not READ_ONLY/NONE | CANCEL | operation CANCELLED; I2 violation metric |
| fingerprint stale or intent superseded | CANCEL | cancellation requested/operation SUPERSEDED; no call |
| consequential and not COMMITTED+AUTHORIZED | HOLD | request clarification/authorization; no call |
| session paused | HOLD | remain READY until resume/revalidation |
| cancellation REQUESTED and policy IMMEDIATE/AT_SAFEPOINT | CANCEL | acknowledge local pre-dispatch cancellation |
| current and permitted | CONTINUE | journal `ToolDispatchRequested`; operation DISPATCHED |

After `ToolDispatchRequested`, the commit boundary is considered crossed for safety even if `ToolDispatchAccepted` has not arrived; a timeout is not proof of absence. Cancellation commands may still be sent, but results remain admissible. `NONCANCELLABLE` records `REQUESTED` and continues observation. Duplicate cancellation is idempotent. Conflicting acknowledgements become protocol violations/unknown outcome.

Recovery: before boundary, correct inputs and re-prepare a new operation; after boundary, verify outcome and reconcile. Acceptance: `T-SAF-01`, `T-SAF-02`, `T-WLD-01`, `T-UNK-01`, `T-INV-I3-P`, `T-INV-I3-N`, `T-INV-I14-P`, and `T-INV-I14-N`. Owner C; dependencies EXE-001, EXE-002, and active intent contracts.
