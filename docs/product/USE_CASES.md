# Use Cases

| ID | Trigger and main flow | Alternatives/failures | Final condition | Requirements / tests |
|---|---|---|---|---|
| UC-01 | Authorized request → prepare → dispatch → authoritative result → confirmed claim. | tool failure yields failure claim | world and intent agree | FR-007, FR-014 / T-E2E-01 |
| UC-02 | Correction while reasoning → old dependency invalidated; obsolete result ignored for active intent. | ambiguous correction clarifies | new revision active | FR-003, FR-005 / T-INT-02 |
| UC-03 | Correction during read-only call → immediate cancel or stale-result cache only. | cancel ignored; result cannot mutate active projection | no world effect | FR-005 / T-CON-02 |
| UC-04 | Correction before commit → cancellation accepted at safe point; new request proceeds. | noncancellable descriptor blocks transition | no obsolete effect | FR-007, FR-009 / T-SAF-01 |
| UC-05 | Correction after remote commit → record old effect and divergence. | callback late/duplicate | observed 11:00 retained | FR-011, FR-012 / T-WLD-01 |
| UC-06 | Late tool result correlates to stale operation. | malformed result quarantined | ledger updated only if authoritative | FR-011 / T-WLD-01 |
| UC-07 | Consequential control confidence below threshold. | nonconsequential backchannel accepted | clarification, no mutation | FR-003 / T-CTL-01 |
| UC-08 | Branch fingerprint matches committed intent → promote cached read. | expired/mismatch becomes miss | no write occurred | FR-006 / T-BRC-01 |
| UC-09 | desired 12:00 differs from observed 11:00. | verification unavailable | divergence surfaced | FR-012 / T-REC-01 |
| UC-10 | authorized reversible obsolete booking → verify, cancel, confirm, book desired, confirm. | intent changes replans | agreement restored | FR-012 / T-E2E-02 |
| UC-11 | compensation fails. | retry only if policy permits | divergence escalated, no success | FR-012, FR-015 / T-REC-02 |
| UC-12 | model proposes “booked” with only acknowledgement. | renderer downgrades to received/pending | success blocked | FR-014, FR-015 / T-TRU-01 |
| UC-13 | “code before this” resolves FRAME-21 over FRAME-38. | uncertain anchor clarifies | new intent edge to immutable record | FR-017 / T-REF-01 |
| UC-14 | write times out after dispatch. | provider supports status lookup | effect `OUTCOME_UNKNOWN` until verified | FR-007, FR-012 / T-UNK-01 |

Actors are the user, frontend/input adapter, runtime, model provider, tool provider, and presenter/fault injector. All flows begin with an active session and valid descriptors; failures preserve traceability and never infer success from arrival order.
