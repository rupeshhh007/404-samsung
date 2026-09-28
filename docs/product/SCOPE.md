# Scope

## Priorities

| Level | Included | Cut rule |
|---|---|---|
| P0 | journal/reducer, semantic control, intent dependencies, dynamic tools, selective invalidation, SAFEPOINT, world effects, late results, ClaimGraph, TRUTHLOCK, idempotency, deterministic harness, LiveKit voice-agent wrapper, FDB-v3 tool adapter, isolated scenario lifecycle, and reproducible benchmark command | Never cut: internal safety and official voice/benchmark requirements are both submission-critical |
| P1 | BranchCache, richer provisional intent, Progressive Truth, automatic reconciliation, temporal reference resolution | BranchCache and reconciliation are demo-critical; degrade to no speculation/manual surfaced divergence |
| P2 | time-travel debugger, extra visualization/animation, optional nonessential voice polish | Cut first; voice-native LiveKit operation itself is P0, not polish |

Minimum competition submission is a working LiveKit agent that FDB-v3 can rerun from a clean scenario, plus one actually demonstrated extension and reproducible instructions/results provenance. Coherent deterministic correction-before/after-commit tests remain an internal P0 gate. The full extension adds P1 late-commit reconciliation; degraded behavior surfaces confirmed 11:00/desired 12:00 mismatch and refuses false success if compensation is disabled.

Out of scope: official Samsung claims without supplied specifications, production persistence/HA, arbitrary provider exactly-once guarantees, complex authentication, Redis/Kafka/Kubernetes/Docker, payments, broad RAG, and unrelated assistant workflows.
