# Test Strategy and Functional Test Registry

This file owns every functional, contract, integration, UI, and non-invariant test ID. [Invariant Tests](INVARIANT_TESTS.md) owns the 28 invariant-case IDs. Abbreviated aliases and combined ranges are invalid references.

All backend tests use pytest; race/scenario tests use the virtual clock. Planned files are repository-relative future paths. Every case asserts expected facts and forbidden external effects/output. A test passes only when all listed assertions hold; any unexpected provider call, event, state transition, claim, or speech is failure.

## Runtime, intelligence, and execution

| ID — name | Coverage; module; planned file | Initial conditions and input | Expected events/state/output; pass criteria |
|---|---|---|---|
| T-DOM-01 — Domain serialization | FR-001, FR-007; Domain; `backend/tests/unit/test_domain.py` | construct every valid/invalid entity and enum | valid round-trip stable; missing/unknown/illegal combinations rejected |
| T-CFG-01 — Configuration validation | NFR-004; Config; `backend/tests/unit/test_config.py` | defaults, bounds, missing configured-model key | documented defaults load; invalid startup fails; DEMO fallback succeeds |
| T-JRN-01 — Journal dedupe/order | FR-001; Runtime; `backend/tests/unit/test_journal.py` | session plus identical/conflicting duplicate | one sequence/reduction for identical; conflict violation; no gap |
| T-RED-01 — Pure reducer | FR-002; Runtime; `backend/tests/unit/test_reducer.py` | canonical events and illegal transition | deterministic state/commands; illegal event leaves state unchanged |
| T-RPL-01 — Effect-free replay | NFR-003, I12; Runtime; `backend/tests/unit/test_reducer.py` | completed demo journal in REPLAY | state hash equals live; zero dispatched commands |
| T-CON-01 — Concurrent acceptance | NFR-001, I11; Runtime; `backend/tests/concurrency/test_races.py` | simultaneous valid worker completions | unique contiguous sequence; deterministic legal state |
| T-CON-02 — Stale read completion | FR-005, I1; Intent/Runtime; `backend/tests/concurrency/test_races.py` | corrected slot while old read completes last | stale evidence historical only; active projection unchanged |
| T-OBS-01 — Causal trace completeness | NFR-007; Runtime; `backend/tests/scenarios/test_golden.py` | normal and late-reconcile traces | every output traces to claim/evidence/effect/operation/intent/input IDs |
| T-RET-01 — Retention and restart limits | NFR-008; Runtime; `backend/tests/unit/test_session.py` | expire/reset session and simulate process restart | memory cleared, secret content absent from logs, UI snapshot states loss limitation |
| T-CTL-01 — Ambiguous control clarification | FR-003, I7; Semantic Control; `backend/tests/unit/test_control.py` | ambiguous “stop it”, confidence .70 | `ControlIntentInterpreted(CLARIFY)`; no intent/operation mutation; clarification output |
| T-INT-01 — Provisional authorization separation | FR-004, I14; Intent; `backend/tests/unit/test_intent_graph.py` | partial “book ten” without authorization | PROVISIONAL/unauthorized revision; zero write dispatch |
| T-INT-02 — Selective invalidation | FR-005, I1; Intent; same file | warranty plus slot 11, correction to 12 | only slot bindings invalidated; warranty work remains valid |
| T-REF-01 — Temporal evidence reference | FR-017, I8; References; `backend/tests/unit/test_references.py` | FRAME-21, FRAME-38, “before this” | derived anchor to FRAME-21; sources unchanged; ambiguity clarifies |
| T-BRC-01 — Speculation gate/promotion | FR-006, I2; BranchCache; `backend/tests/unit/test_branch_cache.py` | read candidate then attempted write candidate | read may prepare/promote on exact fingerprint; write rejected before adapter |
| T-TOL-01 — Conservative manifest | FR-008, I2; Tools; `backend/tests/contract/test_manifests.py` | omit effect/cancel/retry metadata | IRREVERSIBLE/NONCANCELLABLE/no retry/no speculation defaults |
| T-IDM-01 — Idempotent write/callback | FR-010, I5; Operations; `backend/tests/unit/test_tools.py` | duplicate retry and duplicate callback | same key/args makes one logical effect; conflicting args rejected |
| T-SAF-01 — Correction before dispatch | FR-007, I3; SAFEPOINT; `backend/tests/unit/test_safepoint.py` | correction before named safe point | cancellation acknowledged locally; operation CANCELLED/SUPERSEDED; no 11 call/effect |
| T-SAF-02 — Dispatch revalidation | FR-009, I14; SAFEPOINT; same file | READY operation with stale fingerprint/expired auth | no `ToolDispatchRequested`; hold/cancel reason exact |
| T-WLD-01 — Late effect retention and projection | FR-011, I4/I9/I10; Effects; `backend/tests/unit/test_effects.py` | stale book11 callback; conflicting authoritative A/B; scoped verification C; compensation success/failure/unknown/conflict; duplicate physical IDs | immutable history retained; unresolved projection until decisive causally scoped verification (supporting either A or B); later ordinary/insufficient/conflicting verification cannot win by arrival; replay same projection with zero commands; each duplicate physical ID individually targetable; no unsupported success speech |
| T-UNK-01 — Unknown write outcome | FR-007, I13; Operations; `backend/tests/unit/test_operations.py` | timeout after dispatch | operation TIMED_OUT/effect OUTCOME_UNKNOWN; verification scheduled; no blind retry |
| T-REC-01 — Successful reconciliation | FR-012, I10; Reconciliation; `backend/tests/unit/test_reconciliation.py` | authorized reversible 11 vs desired 12 | verify/cancel/verify/book/verify order; final case RESOLVED and claim confirmed |
| T-REC-02 — Failed compensation | FR-012, I10; Reconciliation; same file | cancellation terminal failure | plan FAILED, case ESCALATED, world remains 11, uncertainty output, no success |
| T-REC-03 — Reconciliation authorization denied | FR-012, I10; Reconciliation; same file | PLANNED repair receives explicit DENY | `ReconciliationDenied`; plan FAILED, case ESCALATED/manual-only, zero compensation/booking calls |

