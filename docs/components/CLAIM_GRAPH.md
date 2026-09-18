# ClaimGraph

Claims are predicate nodes linked to required evidence rules and supporting records. Creation starts PROPOSED; missing but attainable evidence yields PENDING; authoritative matching evidence yields CONFIRMED; authoritative conflict yields CONTRADICTED; conflicting/unknown outcome yields UNCERTAIN; expired dependencies yield STALE; replacement yields SUPERSEDED.

Booking rules:

| Claim | Minimum evidence |
|---|---|
| slot available | fresh authoritative availability result for exact center/slot |
| request received | provider acknowledgement explicitly defined as receipt |
| appointment booked | authoritative commit result or verification with provider booking ID, exact center/slot, committed status; when the booking is a reconciliation step, also require the plan’s `VERIFY_FINAL` evidence and no unresolved case for that resource |
| appointment cancelled | authoritative cancellation confirmation or verification proving absence/cancelled state |

Evaluation runs after relevant evidence/effect/intent events. Revalidation never mutates evidence and produces `ClaimStateChanged`. Submitting or acknowledging is insufficient for booked. Tests: T-CLM-01.

## Implementation contract

- Purpose: maintain explicit propositions and evidence dependencies.
- Non-responsibilities: fabricating evidence, invoking tools, rendering language, or changing world effects.
- State: reducer-owned claim nodes and reverse indexes from evidence/effect/intent dependencies.
- Inputs: claim proposals, immutable evidence/effects, intent revisions, expiry ticks. Outputs: `ClaimProposed` and legal `ClaimStateChanged` events.

Evaluation is deterministic: validate evidence rule → discard stale/non-authoritative candidates → compare required identity/parameters → CONFIRMED only if all clauses hold; authoritative conflict gives CONTRADICTED; ambiguous/unknown outcome gives UNCERTAIN; attainable missing evidence gives PENDING. Re-evaluate only claims in the reverse-dependency closure. Concurrent evidence is reduced in sequence, but authority/causality decides the state.

For `appointment booked`, evidence must prove `BOOKING_CONFIRMED` and exact `provider_request_id`, `provider_booking_id`, `center_id`, `requested_slot`, and `confirmed_slot`; both slots must equal the claim's desired slot. A normal booking can confirm from the authoritative commit result. A reconciliation booking remains PENDING until `VERIFY_FINAL` proves the current world and the related divergence can resolve. A real mismatched booking confirms a separate world-effect claim and contradicts the desired-booking claim. Acceptance: `T-CLM-01`, `T-WLD-01`, `T-INV-I6-N`, `T-INV-I9-N`. Owner D; depends on TRU-001 and EXE-005.
