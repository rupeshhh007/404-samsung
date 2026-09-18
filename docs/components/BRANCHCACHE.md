# BranchCache

After a stable input, the predictor proposes at most configured top-K (default 2, maximum 3) candidates. Deterministic policy filters confidence, budget cost, trusted descriptors, exact bindings, and duplicate candidates. Each record expires after TTL, is evicted lowest confidence then oldest, and is invalidated on binding or descriptor capability-hash change.

Preparation may call only tools whose normalized descriptor is `READ_ONLY` with no effect. ToolRuntime independently enforces this at invocation, so a model/policy bug cannot dispatch a write. Results are evidence scoped to the branch. Promotion requires unexpired READY state and exact candidate/fingerprint equality with committed intent; otherwise it is a miss and normal work runs. Unknown tool effects are ineligible.

Metrics: candidates, preparations, hits, misses by reason, latency saved (normal estimated/read latency minus promotion latency, never fabricated), expired/evicted/invalidated/discarded cost. Tests: T-BRC-01 plus I2 negative test.

## Implementation contract

- Purpose: reduce perceived latency by preparing likely read-only results.
- Non-responsibilities: committing intent, authorizing operations, invoking writes, or deciding truth/speech.
- State: reducer-owned `BranchRecord` map and aggregate budget usage; workers receive copies only.
- Inputs: active revision, candidate deltas, trusted descriptors, current logical time, top-K/TTL/cost limits. Outputs: `BranchPredicted`, `BranchPreparationStarted`, read-only `OperationCreated`, `BranchPreparationCompleted`, `BranchPromoted`, and `BranchInvalidated`.

Selection sorts eligible candidates by confidence descending, then stable candidate hash; accepts until top-K or budget is exhausted. Eligibility requires confidence above configured policy, complete bindings, explicit READ_ONLY/NONE descriptor, and no equivalent live branch. Promotion compares candidate delta, fingerprint, capability hash, expiry, and READY state atomically at reduction time. Miss reasons are `NOT_FOUND`, `NOT_READY`, `EXPIRED`, `FINGERPRINT_MISMATCH`, or `CAPABILITY_CHANGED`.

Concurrent promotion and expiry are resolved by journal sequence. Worker completion after invalidation may add historical evidence but cannot restore the branch. Provider/model failure marks FAILED and returns budget; no retry unless normal read retry policy permits it. Acceptance: `T-BRC-01`, `T-INV-I1-N`, `T-INV-I2-N`, `T-MET-01`. Dependency/owner: INTEL-002 + EXE-001/EXE-003; Owner B, reviewer A/C.
