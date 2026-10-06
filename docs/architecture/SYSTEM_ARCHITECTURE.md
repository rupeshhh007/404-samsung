# System Architecture

```mermaid
flowchart LR
  U[User] --> F[React UI]
  F -->|HTTP commands / WS projections| A[FastAPI adapters]
  A --> J[Journal + reducer]
  J --> D[Async command dispatcher]
  D --> M[Model provider or fallback]
  D --> P[Tool provider or fake]
  P --> J
  M --> J
  J --> G[Intent / effects / evidence / claims]
  G --> X[TRUTHLOCK]
  X --> F
```

Allowed dependencies point inward: adapters → application/runtime → domain policies. Provider implementations depend on contract protocols, never the reverse. The reducer owns all session state. Adapters validate untrusted transport; model outputs are proposals; provider observations require descriptor-defined authority. Commands flow outward from reducer decisions, facts flow inward through the journal, and projections flow read-only to clients.

Trust boundaries exist at user input, model output, tool manifests/results, network transports, and frontend. Secrets stay in provider adapters and never enter event payloads. The Samsung adapter maps provisional external messages to generic events/tools; domain modules contain no Samsung-specific branches.

A modular monolith minimizes deployment and ordering complexity for four hackathon developers while retaining module protocols and tests. The UI can be replaced without altering consistency rules; the deterministic fake provider can replace external integration without altering the tool contract.

For the updated Theme 05 target, LiveKit Agents is the voice transport/session runtime, not the authoritative domain state writer. A thin adapter maps audio/transcript hypotheses, final text, barge-in and speech-cancellation observations to journaled facts; it maps approved output back to LiveKit speech. Model, perception and tool work remain asynchronous around the serialized reducer. The FDB-v3 adapter maps benchmark tool names/arguments/results generically to registered descriptors and starts/tears down a fresh INTERLOCK session for every benchmark conversation. This composition is planned under `VCE-001`, `FDB-001`, and `FDB-002`; no current repository path yet provides a working LiveKit/FDB agent.

```text
LiveKit audio/session → input observations → journal/reducer → control/SAFEPOINT
                                              ↓                    ↓
                                     approved speech ← truth gate ← async tools/models
FDB-v3 runner → fresh LiveKit conversation and generic tool protocol per scenario
```

Major responsibilities are detailed in [Interfaces](../contracts/INTERFACES.md) and [component specifications](../INDEX.md#map).
