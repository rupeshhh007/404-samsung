# Scope

## Priorities

| Level | Included | Cut rule |
|---|---|---|
| P0 | journal/reducer, semantic control, intent dependencies, dynamic tools, selective invalidation, SAFEPOINT, world effects, late results, ClaimGraph, TRUTHLOCK, idempotency, deterministic harness, Samsung boundary | Never cut: removing any item breaks the consistency thesis |
| P1 | BranchCache, richer provisional intent, Progressive Truth, automatic reconciliation, temporal reference resolution | BranchCache and reconciliation are demo-critical; degrade to no speculation/manual surfaced divergence |
| P2 | time-travel debugger, live metrics, real VAD/voice, reverse interruption, animation | Cut first; retain textual trace and metric snapshot |

Minimum acceptable MVP is coherent P0 with deterministic correction-before-commit and correction-after-commit tests. The full target adds the P1 late-commit reconciliation path. Degraded demo surfaces the confirmed 11:00/desired 12:00 mismatch and refuses false success if compensation is disabled.

Out of scope: official Samsung claims without supplied specifications, production persistence/HA, arbitrary provider exactly-once guarantees, complex authentication, Redis/Kafka/Kubernetes/Docker, payments, broad RAG, and unrelated assistant workflows.
