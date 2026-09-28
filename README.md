# INTERLOCK

> Anticipate early. Commit safely. Speak only what reality confirms.

INTERLOCK is a consistency runtime for interruptible, real-time, multimodal AI agents. It keeps evolving user intent, concurrent execution, external side effects, evidence, and user-visible claims aligned when an interruption arrives at the worst possible moment.

Its three pillars are:

- **ANTICIPATE** — BranchCache safely prepares likely read-only work.
- **ADAPT** — SAFEPOINT applies explicit cancellation, commit, and reconciliation rules.
- **VERIFY** — ClaimGraph + TRUTHLOCK ensures consequential language never exceeds available evidence.

The system is designed as a modular monolith with a **Python 3.11 / FastAPI backend** and a **React / Vite / Tailwind frontend**.

Async interpretation and tool execution may run concurrently, but every authoritative runtime state transition flows through a serialized event journal and pure reducer.

The updated Theme 05 competition target is a **voice-native LiveKit agent evaluated by Full-Duplex-Bench v3**. INTERLOCK's simulated **Samsung Device / Service Copilot** is the planned additional extension: an obsolete 11:00 booking commits late after the user changes the request to 12:00, and the agent must preserve the late world fact without making an unsupported success claim. The extension is not yet runnable end to end.

---

## Current Status

**CURRENT PHASE: ACTIVE IMPLEMENTATION**

The core runtime foundation is under development. This repository is **not yet a runnable LiveKit/FDB-v3 submission**: the composition root, voice agent, benchmark adapter, one-command reproduction script, ClaimGraph and TRUTHLOCK are not implemented. Do not interpret the tests below as benchmark scores.

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

- **INTEL-002, EXE-002, EXE-003, EXE-004, TRU-001, TST-001, UI-001 — Partial P0 foundations**
  - Intent dependencies, operations/idempotency, SAFEPOINT, generic tool runtime, immutable evidence ingress, deterministic scenario primitives, and an honest disconnected frontend shell

### In Progress / Upcoming

- Runtime orchestration and composition
- BranchCache
- EXE-005 world-effect interpretation, conflict projection, and verification consumer
- Reconciliation
- ClaimGraph
- TRUTHLOCK
- API / WebSocket integration
- Frontend integration
- End-to-end deterministic demo
- Adversarial and invariant testing
- LiveKit voice/session integration and FDB-v3 generic tool adapter
- One-command benchmark reproduction with results/log provenance and fresh scenarios
- One actually working extension, demo video, and slide deck

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
```

The LiveKit voice layer will wrap this runtime as transport; it must not become a second authoritative state writer. Each benchmark scenario must start with fresh session, model context, callback/idempotency state, and provider fixtures.

## Current local verification

With the existing `.venv`, run `PYTHONPATH=backend .venv/bin/pytest -q` and `.venv/bin/python -m compileall -q backend/interlock`. For the frontend shell, use Node.js 20.19+ and run `cd frontend && npm ci && npm run build`; `package-lock.json` pins the tested dependency graph. A green local build does not imply that a LiveKit agent, FDB-v3 evaluation, or the extension demo has run. The one-command benchmark entrypoint is planned under `FDB-002`; there is no valid reproduction command yet. The official [FDB-v3 repository](https://github.com/DanielLin94144/Full-Duplex-Bench/tree/main/v3) documents its own prerequisites and evaluation scripts.
