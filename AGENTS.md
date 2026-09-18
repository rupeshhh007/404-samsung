# Repository Guidelines

INTERLOCK is a documentation-first design for a consistency runtime for interruptible real-time agents. Phase 0 permits Markdown documentation only; application code, tests, manifests, dependencies, infrastructure, and scaffolding must not be created until implementation is explicitly authorized.

The authority order is: `docs/SOURCE_OF_TRUTH.md`; canonical requirements/contracts in `docs/product`, `docs/architecture`, and `docs/contracts`; component specifications; testing/demo specifications; then delivery guidance. If files conflict, stop and follow `docs/agents/CONTRACT_CHANGE_POLICY.md`; never silently invent or change a shared schema.

Mandatory reading order for implementation work:

1. `README.md`, `docs/INDEX.md`, and `docs/SOURCE_OF_TRUTH.md`.
2. `docs/product/REQUIREMENTS.md` and `docs/architecture/INVARIANTS.md`.
3. `docs/architecture/DOMAIN_MODEL.md`, `EVENT_MODEL.md`, and `STATE_MACHINES.md`.
4. `docs/contracts/INTERFACES.md` plus the assigned component contract.
5. The assigned ticket in `docs/delivery/TASK_BACKLOG.md` and its referenced tests.

The frozen modular-monolith design has one serialized reducer as the only authoritative state writer. Models and tools emit validated events; reducers never call external services. Speculative branches cannot perform writes. Confirmed late effects are retained. Consequential speech must pass TRUTHLOCK.

Work ticket-by-ticket. Implement only listed files and dependencies; add unit, contract, state-machine, negative-invariant, and deterministic scenario tests as assigned. Report files changed, contracts implemented, tests actually run and their results, known gaps, and documentation updates. Do not report unexecuted tests as passing.

Before creating a file, verify its single creation ticket in `docs/architecture/REPOSITORY_BLUEPRINT.md`. Use only complete canonical requirement, ticket, and test IDs; do not use shorthand ranges. P0 work must not depend on P1/P2 tickets.

See [the detailed operating manual](docs/agents/OPERATING_MANUAL.md).
