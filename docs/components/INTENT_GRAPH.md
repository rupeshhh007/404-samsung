# Intent Graph

Each goal has stable `IntentNode` identity and immutable revision chain. A delta inherits unspecified values, applies validated sets/unsets, records evidence, computes maturity/authorization independently, and supersedes the prior active revision when committed.

## Selective invalidation

1. Canonicalize every changed path and hash its new value.
2. For each nonterminal operation/branch, inspect its `DependencyBinding` paths.
3. Recompute only bindings whose path is changed or whose ancestor/descendant changed.
4. If any value/evidence hash differs, mark fingerprint stale; otherwise retain it across the global revision change.
5. Stale undispatched write operations are cancelled/superseded; dispatched ones remain observed. Stale reads may finish into historical/cache evidence but cannot update active projections.
6. Recompute active candidates and emit explicit invalidation events.

Promotion from provisional to committed creates a revision; authorization is granted only by an explicit user/policy event tied to the exact fingerprint. Example: changing `appointment.requested_slot` invalidates availability/booking bound to slot but retains `device.warranty` bound only to device ID. Tests: `T-INT-01` and `T-INT-02`.
