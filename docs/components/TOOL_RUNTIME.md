# ToolRuntime

At startup the registry normalizes/validates manifests. Invocation validates arguments, speculation authorization, active dispatch authorization, retry/idempotency policy, timeout, and compensation reference. It sends the same idempotency key for safe retries, maps provider request IDs, normalizes results/errors, and journals every observation.

Read retries may follow the descriptor. Writes default to one attempt; retry is allowed only when the same provider-scoped idempotency key is declared safe. Cancellation uses the provider adapter but local task cancellation is not reported as remote cancellation. Result schema failure is `PROVIDER_PROTOCOL_ERROR`; post-dispatch ambiguity becomes unknown. Duplicate callbacks are detected by event/dedupe/provider-effect identity.

No tool-name or Samsung-specific business branch determines safety. A speculative non-read invocation returns `SPECULATION_FORBIDDEN` before adapter dispatch. Tests: T-TOL-01, T-IDM-01, T-SEC-01.

## Implementation contract

- Purpose: validate descriptors/invocations, cross the external boundary, normalize observations, and enforce retry/cancellation/speculation rules.
- Non-responsibilities: authoritative state mutation, intent selection, effect/claim interpretation, or reconciliation planning.
- State: registry/capability hashes and ephemeral invocation handles; authoritative operations remain reducer-owned.
- Inputs/outputs: `ToolExecutor.invoke` in `INTERFACES.md`; consumes `DispatchTool`/`RequestToolCancellation` and handles `PrepareOperation` (replacing the builtin dispatcher handler in composed runtime); produces `ToolDispatchAccepted`, `ToolResultObserved`, `ToolTimedOut`, `CancellationAcknowledged`, `CancellationRejected`, `CancellationTooLate`, or sanitized protocol-failure observations.

Invocation order is fixed: resolve trusted descriptor hash → validate schema → enforce speculation → verify immutable dispatch authorization token (`dispatch_requested_event_id` from accepted `ToolDispatchRequested`) → reserve idempotency identity → call provider transport → journal acceptance/result. Argument or capability mismatch fails before I/O. For writes, attempt 2+ is permitted only with declared provider idempotency, identical normalized args, identical key, and retryable policy. A changed key creates a new logical action and requires new authorization.

Cancellation sends the provider request only when supported; local task cancellation does not suppress callbacks. Result normalization checks outer/nested request IDs, conditional result schema, and provider-effect identity. Malformed pre-dispatch responses fail; malformed/ambiguous post-dispatch responses set outcome unknown and request verification. EXE-004 creates `execution/tools.py` containing ToolRuntime and its private inward provider transport Protocol/callable. ToolRuntime does not depend on or create `adapters/protocol.py` (API-003); external adapters and fakes depend inward on this transport contract later. Acceptance: `T-TOL-01`, `T-IDM-01`, `T-SEC-01`, `T-UNK-01`, and the I2/I5/I13 invariant cases. Owner C; adapter-specific behavior stays outside this module.
