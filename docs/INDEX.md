# Documentation Index

Status: Phase 0 design repaired and audited; implementation not started. External Samsung protocols, credentials, and provider guarantees are unavailable and isolated behind the adapter.

## Reading order

Product readers: [Product](product/PRODUCT.md) → [Requirements](product/REQUIREMENTS.md) → [Journeys](product/USER_JOURNEYS.md). Implementers: [Source of truth](SOURCE_OF_TRUTH.md) → canonical architecture contracts → assigned component → backlog ticket → tests. Demo operators: [Scenario](demo/DEMO_SCENARIO.md) → [Fixtures](demo/DEMO_FIXTURES.md) → [Runbook](demo/DEMO_RUNBOOK.md).

## Map

- Root: [README](../README.md) entry point; [AGENTS](../AGENTS.md) contributor rules; [Architecture](../ARCHITECTURE.md) overview.
- Product: [PRODUCT](product/PRODUCT.md) vision; [REQUIREMENTS](product/REQUIREMENTS.md) IDs; [USE_CASES](product/USE_CASES.md) behavior; [SCOPE](product/SCOPE.md) priorities; [USER_JOURNEYS](product/USER_JOURNEYS.md) experience.
- Architecture: [SYSTEM](architecture/SYSTEM_ARCHITECTURE.md) boundaries; [RUNTIME](architecture/RUNTIME_ARCHITECTURE.md) execution; [BLUEPRINT](architecture/REPOSITORY_BLUEPRINT.md) future files; [DOMAIN](architecture/DOMAIN_MODEL.md) schemas; [EVENTS](architecture/EVENT_MODEL.md) facts; [STATES](architecture/STATE_MACHINES.md) transitions; [CONCURRENCY](architecture/CONCURRENCY_MODEL.md) races; [INVARIANTS](architecture/INVARIANTS.md) safety; [SECURITY](architecture/SECURITY_AND_TRUST.md) trust; [GUARANTEES](architecture/GUARANTEES_AND_LIMITATIONS.md) limits; [DECISIONS](architecture/DECISIONS.md) ADRs.
- Contracts: [INTERFACES](contracts/INTERFACES.md), [HTTP](contracts/HTTP_API.md), [WEBSOCKET](contracts/WEBSOCKET_PROTOCOL.md), [TOOLS](contracts/TOOL_DESCRIPTOR.md), [SAMSUNG](contracts/SAMSUNG_ADAPTER.md), [LLM](contracts/LLM_CONTRACTS.md), [CONFIG](contracts/CONFIGURATION.md).
- Components: [journal/reducer](components/EVENT_JOURNAL_AND_REDUCER.md), [semantic control](components/SEMANTIC_CONTROL.md), [intent graph](components/INTENT_GRAPH.md), [BranchCache](components/BRANCHCACHE.md), [operations](components/OPERATION_MANAGER.md), [SAFEPOINT](components/SAFEPOINT.md), [tool runtime](components/TOOL_RUNTIME.md), [world effects](components/WORLD_EFFECTS.md), [reconciliation](components/RECONCILIATION.md), [evidence](components/EVIDENCE_AND_PROVENANCE.md), [claims](components/CLAIM_GRAPH.md), [TRUTHLOCK](components/TRUTHLOCK.md), [speech](components/SPEECH_AND_OUTPUT.md), [frontend](components/FRONTEND.md).
- Testing: [strategy](testing/TEST_STRATEGY.md), [scenario DSL](testing/SCENARIO_DSL.md), [faults](testing/FAULT_INJECTION.md), [golden traces](testing/GOLDEN_TRACES.md), [invariant tests](testing/INVARIANT_TESTS.md), [metrics](testing/METRICS.md).
- Demo: [scenario](demo/DEMO_SCENARIO.md), [fixtures](demo/DEMO_FIXTURES.md), [runbook](demo/DEMO_RUNBOOK.md), [UI](demo/UI_SPECIFICATION.md).
- Delivery: [ownership](delivery/OWNERSHIP.md), [plan](delivery/IMPLEMENTATION_PLAN.md), [backlog](delivery/TASK_BACKLOG.md), [development](delivery/DEVELOPMENT_RUNBOOK.md), [risks](delivery/RISKS_AND_DEPENDENCIES.md), [traceability](delivery/TRACEABILITY.md), [checklist](delivery/COMPLETION_CHECKLIST.md), [handoff audit](delivery/HANDOFF_AUDIT.md).
- Agents: [operating manual](agents/OPERATING_MANUAL.md), [task template](agents/TASK_TEMPLATE.md), [contract changes](agents/CONTRACT_CHANGE_POLICY.md), [AI use](agents/AI_USAGE.md).
