# Implementation Plan

## Gates

1. Shared contracts: INT-001; gate G1 schemas import and examples validate.
2. Runtime foundation: RUN-001, RUN-002, RUN-003; G2 journal/reducer/replay pass.
3. Intent/execution: INTEL-001, INTEL-002, EXE-001, EXE-002, EXE-003, EXE-004; G3 safe correction-before-commit.
4. Effects/truth: INT-002, TRU-001, EXE-005, TRU-002, TRU-003, TRU-004; G4 late effect and unsupported speech tests. EXE-005 consumes the accepted CCR-001 immutable-observation and targeted-verification contract.
5. Deterministic P0 integration: RUN-004, API-001, API-002, API-003, PRV-001, TST-001, TST-002, TST-003 plus UI-001 through UI-004; G5 offline P0 golden and core UI run.
6. Demo-critical P1: INTEL-003, INTEL-004, EXE-006, TST-004, UI-005; G6 full late-repair trace and G7 presenter rehearsal/reset.
7. Competition integration: VCE-001 → FDB-001 → FDB-002, in parallel with extension work EXT-001 after its dependencies; require an actual LiveKit session, generic FDB-v3 mapping, isolated scenarios, and a nonempty official evaluator run before claiming benchmark readiness.
8. Validation: all P0/P1 demo tests, voice/benchmark/isolation/reproduction tests, docs/contracts, risks; G8 submission readiness only after external credentials/data and demo artifacts are verified.

One agent executes the dependency-ordered sequence in the backlog. Four agents first complete INT-001/G1, then A builds runtime/API/harness, B intelligence, C execution/providers, and D truth/frontend in parallel. P0 completes without any P1/P2 dependency; P1 is integrated only after G5. Agents integrate at gates using frozen interfaces, with A checking domain/event compatibility and D validating projections. No agent creates a file owned by another creation ticket or bypasses a gate with a private schema.
