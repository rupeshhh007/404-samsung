# Runtime Architecture

Startup validates configuration and built-in/fake manifests, creates journal/reducer/dispatcher registries, starts workers, then exposes HTTP/WebSocket. A session starts with sequence 1 and a snapshot. Inputs are boundary-validated and journaled; the reducer synchronously produces state plus immutable commands. The dispatcher runs model/tool/output work asynchronously and journals result events.

```mermaid
sequenceDiagram
  participant UI
  participant J as Journal
  participant R as Reducer
  participant D as Dispatcher
  participant T as Tool
  UI->>J: UserInputObserved
  J->>R: next sequence
  R-->>D: InterpretInput command
  D->>J: IntentRevisionProposed
  J->>R: reduce
  R-->>D: Prepare/Dispatch command
  D->>T: invoke(idempotency key)
  T-->>D: result/callback
  D->>J: ToolResultObserved
  J->>R: reduce effect/evidence/claim
  R-->>D: ValidateSpeech
  D->>J: SpeechActApproved/Blocked
  J-->>UI: ordered projection event
```

World-effect processing occurs for every authoritative result, stale or current. Claim evaluation follows evidence/effect updates. Speech validation reads a sequence-pinned snapshot and returns a decision event; the reducer rechecks referenced claim versions before queueing output.

Shutdown stops new sessions, closes intake after accepted work, drains reducers, requests only legal cancellations, marks unresolved dispatched writes unknown, sends final snapshots, then closes workers. Session cleanup occurs after configurable idle retention and is not durable.
