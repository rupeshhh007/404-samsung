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

The core runtime foundation is under development. The LiveKit/FDB-v3 adapter and one-command official evaluator path are implemented, but a real run still requires the separately distributed official dataset, LiveKit credentials, and model-provider credentials. No benchmark score is claimed by this repository; only artifacts produced by an actual evaluator run are results.

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

- **VCE-001, FDB-001, FDB-002 — Live benchmark delivery path**
  - LiveKit voice/session ingress on one authoritative INTERLOCK session
  - Generic FDB-v3 tool mapping through SAFEPOINT and ToolRuntime
  - Fresh Application, model, tool, callback, and idempotency state per benchmark room
  - One-command official inference/evaluation with fail-closed provenance

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

## Official FDB-v3 reproduction

The wrapper requires Python 3.11, `livekit-agents==1.8.4`, `ffmpeg`, the provider-specific LiveKit plugin, and the official FDB audio/metadata dependencies (`numpy`, `python-dotenv`, NeMo ASR, `pydub`, `ffmpeg-python`, and `openai`). The official benchmark checkout is pinned to commit `3e799c45a045256f47d5f1c9cda90157e2d2ec9e`; the wrapper refuses another commit unless `FDB_V3_BENCHMARK_COMMIT` explicitly pins that checkout. Exact resolved package versions are written to each run's provenance.

Prepare a clean Python 3.11 virtual environment, install this backend plus the official [FDB-v3 prerequisites](https://github.com/DanielLin94144/Full-Duplex-Bench/tree/3e799c45a045256f47d5f1c9cda90157e2d2ec9e/v3), install `ffmpeg`, and check out the pinned benchmark:

```bash
git clone https://github.com/DanielLin94144/Full-Duplex-Bench.git ../Full-Duplex-Bench
git -C ../Full-Duplex-Bench checkout 3e799c45a045256f47d5f1c9cda90157e2d2ec9e
```

Set `FDB_V3_REPO`, `FDB_V3_DATA_DIR`, `FDB_V3_PROVIDER`, `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET`, `OPENAI_API_KEY` (also required by the latency evaluator), and the selected provider's key (`XAI_API_KEY`, `GOOGLE_API_KEY`, `ULTRAVOX_API_KEY`, or the three Azure variables). Then the complete inference and official evaluation path is one command:

```bash
./scripts/reproduce_fdb_v3.sh
```

Optional reproducibility controls are `FDB_V3_SEED` (default `0`), `FDB_V3_LATENCY_PROFILE` (default `instant`), `FDB_V3_USE_LLM_JUDGE` (`0` or `1`), `FDB_V3_RUN_ID`, and `FDB_V3_OUTPUT_DIR`. By default, logs, raw per-example results, official tool/pass-rate/latency evaluator outputs, and `provenance.json` are stored under `artifacts/fdb-v3/<UTC run id>/`. The command exits nonzero for missing prerequisites/config/data, agent or evaluator failure, zero completed examples, or absent evaluator artifacts. It never substitutes local expected calls, answers, or scores.

## Current local verification

With the existing `.venv`, run `PYTHONPATH=backend .venv/bin/pytest -q` and `.venv/bin/python -m compileall -q backend/interlock`. For the frontend shell, use Node.js 20.19+ and run `cd frontend && npm ci && npm run build`; `package-lock.json` pins the tested dependency graph. A green local build does not imply that a real FDB-v3 benchmark scenario or the extension demo has run.
