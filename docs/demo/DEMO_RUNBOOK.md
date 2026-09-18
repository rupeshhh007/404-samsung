# Demo Runbook

All commands are **planned and unverified Phase 0 instructions**. Prerequisites after implementation: Python 3.11, supported Node LTS, repository dependencies, two terminals; no Samsung or model key is required for deterministic mode.

Planned setup/start: follow [Development Runbook](../delivery/DEVELOPMENT_RUNBOOK.md), select `INTERLOCK_MODE=DEMO`, load `samsung-demo-v1`, start backend/frontend, open localhost. Reset through `POST /api/v1/sessions/{id}/demo/reset` or UI Reset and verify sequence 1, empty provider bookings, fault enabled.

Presenter script exactly follows [Demo Scenario](DEMO_SCENARIO.md). Pause after “Book 11” until submission appears; issue the correction before logical callback; advance/run the scripted fault; point out late effect, divergence, TRUTHLOCK block, repair steps, and final evidence. Expected final provider state is only confirmed apt-12 with apt-11 cancelled.

Fallback: run pre-authored `late_reconcile.yaml`; if automatic repair fails, demonstrate honest surfaced divergence. Troubleshooting: sequence gap → resync; wrong timing → reset virtual scenario; no model → fallback badge; no final confirmation → inspect claim evidence and provider verification; stale prior booking → reset fixture, do not manually fake the UI.
