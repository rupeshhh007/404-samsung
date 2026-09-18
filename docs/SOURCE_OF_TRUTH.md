# Source-of-Truth Policy

## Authority

| Concern | Canonical owner |
|---|---|
| Product scope and requirement IDs | `product/REQUIREMENTS.md`, then `product/SCOPE.md` |
| Entities, fields, and enums | `architecture/DOMAIN_MODEL.md` |
| Events and payloads | `architecture/EVENT_MODEL.md` |
| Legal transitions | `architecture/STATE_MACHINES.md` |
| Cross-module calls | `contracts/INTERFACES.md` |
| HTTP/WebSocket/tool/model payloads | corresponding file in `contracts/` |
| Safety rules | `architecture/INVARIANTS.md` |
| Future paths and ownership | `architecture/REPOSITORY_BLUEPRINT.md` |
| Ticket IDs and dependency graph | `delivery/TASK_BACKLOG.md` |
| Functional/contract test IDs | `testing/TEST_STRATEGY.md` |
| Invariant positive/negative test IDs | `testing/INVARIANT_TESTS.md` |
| Demo data and sequence | `demo/DEMO_FIXTURES.md`, `demo/DEMO_SCENARIO.md` |

Examples elsewhere are informative and must conform to these owners. On conflict, the more specific canonical owner wins; unresolved conflicts block implementation and require the contract-change process.

Requirement/test ranges and abbreviated aliases are not canonical identifiers. Normative mappings must list every complete ID. Prose may summarize a group only after linking to its canonical registry.

## Frozen decisions

The product thesis, three pillars, modular monolith, one Python backend, one React frontend, one serialized mutation authority, async work outside the reducer, immutable evidence, conservative unknown tool capabilities, and evidence-gated speech are frozen. Samsung integration is an adapter and must not leak into the generic runtime.

## Change discipline

Shared changes use [the contract-change policy](agents/CONTRACT_CHANGE_POLICY.md): record rationale and compatibility, edit the canonical file first, update dependents, tests, traceability, and version fields in the same change. Architecture decision records in `architecture/DECISIONS.md` close internal questions. Genuine external unknowns use a documented local substitute and integration boundary.

Consistency checks must validate links, entity/enums, event producers and consumers, transitions, interfaces, blueprint-ticket ownership, P0 tests, and demo trace alignment.
