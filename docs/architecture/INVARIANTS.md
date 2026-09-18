# Invariants

| ID | Formal rule / enforcement | Counterexample and detection | Positive / negative test | Events / states |
|---|---|---|---|---|
| I1 | An obsolete read result may populate historical/cache evidence but not active-intent projection; reducer compares fingerprint. | old availability overwrites current slot; fingerprint mismatch metric | T-INV-I1-P, T-INV-I1-N | result; operation superseded |
| I2 | `speculative ⇒ descriptor.action_type=READ_ONLY ∧ effect_classification=NONE`; ToolRuntime hard rejects. | branch calls booking | T-INV-I2-P, T-INV-I2-N | OperationCreated; branch states |
| I3 | cancellation transition follows descriptor policy and named safe point. | forced stop of NONCANCELLABLE call | T-INV-I3-P, T-INV-I3-N | CancellationRequested; cancellation machine |
| I4 | authoritative committed effects are append-only regardless of intent age. | discard late 11 booking | T-INV-I4-P, T-INV-I4-N | WorldEffectObserved; COMMITTED |
| I5 | one logical action/idempotency key maps to at most one local committed-effect identity unless provider proves distinct effects. | retry duplicates booking | T-INV-I5-P, T-INV-I5-N | ToolResultObserved; effect ledger |
| I6 | rendered certainty ≤ minimum certainty allowed by all required claims/evidence. | “confirmed” from acknowledgement | T-INV-I6-P, T-INV-I6-N | SpeechActBlocked; claim/speech |
| I7 | consequential low-confidence control cannot mutate intent/operation; it produces clarification. | uncertain “stop it” cancels booking | T-INV-I7-P, T-INV-I7-N | ControlIntentInterpreted |
| I8 | EvidenceRecord content/provenance is immutable; corrections create new records/edges. | FRAME-21 rewritten to E17 | T-INV-I8-P, T-INV-I8-N | EvidenceRecorded |
| I9 | truth uses causal/provider authority, not arrival timestamp/order alone. | fast ack treated as commit | T-INV-I9-P, T-INV-I9-N | ToolResultObserved; claim states |
| I10 | desired/observed mismatch has an OPEN/active case or verified resolution. | hidden 11 vs 12 | T-INV-I10-P, T-INV-I10-N | DivergenceDetected |
| I11 | only reducer advances `SessionState.last_sequence`. | worker edits operation map | T-INV-I11-P, T-INV-I11-N | all events |
| I12 | replay emits zero external-dispatch commands. | replay repeats booking | T-INV-I12-P, T-INV-I12-N | replay mode |
| I13 | post-dispatch timeout remains `OUTCOME_UNKNOWN` until authoritative verification. | timeout declared failure and retried | T-INV-I13-P, T-INV-I13-N | ToolTimedOut |
| I14 | consequential writes require committed active intent and `AUTHORIZED`. | final transcript auto-books | T-INV-I14-P, T-INV-I14-N | ToolDispatchRequested |

Preconditions are validated entities and descriptor registrations. Invariant violation handling is fail-closed: reject the transition/command, append a sanitized violation fact when safe, increment metrics, and expose an actionable error. Tests are detailed in [Invariant Tests](../testing/INVARIANT_TESTS.md).
