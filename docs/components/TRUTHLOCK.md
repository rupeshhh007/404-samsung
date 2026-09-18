# TRUTHLOCK

TRUTHLOCK receives structured `SpeechAct`, sequence-pinned claim snapshots, and requested certainty. It verifies claim existence, state, evidence rule/freshness, slot equality, and controlled template policy.

| Claim/effect state | Maximum wording |
|---|---|
| preparation/read pending | “Checking…” |
| availability confirmed | “The slot is currently available.” |
| dispatch requested | “I’m submitting the booking.” |
| receipt acknowledged | “The service received the request.” |
| committed claim confirmed | “Confirmed — your appointment is booked.” |
| outcome unknown | “I can’t yet verify whether the booking completed.” |
| divergence | “An 11:00 booking exists; you requested 12:00. I’m reconciling it.” |

Unsupported acts are blocked or downgraded to a safe controlled template; a free model rewrite is never permitted to increase certainty. If an emitted statement later becomes contradicted, mark it `CORRECTION_REQUIRED` and propose an explicit correction referencing current evidence. TRUTHLOCK cannot retract heard audio or guarantee source truth. Tests: T-TRU-01 and I6.

## Implementation contract

- Purpose: ensure consequential output certainty does not exceed sequence-pinned claim/evidence state.
- Non-responsibilities: deciding external truth, repairing effects, or cancelling operations.
- State: policy/template registry; SpeechAct lifecycle itself is reducer-owned.
- Input/output: `Truthlock.validate` in `INTERFACES.md`; consumes validation commands and produces approved/blocked facts.

Decision order: validate SpeechAct schema → resolve exact claim versions → reject stale snapshot → reject a success act tied to an OPEN/PLANNED/RECONCILING divergence → compute minimum allowed certainty → verify template is allowed for act/claim state → fill only typed slots → return approve/block. Missing claim, identity mismatch, unresolved relevant divergence, stale/contradicted claim, free-form consequential text, or unsupported template blocks. A safe downgrade creates a new SpeechAct rather than silently changing the requested act.

Validation is idempotent and may run concurrently, but reducer queues approval only if referenced claim versions still match. After emission, contradiction cannot cancel history; `CORRECTION_REQUIRED` produces “Correction: I previously said …; current verified state is …” with supported slots. Acceptance: `T-TRU-01`, `T-SPK-01`, `T-INV-I6-P`, `T-INV-I6-N`, and `T-INV-I9-N`. Owner D; depends on TRU-002 and output contracts.
