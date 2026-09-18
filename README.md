# INTERLOCK

> Anticipate early. Commit safely. Speak only what reality confirms.

INTERLOCK is a consistency runtime for interruptible, real-time, multimodal AI agents. It keeps evolving user intent, concurrent execution, external side effects, evidence, and user-visible claims aligned when an interruption arrives at the worst possible moment.

Its three pillars are **ANTICIPATE** (BranchCache safely prepares likely read-only work), **ADAPT** (SAFEPOINT applies explicit cancellation and commit rules), and **VERIFY** (ClaimGraph plus TRUTHLOCK permits only evidence-supported consequential language).

The system is a modular monolith: a Python 3.11/FastAPI backend and React/Vite/Tailwind frontend. Async interpretation and tools run concurrently, but every authoritative in-memory state change passes through one serialized event journal and reducer. The primary deterministic demonstration is a simulated Samsung Device/Service Copilot whose obsolete 11:00 booking commits late, is recorded as reality, and is reconciled to the user's corrected 12:00 intent.

**CURRENT PHASE: DOCUMENTATION / DESIGN.**

**APPLICATION IMPLEMENTATION: NOT STARTED.** No setup or run claims in this repository have been verified yet.

## Start here

1. Read the [documentation index](docs/INDEX.md) and [source-of-truth policy](docs/SOURCE_OF_TRUTH.md).
2. Read [requirements](docs/product/REQUIREMENTS.md), [domain model](docs/architecture/DOMAIN_MODEL.md), [event model](docs/architecture/EVENT_MODEL.md), [state machines](docs/architecture/STATE_MACHINES.md), and [interfaces](docs/contracts/INTERFACES.md).
3. Select the first dependency-unblocked ticket from the [backlog](docs/delivery/TASK_BACKLOG.md) and follow the [agent operating manual](docs/agents/OPERATING_MANUAL.md).

The concise architecture overview is [ARCHITECTURE.md](ARCHITECTURE.md); detailed specifications live under `docs/`.
