# Canonical Event Model

The journal is the sole acceptor. It generates UUIDv7 event IDs, assigns the next per-session integer sequence under the session lock, validates payload/schema, and rejects an already-seen `event_id` or `dedupe_key`. `occurred_at` is observational; sequence orders reduction, while causation/correlation establish lineage. Commands request work and are never written as facts until an executor reports an event.

## Envelope

```json
{"event_id":"evt-42","session_id":"demo","sequence":42,"event_type":"ToolResultObserved","source":"TOOL","occurred_at":"2030-01-15T05:35:00Z","logical_time":1100,"schema_version":1,"correlation_id":"op-book-11","causation_id":"evt-dispatch-11","dedupe_key":"provider:req-11:callback-1","payload":{"operation_id":"op-book-11","provider_request_id":"req-11","outcome":"SUCCEEDED","provider_effect_id":"apt-11","result":{"phase":"FINAL","status":"BOOKING_CONFIRMED","provider_request_id":"req-11","provider_booking_id":"apt-11","center_id":"ctr-01","requested_slot":"2030-01-15T11:00:00+05:30","confirmed_slot":"2030-01-15T11:00:00+05:30"}}}
```

Common invalidity (unknown type/version, mismatched session, missing causation where required) emits no domain event and returns a boundary error. A conflicting duplicate is quarantined and recorded as `ProtocolViolationObserved` by an internal trusted boundary.

## Taxonomy and reducer contract

Payload fields listed are required unless marked `?`.

| Event | Producer → consumer | Payload | Preconditions / reducer behavior / commands |
|---|---|---|---|
| `SessionStarted` | API → reducer | `mode` | new ID; initializes state |
| `UserInputObserved` | input adapter → reducer | `evidence_id, modality, content_ref` | adds evidence; command `InterpretInput` |
| `TranscriptHypothesisObserved` | audio adapter → reducer | `evidence_id, text, final` | provisional interpretation only |
| `ControlIntentInterpreted` | model/fallback → reducer | `control: ControlIntent` | apply confidence policy; may `RequestClarification` |
| `IntentRevisionProposed` | interpreter → reducer | `intent_delta` | validate goal target; no write dispatch |
| `IntentRevisionCommitted` | reducer policy → reducer | `revision` | activates revision, invalidates fingerprints, schedules eligible work |
| `IntentAuthorizationChanged` | user/policy → reducer | `revision_id, authorization, evidence_id` | consequential dispatch requires `AUTHORIZED` |
| `BranchPredicted` | branch generator → reducer | `branch` | retain top-K within budget |
| `BranchPreparationStarted` | dispatcher → reducer | `branch_id, operation_id` | PREDICTED and eligible read-only operation; set PREPARING |
| `BranchPreparationCompleted` | tool executor → reducer | `branch_id, operation_id, result_evidence_id` | only READ_ONLY; set ready if fingerprint current |
| `BranchPromoted` | reducer policy → reducer | `branch_id, revision_id` | exact fingerprint match/unexpired |
| `BranchInvalidated` | reducer → reducer | `branch_id, reason` | mark invalidated; cancel eligible reads |
| `OperationCreated` | planner → reducer | `operation` | descriptor and bindings valid |
| `OperationPreparationStarted` | dispatcher → reducer | `operation_id` | CREATED; set PREPARING after accepting `PrepareOperation` |
| `OperationPrepared` | executor → reducer | `operation_id, prepared_args_hash, safe_point` | set READY; may command dispatch after revalidation |
| `ToolDispatchRequested` | reducer policy → reducer | `operation_id` | READY and current authorization/fingerprint; set operation DISPATCHED; fact of local request, not remote acceptance or commit; command `DispatchTool` |
| `ToolDispatchAccepted` | executor → reducer | `operation_id, provider_request_id` | DISPATCHED; set operation WAITING and effect IN_FLIGHT |
| `CancellationRequested` | reducer policy → reducer | `operation_id, reason` | set REQUESTED; command per policy |
| `CancellationAcknowledged` | executor/provider → reducer | `operation_id, scope: CancellationAckScope` | only proves stated local/provider acceptance; none of the three scope values proves effect absence |
| `SafePointReached` | executor → reducer | `operation_id, name` | cancel or continue according to current revision/policy |
| `ToolResultObserved` | tool adapter → reducer | `operation_id, provider_request_id, outcome: ToolOutcome, result: object, provider_effect_id?` | provider request must match operation; validate result against descriptor and conditional result schema; dedupe; normalize evidence; update operation; never discard because stale |
| `ToolTimedOut` | executor → reducer | `operation_id, after_dispatch` | write after dispatch → `OUTCOME_UNKNOWN`; schedule verification if supported |
| `WorldEffectObserved` | result interpreter → reducer | `effect: EffectRecord` | append/merge ledger; evaluate divergence and claims |
| `EvidenceRecorded` | adapters/reducer → reducer | `evidence` | insert immutable; conflicting ID is violation |
| `ClaimProposed` | claim engine → reducer | `claim` | evaluate evidence rule |
| `ClaimStateChanged` | claim engine → reducer | `claim_id, from, to, evidence_ids, reason` | transition per machine; evaluate queued speech |
| `SpeechActProposed` | output planner → reducer | `speech_act` | command `ValidateSpeech` |
| `SpeechActApproved` | TRUTHLOCK → reducer | `speech_id, rendered_text, policy_id` | queue output |
| `SpeechActBlocked` | TRUTHLOCK → reducer | `speech_id, reason, max_certainty` | record block; optionally propose safe wording |
| `SpeechQueued` | output dispatcher → reducer | `speech_id` | APPROVED and claim versions still current; set QUEUED |
| `SpeechEmissionStarted` | output adapter → reducer | `speech_id` | mark emitting |
| `SpeechEmissionFinished` | output adapter → reducer | `speech_id, heard` | mark emitted; if later contradicted require correction |
| `SpeechCancellationRequested` | reducer → reducer | `speech_id` | command stop; does not cancel operations |
| `DivergenceDetected` | reconciliation detector → reducer | `case` | store open; command build plan/surface |
| `ReconciliationPlanned` | planner → reducer | `plan` | capability hash and intent revision must match |
| `ReconciliationAuthorized` | user/policy → reducer | `plan_id, evidence_id` | allow run |
| `ReconciliationDenied` | user/policy → reducer | `plan_id, evidence_id, reason` | plan DRAFT and divergence PLANNED; set plan FAILED and divergence ESCALATED/manual-only; dispatch no plan step |
| `ReconciliationStepChanged` | executor → reducer | `plan_id, step_id, state, evidence_id?` | update; failure escalates/retries policy |
| `DivergenceResolved` | verifier → reducer | `divergence_id, evidence_ids` | requires desired/observed equality evidence |
| `FaultActivated` | scenario runner → reducer | `fault_id, operation_match` | test mode only; annotate trace |
| `ProtocolViolationObserved` | trusted boundary → reducer | `boundary, code, digest` | metric + safe error; redact raw secret data |

Every accepted operational event is consumed by the reducer. Derived engines run as reducer policies or commands but can only change state through a returned event. Replay consumes the same events with `dispatch_enabled=false`.

For `appointment.book`, the nested result contract is canonical in `DOMAIN_MODEL.md` and `TOOL_DESCRIPTOR.md`. `outcome=ACKNOWLEDGED` accepts only acknowledgement-shaped results; `SUCCEEDED` requires a final confirmed result; `FAILED` requires a final failure; `UNKNOWN` requires the unknown shape. Outer and nested `provider_request_id` values must match. A schema-valid result for a different center or slot records the authoritative effect but cannot confirm the desired claim.