## Truth, contracts, scenarios, and UI

| ID — name | Coverage; module; planned file | Initial conditions and input | Expected events/state/output; pass criteria |
|---|---|---|---|
| T-EVD-01 — Evidence immutability | FR-013, I8; Evidence; `backend/tests/unit/test_evidence.py` | same evidence ID with changed content | original retained; conflict violation; derived records allowed |
| T-CLM-01 — Booking evidence rule | FR-014, I9; ClaimGraph; `backend/tests/unit/test_claims.py` | receipt, mismatched confirmation, exact normal confirmation, and reconciliation commit before/after final verify | PENDING, then CONTRADICTED/separate effect; normal exact commit confirms; reconciliation claim confirms only after exact `VERIFY_FINAL` evidence |
| T-TRU-01 — Unsupported success blocked | FR-015, I6; TRUTHLOCK; `backend/tests/unit/test_truthlock.py` | confirmed wording with pending/unknown claim | `SpeechActBlocked` or safe pending template; no confirmed phrase |
| T-SPK-01 — Emitted correction | FR-016, I6; Speech; `backend/tests/unit/test_speech.py` | emitted claim later contradicted | history remains EMITTED; CORRECTION_REQUIRED and supported correction act |
| T-API-01 — HTTP acceptance semantics | FR-018, NFR-004; API; `backend/tests/contract/test_http.py` | valid/invalid/retried session commands | documented statuses/bodies; 202 means accepted only; stable request dedupe |
| T-WS-01 — Stream resynchronization | FR-018; WebSocket; `backend/tests/contract/test_websocket.py` | duplicate, gap, reconnect after N | duplicates ignored; gap pauses; snapshot atomically restores contiguous projection |
| T-LLM-01 — Structured model fallback | FR-003, FR-004, FR-006, FR-017, NFR-004, NFR-006; Model; `backend/tests/contract/test_llm.py` | valid, extra-field, timeout, unavailable outputs | valid proposal accepted; invalid repaired once then fallback/clarify; no direct action |
| T-SEC-01 — Boundary fail-closed | NFR-004; All; `backend/tests/contract/test_security.py` | malformed input/manifest/model/result and injected instruction | rejected/quarantined or unknown; zero unsafe tool/speech; secrets redacted |
| T-ADP-01 — Samsung-shaped mock mapping | FR-020; Adapter; `backend/tests/contract/test_samsung.py` | all provisional inbound/outbound mock messages | canonical IDs/events/descriptors/results; every datum labeled simulated |
| T-OFF-01 — Credential-free mode | NFR-006; Composition; `backend/tests/scenarios/test_golden.py` | no network/model/Samsung credentials | fallback + fake provider completes deterministic demo; no real-integration claim |
| T-SCN-01 — Scenario determinism | FR-019; Harness; `backend/tests/scenarios/test_golden.py` | same YAML twice | identical envelopes, logical times, state/effect/claim/speech hashes |
| T-FLT-01 — Fault catalogue | FR-019; Faults; `backend/tests/scenarios/test_faults.py` | each documented fault | exact scheduled fault behavior and corresponding safe runtime outcome |
| T-MET-01 — Metric formulas | NFR-002; Metrics; `backend/tests/unit/test_metrics.py` | known event trace and empty denominator | exact derived counters/durations; “not measured” not zero; no invented values |
| T-ARC-01 — Dependency direction | NFR-005; Architecture; `backend/tests/contract/test_architecture.py` | planned/imported module graph | no domain→adapter or Samsung→domain dependency |
| T-E2E-01 — Normal booking | FR-007, FR-009, FR-014, FR-015; Integration; `backend/tests/scenarios/test_golden.py` | G-01 fixture | exact golden order; one apt-12 effect; confirmation only after authoritative evidence |
| T-E2E-02 — Late reconciliation | FR-006, FR-011, FR-012, FR-014, FR-015, FR-019; Integration; same file | canonical 0–2000 ms scenario | 1100 ms open checkpoint and 2000 ms resolved checkpoint exactly match G-04 |
| T-UI-01 — Shell and empty/error states | FR-018; Frontend; `frontend/src/test/components.test.tsx` | disconnected, empty, loading, errors | accessible exact states; no implied success |
| T-UI-02 — Projection reducer | FR-018, NFR-007; Frontend; `frontend/src/test/projections.test.ts` | snapshot plus ordered/duplicate/gapped deltas | deterministic views; gap marks stale; no client-derived truth |
| T-UI-03 — Reconnect client | FR-018; Frontend; `frontend/src/test/reconnect.test.ts` | disconnect at sequence N | reconnect asks after N; snapshot/delta recovery; duplicates ignored |
| T-UI-04 — Core workflow accessibility | FR-015, FR-018; Frontend; `frontend/src/test/components.test.tsx` | P0 booking/divergence projections | exact controlled text, keyboard/focus/live-region and non-color status assertions |
| T-UI-05 — P1 demo panels | FR-006, FR-012, NFR-002; Frontend; `frontend/src/test/components.test.tsx` | branch/reconciliation/metrics projections | ANTICIPATE, stepper, and measured/not-measured metrics render accurately |

