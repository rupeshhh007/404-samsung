# Frontend Architecture

React pages are `CopilotPage` and `TracePage`; components are enumerated in the blueprint. A small reducer/store holds only the latest backend projection, connection state, and last sequence. `http.ts` submits commands with stable client IDs; `websocket.ts` applies contiguous deltas, ignores duplicates, detects gaps, and atomically replaces from snapshot.

Event mapping: intent revisions update `IntentPanel`; operation/cancellation events update `OperationPanel`; world effects update `WorldPanel`; claim/speech decisions update `ClaimPanel`/`TruthBanner`; divergence/plan events drive `DivergenceAlert`/`ReconciliationStepper`; every sanitized event appends `TraceTimeline`; metric snapshots update `MetricsPanel`.

Errors distinguish disconnected/stale, validation, provider failure, unknown outcome, and unresolved divergence. Loading and empty states never imply success. Keyboard focus, live regions for status (not every trace event), text plus icons beyond color, WCAG-aware contrast, and responsive stacking are required. Tests cover projections, reconnect/gaps, components, accessibility, and end-to-end demo. The frontend never derives authoritative truth.
