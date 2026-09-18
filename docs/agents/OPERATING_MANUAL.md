# Implementation-Agent Operating Manual

INTERLOCK is a modular-monolith consistency runtime for interruptible real-time agents. The repository documentation is sufficient to implement it without the originating conversation.

## Begin and choose work

Read `README`, `INDEX`, `SOURCE_OF_TRUTH`, requirements, invariants, domain, events, states, interfaces, blueprint, implementation plan, then your component and ticket. Select only the first dependency-unblocked ticket in `TASK_BACKLOG`; confirm its gate and owner. Continue after context reset by rereading the ticket, latest canonical files, and working-tree status.

Implement exact listed paths and public contracts. State changes enter only through journal/reducer. Models return validated proposals. Tools return events. Never create duplicate domain models, invent event fields, bypass the reducer, speculate with write/unknown tools, discard late effects, treat cancellation as rollback, upgrade claim certainty, or report fake test results.

The blueprint assigns one creation ticket to every planned path. A later ticket may edit another ticket’s file only when its backlog row explicitly says so. Use complete IDs from the canonical registries; a combined range or informal test-family label is not an acceptance test.

When a specification conflicts, stop implementation, identify canonical owners via `SOURCE_OF_TRUTH`, and use `CONTRACT_CHANGE_POLICY`; do not resolve public behavior privately. Private algorithms are flexible if externally observable behavior, invariants, and interfaces remain exact.

Write listed unit, contract, transition, negative-invariant, race, and scenario tests. Assert forbidden effects/output as well as expected state. Use virtual time for races. Clearly label mocks/simulation. Run only tests actually available and report exact commands/results; “not run” is acceptable, “passed” without execution is not.

Completion report: ticket, objective, files changed, contracts/events implemented, invariants enforced, tests run/results, integration evidence, documentation changes, known limitations/risks, and next unblocked ticket. Architecture-changing documentation updates must accompany code under the change policy.
