# Development Runbook

These are **planned, unverified Phase 0 commands** and must be confirmed after source/manifests exist.

Prerequisites: Python 3.11, Node LTS compatible with chosen Vite release, npm, and two terminals. Planned backend: `cd backend`, create/activate a local virtual environment, `python -m pip install -e ".[dev]"`, copy documented `.env.example`, then `python -m uvicorn interlock.main:app --reload`. Planned frontend: `cd frontend`, `npm install`, `npm run dev`.

Planned tests: backend `python -m pytest`; focused golden `python -m pytest tests/scenarios/test_golden.py`; frontend `npm test`; build `npm run build`. Demo uses `INTERLOCK_MODE=DEMO`, fallback model, fake provider, then UI reset/load `samsung-demo-v1`.

Troubleshooting: configuration failure → compare [Configuration](../contracts/CONFIGURATION.md); import/schema mismatch → G1 not met; disconnected UI → health and WS URL/origin; sequence gap → snapshot resync; scenario nondeterminism → remove wall clock/randomness; unknown booking → run verification, never blind retry; no API key → ensure fallback; no Samsung access → fake adapter is expected.
