# Traceability Matrix

Every requirement has an explicit implementation and test mapping. Canonical entity/event/state/interface details live in the linked owner documents; exact paths live in the blueprint.

| Requirement | Module and canonical contract | Key event/state/invariant | Primary source / ticket | Canonical test(s) | Acceptance; demo/metric |
|---|---|---|---|---|---|
| FR-001 | Runtime; EventEnvelope/JournalPort | accepted sequence; I11 | `runtime/journal.py` / RUN-001 | T-JRN-01, T-DOM-01 | unique monotonic acceptance and dedupe; all steps |
| FR-002 | Runtime; SessionState/Reducer | every event; I11 | `runtime/reducer.py` / RUN-002 | T-RED-01, T-CON-01 | only reducer changes state |
| FR-003 | Semantic Control; ControlIntent | ControlIntentInterpreted; I7 | `intelligence/control.py` / INTEL-001 | T-CTL-01, T-LLM-01 | ten kinds and safe clarification; demo step 6 |
| FR-004 | Intent; IntentRevision/Authorization | revision/auth states; I14 | `intelligence/intent_graph.py` / INTEL-002 | T-INT-01, T-INV-I14-N | provisional and authorization remain independent; step 5 |
| FR-005 | Intent; DependencyBinding | IntentRevisionCommitted/SUPERSEDED; I1 | `intelligence/intent_graph.py` / INTEL-002 | T-INT-02, T-CON-02 | only changed bindings invalidated; stale-prevented metric |
| FR-006 | BranchCache; BranchRecord/BranchPlanner | branch lifecycle; I2 | `intelligence/branch_cache.py` / INTEL-004 | T-BRC-01, T-INV-I2-N | bounded read-only speculation; demo steps 2–3/cache metrics |
| FR-007 | Operations/SAFEPOINT; OperationRecord | dispatch/cancel/effect states; I3/I13 | `execution/operations.py`, `safepoint.py` / EXE-002, EXE-003 | T-SAF-01, T-UNK-01 | orthogonal lifecycles and legal races; steps 5–7 |
| FR-008 | Tools; ToolDescriptor/ToolRegistry | registration; I2 | `execution/descriptors.py` / EXE-001 | T-TOL-01, T-DOM-01 | unknown capabilities fail conservative |
| FR-009 | SAFEPOINT; SafePointPolicy | ToolDispatchRequested; I14 | `execution/safepoint.py` / EXE-003 | T-SAF-02, T-INV-I14-N | stale/unauthorized write never dispatched |
| FR-010 | Operations/Tools; idempotency contract | result dedupe; I5 | `execution/idempotency.py`, `tools.py` / EXE-002, EXE-004 | T-IDM-01, T-INV-I5-N | duplicate logical action does not create second local effect |
| FR-011 | World Effects; EffectRecord | WorldEffectObserved/COMMITTED; I4/I9 | `execution/effects.py` / EXE-005 | T-WLD-01, T-INV-I4-N | stale apt-11 retained; demo step 7/late-effects metric |
| FR-012 | Reconciliation; DivergenceCase/Plan | divergence/plan states; I10 | `execution/reconciliation.py` / EXE-006 | T-REC-01, T-REC-02, T-REC-03, T-E2E-02 | P0 surfaces mismatch; P1 safely repairs or honors denial; steps 8–10 |
| FR-013 | Evidence; EvidenceRecord | EvidenceRecorded; I8 | `truth/evidence.py` / TRU-001 | T-EVD-01, T-INV-I8-N | immutable source plus derived provenance; step 1 |
| FR-014 | ClaimGraph; ClaimRecord | ClaimStateChanged; I9 | `truth/claims.py` / TRU-002 | T-CLM-01, T-INV-I9-N | exact center/slot evidence required; steps 7–10 |
| FR-015 | TRUTHLOCK; SpeechAct/Truthlock | SpeechActApproved/Blocked; sequence pin; I6 | `truth/truthlock.py` / TRU-003 | T-TRU-01, T-INV-I6-N | sequence-pinned approval gate; unsupported success absent; steps 8/10, block metric |
| FR-016 | Speech; SpeechAct | CORRECTION_REQUIRED / RequestSpeechCorrection; I6 | `truth/speech.py` / TRU-004 | T-SPK-01 | contradicted emitted speech triggers RequestSpeechCorrection; explicit correction speech |
| FR-017 | References/Evidence | derived EvidenceRecorded; I8 | `intelligence/references.py` / INTEL-003 | T-REF-01 | prior frame anchored without mutation; demo optional frame step |
| FR-018 | API/WS/Frontend projections | SessionStarted/input/snapshot sequence | `adapters/http.py`, `websocket.py`; frontend clients / API-001, API-002, UI-002 | T-API-01, T-WS-01, T-UI-02, T-UI-03 | accepted commands and lossless resync; all UI steps |
| FR-019 | Scenario/Faults | FaultActivated/virtual time | `testing/clock.py`, `scenario.py`, `faults.py` / TST-001, TST-002 | T-SCN-01, T-FLT-01, T-E2E-02 | reproducible fault catalogue and G-04; scenario success metric |
| FR-020 | Samsung adapter | normalized canonical events | `adapters/samsung.py` / API-003 | T-ADP-01, T-OFF-01 | full simulated mapping, no official claim |
| NFR-001 | Runtime concurrency | sequence/single writer; I11 | journal/reducer/dispatcher / RUN-001, RUN-002, RUN-003 | T-CON-01, T-INV-I11-N | adversarial completions remain deterministic |
| NFR-002 | Metrics | MetricsSnapshot | `metrics.py` / RUN-004 | T-MET-01, T-UI-05 | formulas exact; absent denominator says not measured |
| NFR-003 | Replay | REPLAY mode; I12 | `runtime/reducer.py`, `dispatcher.py` / RUN-002, RUN-003 | T-RPL-01, T-INV-I12-N | equal state and zero external commands |
| NFR-004 | Boundaries/security | ProtocolViolationObserved | config/adapters/providers / INT-001, API-001, EXE-001, INTEL-001 | T-SEC-01, T-CFG-01, T-API-01 | malformed/untrusted data fails closed |
| NFR-005 | Architecture | dependency direction | all module roots / RUN-004 | T-ARC-01 | no Samsung/domain or adapter/domain inversion |
| NFR-006 | Offline composition; fallback + fake provider | startup/provider events | providers/composition / INTEL-001, PRV-001, RUN-004 | T-OFF-01, T-LLM-01 | complete deterministic demo without credentials |
| NFR-007 | Observability; causal/correlation IDs | projections/trace | runtime + frontend / RUN-001, API-002, UI-003 | T-OBS-01, T-UI-02 | input-to-output causal chain visible; demo step 11 |
| NFR-008 | Retention/privacy; session expiry/reset | session/evidence/security | `runtime/session.py`, `truth/evidence.py` / RUN-001, TRU-001 | T-RET-01, T-SEC-01 | memory clears and crash limitation is visible |
| FR-021 | LiveKit voice session | partial/final transcripts, barge-in, safe speech | `adapters/livekit_agent.py` / VCE-001 | T-VOICE-01 | transport bridge and provider-injected worker composition implemented; credentialed room-to-audio smoke remains unverified; browser microphone awaits a secure room/token endpoint |
| FR-022 | FDB-v3 generic tool mapping | fresh scenario and validated tool chains | `adapters/fdb_v3.py` / FDB-001 | T-FDB-01, T-ISO-01 | benchmark runner can call the submitted agent; not implemented yet |
| FR-023 | End-to-end extension | correction, late effect, safe final output | extension demo / EXT-001 | T-EXT-01 | a working recorded use case, not a diagram |
| NFR-009 | One-command reproduction | prerequisites, versions, seeds, nonempty official outputs | `scripts/reproduce_fdb_v3.sh` / FDB-002 | T-FDB-02 | evaluator reruns from supplied instructions; not implemented yet |
| NFR-010 | Honest voice/FDB metrics | timestamped traces and official evaluator artifacts | VCE-001, FDB-002 | T-VOICE-01, T-FDB-02 | measured values with denominators; no fabricated scores |

P2 polish has no requirement IDs and is intentionally deferred; it cannot be a dependency of any P0/P1 ticket.
