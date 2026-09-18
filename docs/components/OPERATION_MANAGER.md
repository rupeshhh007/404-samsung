# Operation Manager

The manager creates an `OperationRecord` from a validated descriptor, arguments, committed/provisional scope, exact bindings, logical action ID, and stable idempotency key. It schedules preparation, processes results, and emits commands through reducer decisions.

Operation state describes local workflow; cancellation state describes requests; effect state describes world knowledge. Supersession never deletes an operation or effect. Before dispatch, READY operations are revalidated for active fingerprint and authorization. Cancellation is requested according to policy and never interpreted as success merely because a local task stopped. Identical result callbacks are no-ops; conflicting callbacks cause unknown outcome and verification. A post-dispatch timeout sets effect unknown and prohibits blind write retry unless provider idempotency makes retry safe. Tests: `T-SAF-01`, `T-SAF-02`, `T-IDM-01`, `T-UNK-01`.

## Implementation contract

- Purpose: turn planned tool work into tracked operations while preserving dependencies and idempotency.
- Non-responsibilities: provider transport, effect authority, reconciliation policy, or claim wording.
- State owned: reducer-owned operations and logical-action/idempotency indexes.
- Inputs: descriptor hash, validated args, intent revision/bindings, speculative flag. Outputs: operation/cancellation/dispatch commands and lifecycle events.

Creation rejects unknown descriptors, invalid args, duplicate operation IDs, logical-action reuse with different args, and speculative non-read work. Logical action identity is SHA-256 of tool name + normalized consequential args + intent goal identity; the idempotency key additionally includes session and contract version. Result processing first validates correlation/dedupe, then updates operation dimension; effect interpretation remains separate.

Concurrent supersession never cancels observation. A result can close a WAITING operation; a late result for SUPERSEDED leaves that state unchanged while the ledger updates. Recovery from post-dispatch timeout is verification; retry only reuses the identical key when provider support is declared. Acceptance: the four tests above plus `T-CON-02` and invariants I1/I5/I13/I14. Owner C; depends on INTEL-002 and EXE-001.
