# Future Repository Blueprint

These paths are planned; none exists in Phase 0. “Creation ticket” is unique. A later ticket may modify a file only when the backlog explicitly says so.

| Future path(s) | Responsibility / public contract | Creation ticket / owner | Planned tests |
|---|---|---|---|
| `backend/pyproject.toml`; `backend/interlock/__init__.py`; `backend/interlock/config.py`; `.env.example` | package and validated Settings | INT-001 / A | T-DOM-01, T-CFG-01 |
| `backend/interlock/domain/enums.py`; `backend/interlock/domain/models.py`; `backend/interlock/domain/events.py` | canonical enums, entities, event payload registry | INT-001 / A | T-DOM-01 |
| `backend/interlock/runtime/journal.py`; `backend/interlock/runtime/session.py` | JournalPort and session registry/retention | RUN-001 / A | T-JRN-01, T-RET-01 |
| `backend/interlock/runtime/reducer.py`; `backend/interlock/runtime/commands.py` | pure reducer and command union | RUN-002 / A | T-RED-01, T-RPL-01, invariant tests |
| `backend/tests/test_world_effect_contract.py` | append-only reducer/verification regressions for shared world-effect ingress; may be extended by TST-003 | INT-002 / A, with C review | T-WLD-01, T-INV-I4-N, T-INV-I9-N |
| `backend/interlock/runtime/dispatcher.py` | async command execution and replay suppression | RUN-003 / A | T-CON-01, T-RPL-01 |
| `backend/interlock/intelligence/control.py`; `backend/interlock/providers/base.py`; `backend/interlock/providers/llm.py`; `backend/interlock/providers/fallback.py` | semantic/model provider contracts and offline rules | INTEL-001 / B | T-CTL-01, T-LLM-01 |
| `backend/interlock/intelligence/intent_graph.py` | revisions, bindings, fingerprints, invalidation | INTEL-002 / B | T-INT-01, T-INT-02, T-CON-02 |
| `backend/interlock/intelligence/references.py` | temporal evidence references | INTEL-003 / B | T-REF-01 |
| `backend/interlock/intelligence/branch_cache.py` | bounded speculative read policy | INTEL-004 / B | T-BRC-01 |
| `backend/interlock/execution/descriptors.py` | manifest normalization/registry | EXE-001 / C | T-TOL-01 |
| `backend/interlock/execution/operations.py`; `backend/interlock/execution/idempotency.py` | operation lifecycle and logical-action dedupe | EXE-002 / C | T-IDM-01, T-UNK-01 |
| `backend/interlock/execution/safepoint.py` | dispatch revalidation and cancellation decisions | EXE-003 / C | T-SAF-01, T-SAF-02 |
| `backend/interlock/execution/tools.py` | generic ToolRuntime and private inward provider transport Protocol; no fake-provider or external adapter implementation | EXE-004 / C | T-IDM-01, T-SEC-01, T-UNK-01 |
| `backend/interlock/execution/effects.py` | append-only world ledger/projection | EXE-005 / C | T-WLD-01 |
| `backend/interlock/execution/reconciliation.py` | divergence and repair plans | EXE-006 / C | T-REC-01, T-REC-02, T-REC-03 |
| `backend/interlock/truth/evidence.py` | immutable evidence/provenance | TRU-001 / D | T-EVD-01 |
| `backend/interlock/truth/claims.py` | ClaimGraph evaluation | TRU-002 / D | T-CLM-01 |
| `backend/interlock/truth/truthlock.py` | SpeechAct evidence gate | TRU-003 / D | T-TRU-01 |
| `backend/interlock/truth/speech.py` | output lifecycle and corrections | TRU-004 / D | T-SPK-01 |
| `backend/interlock/adapters/http.py` | FastAPI command endpoints | API-001 / A | T-API-01 |
| `backend/interlock/adapters/websocket.py` | ordered projection stream/resync | API-002 / A | T-WS-01 |
| `backend/interlock/adapters/protocol.py`; `backend/interlock/adapters/samsung.py` | generic and Samsung-shaped provisional mappings | API-003 / A | T-ADP-01 |
| `backend/interlock/providers/fake_tools.py`; `backend/interlock/testing/fixtures.py`; `backend/tests/fixtures/demo.json`; `backend/tests/fixtures/manifests.json` | deterministic simulated provider and data | PRV-001 / C | T-OFF-01, T-ADP-01 |
| `backend/interlock/testing/clock.py`; `backend/interlock/testing/scenario.py` | virtual clock and DSL runner | TST-001 / A | T-SCN-01 |
| `backend/interlock/testing/faults.py`; `backend/scenarios/normal.yaml`; `backend/scenarios/correction_before.yaml`; `backend/scenarios/late_reconcile.yaml`; `backend/scenarios/unknown.yaml`; `backend/scenarios/compensation_failure.yaml` | fault engine and canonical scenarios | TST-002 / C | T-FLT-01 |
| `backend/interlock/metrics.py`; `backend/interlock/main.py` | metrics and composition root | RUN-004 / A | T-MET-01, T-ARC-01, T-OFF-01 |
| `backend/tests/unit/test_domain.py`; `backend/tests/unit/test_config.py`; `backend/tests/unit/test_journal.py`; `backend/tests/unit/test_session.py`; `backend/tests/unit/test_reducer.py`; `backend/tests/unit/test_control.py`; `backend/tests/unit/test_intent_graph.py`; `backend/tests/unit/test_operations.py`; `backend/tests/unit/test_safepoint.py`; `backend/tests/unit/test_tools.py`; `backend/tests/unit/test_effects.py`; `backend/tests/unit/test_evidence.py`; `backend/tests/unit/test_claims.py`; `backend/tests/unit/test_truthlock.py`; `backend/tests/unit/test_speech.py`; `backend/tests/unit/test_metrics.py` | P0 unit and invariant cases | TST-003 / A, modifies test files with owning module reviewers | exact TST-003 assignments in the two canonical test registries |
| `backend/tests/contract/test_http.py`; `backend/tests/contract/test_websocket.py`; `backend/tests/contract/test_manifests.py`; `backend/tests/contract/test_llm.py`; `backend/tests/contract/test_samsung.py`; `backend/tests/contract/test_security.py`; `backend/tests/contract/test_architecture.py`; `backend/tests/concurrency/test_races.py`; `backend/tests/scenarios/test_golden.py`; `backend/tests/scenarios/test_faults.py` | P0 contract/race/scenario suite | TST-003 / A | P0 registry |
| `backend/tests/unit/test_references.py`; `backend/tests/unit/test_branch_cache.py`; `backend/tests/unit/test_reconciliation.py` | P1 component tests; `test_golden.py` later gains G-04 | TST-004 / A; modifies `test_golden.py` | T-REF-01, T-BRC-01, T-REC-01, T-REC-02, T-REC-03, T-E2E-02, T-INV-I2-P, T-INV-I2-N, T-INV-I10-P, T-INV-I10-N |
| `frontend/package.json`; `frontend/vite.config.ts`; `frontend/tailwind.config.ts`; `frontend/src/main.tsx`; `frontend/src/App.tsx`; `frontend/src/styles/index.css` | React composition and base styles | UI-001 / D | T-UI-01 |
| `frontend/src/api/http.ts`; `frontend/src/api/websocket.ts`; `frontend/src/api/types.ts`; `frontend/src/state/store.ts`; `frontend/src/state/projections.ts` | exact clients, sequence/resync, read-only projections | UI-002 / D | T-UI-02, T-UI-03 |
| `frontend/src/components/SessionBar.tsx`; `frontend/src/components/InputPanel.tsx`; `frontend/src/components/IntentPanel.tsx`; `frontend/src/components/OperationPanel.tsx`; `frontend/src/components/WorldPanel.tsx`; `frontend/src/components/ClaimPanel.tsx`; `frontend/src/components/TruthBanner.tsx`; `frontend/src/components/DivergenceAlert.tsx`; `frontend/src/components/TraceTimeline.tsx`; `frontend/src/pages/CopilotPage.tsx`; `frontend/src/pages/TracePage.tsx` | P0 conversation, consistency, divergence, truth, trace views | UI-003 / D | T-UI-01, T-UI-04 |
| `frontend/src/test/setup.ts`; `frontend/src/test/projections.test.ts`; `frontend/src/test/components.test.tsx`; `frontend/src/test/reconnect.test.ts` | P0 frontend tests | UI-004 / D | T-UI-01 through T-UI-04 |
| `frontend/src/components/ReconciliationStepper.tsx`; `frontend/src/components/MetricsPanel.tsx`; `frontend/src/components/BranchCachePanel.tsx` | demo-critical P1 views; UI-005 also modifies `frontend/src/pages/CopilotPage.tsx`, `frontend/src/pages/TracePage.tsx`, and `frontend/src/test/components.test.tsx` | UI-005 / D | T-UI-05 |

Dependency direction: domain ← policies ← runtime/application ← adapters/providers; frontend shares transport shapes only. No path is authorized before Phase 1. The table gives every planned file exactly one creation ticket; later modifications are explicitly named.
