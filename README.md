# INTERLOCK

> Anticipate early. Commit safely. Speak only what reality confirms.

INTERLOCK is a consistency runtime for interruptible, real-time, multimodal AI agents. It keeps evolving user intent, concurrent execution, external side effects, evidence, and user-visible claims aligned when an interruption arrives at the worst possible moment.

Its three pillars are:

- **ANTICIPATE** — BranchCache safely prepares likely read-only work.
- **ADAPT** — SAFEPOINT applies explicit cancellation, commit, and reconciliation rules.
- **VERIFY** — ClaimGraph + TRUTHLOCK ensures consequential language never exceeds available evidence.

The system is designed as a modular monolith with a **Python 3.11 / FastAPI backend** and a **React / Vite / Tailwind frontend**.

Async interpretation and tool execution may run concurrently, but every authoritative runtime state transition flows through a serialized event journal and pure reducer.

The primary deterministic demonstration is a simulated **Samsung Device / Service Copilot** where an obsolete 11:00 booking commits late after the user changes their request to 12:00. INTERLOCK records the late commit as external reality, detects the divergence from current intent, reconciles it safely, and prevents the agent from claiming success until reality is verified.

---

## Current Status

**CURRENT PHASE: ACTIVE IMPLEMENTATION**

The core runtime foundation is now under development and several P0 components are implemented.

### Implemented

- **RUN-001 — Event Journal / Session Runtime**
  - Serialized event acceptance
  - Per-session sequencing
  - Session lifecycle and retention

- **RUN-002 — Pure Reducer + Command Contracts**
  - Deterministic state transitions
  - Typed command boundary
  - Replay-safe command suppression
  - Single authoritative state-writer model

- **RUN-003 — Async Command Dispatcher**
  - Explicit asynchronous command routing
  - Replay / disabled-dispatch suppression
  - Journal-only fact ingress
  - Ordered submission with concurrent worker execution
  - Correlation / causation propagation
  - Cross-session protection
  - Defensive command isolation
  - Fail-closed handler boundaries

- **INTEL-001 — Semantic Control Boundary**
  - Model/provider abstraction
  - Conservative control classification
  - Consequential-action confidence gating
  - Clarification fallback

- **EXE-001 — Tool Descriptor Registry**
  - Tool capability manifests
  - Conservative execution defaults
  - Cancellation policy metadata
  - Idempotency / retry / compensation descriptors
  - Stable capability hashing

### In Progress / Upcoming

- Runtime orchestration and composition
- BranchCache
- Operation lifecycle
- SAFEPOINT
- Tool execution and cancellation
- World-effect verification
- Reconciliation
- ClaimGraph
- TRUTHLOCK
- API / WebSocket integration
- Frontend integration
- End-to-end deterministic demo
- Adversarial and invariant testing

---

## Architecture

```text
User / Multimodal Input
        │
        ▼
Semantic Interpreter
        │
        ▼
   Event Journal
        │
        ▼
     Reducer
        │
        ├──► Intent / BranchCache
        │
        ├──► Operation / SAFEPOINT
        │
        └──► Commands
                │
                ▼
        Command Dispatcher
                │
                ▼
        Tool / Runtime Workers
                │
                ▼
           Event Journal
                │
                ▼
        Evidence / ClaimGraph
                │
                ▼
            TRUTHLOCK
                │
                ▼
          User-visible Output
