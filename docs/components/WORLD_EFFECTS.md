# World Effects

The ledger is append-only evidence of observed external reality. Result interpretation uses descriptor confirmation semantics and authority: request receipt creates evidence but not a committed effect; authoritative booking confirmation creates/updates an `EffectRecord` keyed by provider effect ID and logical action.

A stale operation's confirmed effect is always recorded. Identical duplicates merge evidence references; a second distinct provider effect under one idempotency identity is retained as a duplicate-effect incident and divergence. Conflicting results lower certainty to unknown and schedule verification. Unknown outcomes remain explicit until `appointment.get` or equivalent authoritatively proves commit/absence.

The authoritative world projection selects latest non-compensated confirmed effects by subject/type while preserving history. It never uses callback arrival order alone. Tests: T-WLD-01, T-IDM-01, T-UNK-01.

## Implementation contract

- Purpose: preserve every authoritative external effect and derive the current observed-world projection.
- Non-responsibilities: selecting desired intent, invoking tools, or deciding compensation.
- State: reducer-owned append-only `EffectRecord` map plus indexes by provider effect ID, logical action, and subject.
- Inputs: validated `ToolResultObserved`, verification evidence, descriptor confirmation semantics. Outputs: `EvidenceRecorded`, `WorldEffectObserved`, and divergence-evaluation commands.

Decision procedure: acknowledgement → evidence only; confirmed final/verification → construct authoritative effect; failed-before-commit → FAILED without effect; timeout/ambiguous post-dispatch → OUTCOME_UNKNOWN; cancellation confirmation → prior COMMITTED effect becomes COMPENSATED through a new observation while history remains. Exact duplicate provider effect/result merges provenance; same provider effect ID with conflicting parameters is quarantined and makes the world projection uncertain; different effect IDs under one logical action are both retained and flagged duplicate.

For bookings, effect subject is `{resource:"appointment", provider_booking_id, center_id}` and parameters include `requested_slot` and `confirmed_slot`. A mismatch from intent still enters the ledger and triggers divergence. Acceptance: `T-WLD-01`, `T-IDM-01`, `T-UNK-01`, `T-INV-I4-P`, `T-INV-I4-N`, `T-INV-I9-P`, and `T-INV-I9-N`. Owner C; depends on EXE-004 and TRU-001.