## Updated Theme 05 acceptance (planned; not currently passing)

| ID — name | Coverage; module; planned file | Initial conditions and input | Expected events/state/output; pass criteria |
|---|---|---|---|
| T-VOICE-01 — LiveKit interruption and progress | FR-021, NFR-010; `backend/tests/contract/test_livekit.py` | partial/final speech with filler, false start, barge-in during speech and slow tool | safe spoken progress begins before tool completion; partial text never authorizes write; speech cancels independently; final correction updates active arguments; measured timings reported, not assumed |
| T-FDB-01 — Generic FDB-v3 mapping | FR-022; `backend/tests/contract/test_fdb_v3.py` | tool descriptions, chained calls, self-correction and malformed arguments without benchmark answer fixtures | names/arguments map through validated descriptors, stale calls fail safely, no duplicate write or scenario-specific logic |
| T-ISO-01 — Fresh benchmark scenario | FR-022; `backend/tests/contract/test_fdb_isolation.py` | run two conversations with overlapping IDs | second has no first-session operations, callbacks, idempotency, branches, model context, evidence or effects |
| T-FDB-02 — Reproduction fails loudly | NFR-009, NFR-010; `backend/tests/contract/test_fdb_reproduction.py` | missing data/key, empty input, and valid configured subset | invalid prerequisites/nonempty-output checks fail nonzero; valid run invokes official inference and evaluation with recorded versions/seeds/logs; no score asserted without execution |
| T-EXT-01 — Working voice extension | FR-023; existing scenario/golden suite and live demo | spoken booking corrected during tool work | extension runs end to end, retains late physical effect, blocks false done claim, and shows authoritative final/uncertain state |

## Suite execution policy

Ticket ownership is exact:

- `TST-003`: `T-DOM-01`, `T-CFG-01`, `T-JRN-01`, `T-RED-01`, `T-RPL-01`, `T-CON-01`, `T-CON-02`, `T-OBS-01`, `T-RET-01`, `T-CTL-01`, `T-INT-01`, `T-INT-02`, `T-TOL-01`, `T-IDM-01`, `T-SAF-01`, `T-SAF-02`, `T-WLD-01`, `T-UNK-01`, `T-EVD-01`, `T-CLM-01`, `T-TRU-01`, `T-SPK-01`, `T-API-01`, `T-WS-01`, `T-LLM-01`, `T-SEC-01`, `T-ADP-01`, `T-OFF-01`, `T-SCN-01`, `T-FLT-01`, `T-MET-01`, `T-ARC-01`, and `T-E2E-01`.
- `TST-004`: `T-REF-01`, `T-BRC-01`, `T-REC-01`, `T-REC-02`, `T-REC-03`, and `T-E2E-02`.
- `UI-004`: `T-UI-01`, `T-UI-02`, `T-UI-03`, and `T-UI-04`.
- `UI-005`: `T-UI-05`.
- `VCE-001`: `T-VOICE-01`; `FDB-001`: `T-FDB-01`, `T-ISO-01`; `FDB-002`: `T-FDB-02`; `EXT-001`: `T-EXT-01`. These are planned acceptance cases, not current test results.

Invariant ticket ownership is exact in `INVARIANT_TESTS.md`: `TST-004` owns `T-INV-I2-P`, `T-INV-I2-N`, `T-INV-I10-P`, and `T-INV-I10-N`; `TST-003` owns the other 24 named invariant cases. These are ticket assignments, not alternative test IDs.
