# Ownership

| Module | Primary | Reviewer | Dependencies / interfaces | Integration responsibility |
|---|---|---|---|---|
| Journal, reducer, sessions, FastAPI, WebSocket, protocol, scenario integration | Owner A — Runtime | D | domain/events; JournalPort, ProjectionHub | compose app; preserve sequencing/replay |
| Semantic control, intent graph, provisional intent, BranchCache, evidence references | Owner B — Intelligence | A | model/evidence; ControlInterpreter, BranchPlanner | exact fingerprints and model fallback |
| Operations, SAFEPOINT, ToolRuntime, descriptors, idempotency, effects, reconciliation | Owner C — Execution | A | intent/auth; ToolExecutor, Reconciler | all external-effect boundaries |
| ClaimGraph, TRUTHLOCK, Progressive Truth, frontend, trace, metrics | Owner D — Truth & Product | B | evidence/effects; ClaimEvaluator, Truthlock | end-to-end visible truth and UI |

Shared domain/event/interface changes require all affected owners and contract policy. A integrates backend composition; D integrates frontend contract; C owns fake provider effects; B owns demo interpretation. Each owner supplies contract tests to the next consumer.

Creation ownership is file-specific in `REPOSITORY_BLUEPRINT.md`; this table owns module responsibility, not permission for two tickets to create the same path. First work after the shared INT-001 contract gate: B takes INTEL-001 or INTEL-002, C takes EXE-001, and D takes TRU-001 or UI-001. Owner A completes INT-001, then RUN-001.
