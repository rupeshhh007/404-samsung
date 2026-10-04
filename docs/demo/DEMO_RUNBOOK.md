# Demo Runbook

This is the credential-free EXT-001 P0 demo. It runs the **REAL** INTERLOCK
runtime, reducer, SAFEPOINT, ToolRuntime, EffectInterpreter, ClaimGraph and
TRUTHLOCK against **SIMULATED** Samsung-shaped data. Provider response latency
is **SCRIPTED**. Input interpretation uses the deterministic **FALLBACK**; this
does not claim access to an official Samsung API or any benchmark result.

Prerequisites: Python 3.11, the repository virtual environment, Node 20.19 or
newer, and installed frontend dependencies. No Samsung or model credential is
required.

Terminal 1, from the repository root:

```bash
INTERLOCK_MODE=DEMO \
INTERLOCK_MODEL_PROVIDER=fallback \
INTERLOCK_FAKE_LATENCY_MS=3000 \
PYTHONPATH=backend \
.venv/bin/python -m uvicorn interlock.main:app --host 127.0.0.1 --port 8000
```

Check `http://127.0.0.1:8000/api/v1/health`; it must return
`{"status":"ok","mode":"DEMO"}` before starting the frontend.

Terminal 2:

```bash
cd frontend
VITE_INTERLOCK_API_URL=http://127.0.0.1:8000/api/v1 npm run dev
```

Open `http://localhost:5173`. Start a fresh DEMO session, enter `Book 11:00.`,
then enter `Actually, make it 12:00.` while the first request is delayed. The
canonical P0 endpoint is:

- desired slot is 12:00;
- the old 11:00 operation has a cancellation request/too-late result;
- the authoritative late 11:00 effect is retained;
- the 12:00 claim remains `PENDING`;
- an `OPEN` divergence is visible;
- TRUTHLOCK permits only the exact uncertainty text rendered by the console
  output adapter, whose terminal fact records `heard=false` because it is text,
  not audio.

No automatic repair is attempted. EXE-006/TST-004/UI-005 own reconciliation.
Use `POST /api/v1/sessions/{id}/demo/reset` or the UI Reset action with fixture
`samsung-demo-v1`; the returned replacement session must begin at sequence 1.

Troubleshooting: a WebSocket gap requires snapshot resync; if the correction
arrives after the scripted delay, reset and retry; if a success claim appears
for 12:00 without new authoritative evidence, stop—the demo has violated its
truth contract.
