# Security and Trust

This hackathon prototype validates but does not become an identity platform. User transcripts/images, model JSON, manifests, tool results, and WebSocket client messages are untrusted. Pydantic/JSON Schema boundaries reject unknown critical fields, size-limit content, use content references rather than raw images in logs, and redact secrets and personal details.

Tool manifests require an allowlisted registration source in demo mode. Unknown effect, cancellation, retry, confirmation, or compensation capability defaults to the most conservative behavior. User authorization is revision- and argument-bound; speculative context cannot authorize a write. Prompt text cannot dispatch tools.

Prompt injection in frames/transcripts is treated as content, never instructions to bypass policies. Runtime model results are validated proposals. Only deterministic policy selects tools, changes intent, or approves speech. Consequential actions and compensation require the authorization specified by their descriptor/plan.

Credentials are environment-only, never returned to frontend or journaled. Demo fixtures contain no real customer/device data and are visibly labeled simulated. Evidence/event retention is session-memory-only, configurable, and cleared on reset/process exit. Production use would need authentication, encrypted persistence, access control, audit retention, abuse controls, and privacy review; these are outside Phase 0.
