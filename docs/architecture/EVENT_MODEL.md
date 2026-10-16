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
| `VoiceTranscriptionTimeoutObserved` | voice transport → reducer | `speech_duration_ms` | advances the journal; short VAD blips are ignored, sustained speech with no final transcript requests a controlled repeat clarification |
| `ControlIntentInterpreted` | model/fallback → reducer | `control: ControlIntent` | apply confidence policy; may `RequestClarification` |
| `IntentRevisionProposed` | interpreter → reducer | `intent_delta` | validate goal target; no write dispatch |
| `IntentRevisionCommitted` | reducer policy → reducer | `revision` | validates lineage (root parent must be None, child parent must match active revision), initial authorization must be NOT_REQUESTED, and maturity must be PROVISIONAL or COMMITTED; stores revision as COMMITTED, transitions prior active revision in `state.revisions` to SUPERSEDED, invalidates fingerprints, schedules eligible work |
| `IntentAuthorizationChanged` | user/policy → reducer | `revision_id, authorization, evidence_id` | legal transitions: `NOT_REQUESTED→REQUIRED|AUTHORIZED|DENIED`, `REQUIRED→AUTHORIZED|DENIED`, `AUTHORIZED→EXPIRED`; consequential dispatch requires `AUTHORIZED`; rejects transitions on `SUPERSEDED` revisions |
| `BranchPredicted` | branch generator → reducer | `branch` | retain top-K within budget |
| `BranchPreparationStarted` | dispatcher → reducer | `branch_id, operation_id` | PREDICTED and eligible read-only operation; set PREPARING |
| `BranchPreparationCompleted` | tool executor → reducer | `branch_id, operation_id, result_evidence_id` | only READ_ONLY; set ready if fingerprint current |
| `BranchPromoted` | reducer policy → reducer | `branch_id, revision_id` | exact fingerprint match/unexpired |
| `BranchInvalidated` | reducer → reducer | `branch_id, reason` | mark invalidated; cancel eligible reads |
| `OperationCreated` | planner → reducer | `operation` | insert `CREATED`; reject duplicate ID, invalid initial correlation/dispatch state, or non-empty `cancellation_ack_scopes` |
| `OperationPreparationStarted` | dispatcher → reducer | `operation_id` | CREATED; set PREPARING after accepting `PrepareOperation` |
| `OperationPrepared` | executor → reducer | `operation_id, prepared_args_hash, safe_point` | set READY; may command dispatch after revalidation |
| `ToolDispatchRequested` | reducer policy → reducer | `operation_id, validated_through_sequence?` | evaluates sequence pin before operation state: missing pin fails closed with `MISSING_SAFEPOINT_PIN`; stale pin (`pin < last_sequence`) is a normal race that advances sequence/metrics, publishes projection in live mode, emits zero commands in replay, and preserves the current operation in whatever state it holds with no violation and no token; future pin (`pin > last_sequence`) fails closed with `FUTURE_SAFEPOINT_PIN`; matching pin (`pin == last_sequence`) evaluates READY, authorization, and session guards before transitioning operation to DISPATCHED, recording immutable dispatch token (`dispatch_requested_event_id`), and commanding `DispatchTool` |
| `ToolDispatchAccepted` | executor → reducer | `operation_id, provider_request_id` | DISPATCHED; set operation WAITING and effect IN_FLIGHT. If received late after earlier result/timeout, accepts correlation without reactivating terminal/cancelled operation or downgrading effect state; mismatching ID rejected |
| `CancellationRequested` | reducer policy → reducer | `operation_id, reason` | set REQUESTED; command per policy |
| `CancellationAcknowledged` | executor/provider → reducer | `operation_id, scope: CancellationAckScope` | accepts when REQUESTED or ACKNOWLEDGED; appends unique scope to `cancellation_ack_scopes`; transitions active non-terminal operation to CANCELLED; only proves stated local/provider acceptance; none of the three scope values proves effect absence |
| `CancellationRejected` | executor/provider → reducer | `operation_id, reason` | accepts when REQUESTED or ACKNOWLEDGED; fails closed with INVALID_CANCELLATION_TRANSITION if `PROVIDER_CANCEL_ACCEPTED` is already recorded in `cancellation_ack_scopes`; otherwise sets cancellation_state to REJECTED; preserves operation/effect state and provider_request_id; does not imply provider failure or effect absence |
| `CancellationTooLate` | executor/provider → reducer | `operation_id, reason` | accepts when REQUESTED or ACKNOWLEDGED; fails closed with INVALID_CANCELLATION_TRANSITION if `PROVIDER_CANCEL_ACCEPTED` is already recorded in `cancellation_ack_scopes`; otherwise sets cancellation_state to TOO_LATE; preserves operation/effect state and provider_request_id; does not imply effect commit; subsequent result/timeout still determines reality |
| `SafePointReached` | executor → reducer | `operation_id, name` | cancel or continue according to current revision/policy |
| `ToolResultObserved` | tool adapter → reducer | `operation_id, provider_request_id, outcome: ToolOutcome, result: object, provider_effect_id?` | provider request must match operation or establish previously missing ID if dispatch token is present; validate result against descriptor and conditional result schema; dedupe; normalize evidence; update operation; never discard because stale; late result on CANCELLED/SUPERSEDED updates effect state without reactivating operation |
| `ToolTimedOut` | executor → reducer | `operation_id, after_dispatch` | `after_dispatch=true` requires the operation's accepted dispatch token. For DISPATCHED/WAITING, set the operation to TIMED_OUT; for previously dispatched TIMED_OUT/CANCELLED/SUPERSEDED operations, preserve lifecycle state. Set unresolved effects (`NOT_STARTED`, `IN_FLIGHT`, `OUTCOME_UNKNOWN`) to `OUTCOME_UNKNOWN` and schedule verification; preserve authoritative `COMMITTED`, `FAILED`, or `COMPENSATED` effect facts without verification. `after_dispatch=false` retains the ordinary DISPATCHED/WAITING-only timeout transition. |
| `WorldEffectObserved` | result interpreter → reducer | `effect: EffectRecord` | require an existing matching operation/logical action; insert a detached immutable observation by `effect_id`; identical IDs are idempotent and conflicting IDs are protocol violations. Distinct IDs for one physical effect or distinct physical effects for one logical action remain in the ledger; authoritative conflict schedules targeted `VerifyOutcome`. A confirmed late observation can advance the operation effect dimension without reactivating its lifecycle. A `COMPENSATED` observation must link to an existing committed observation of the same physical effect. Current-world certainty is derived from all observations, never from arrival order. |
| `EvidenceRecorded` | adapters/reducer → reducer | `evidence` | insert immutable; conflicting ID is violation |
| `ClaimProposed` | claim engine → reducer | `claim` | evaluate evidence rule |
| `ClaimStateChanged` | claim engine → reducer | `claim_id, from, to, evidence_ids, reason` | transition per machine; advances updated_by_event_id; evaluates dependent speech acts |
| `SpeechActProposed` | output planner → reducer | `speech_act` | command `ValidateSpeech` |
| `SpeechActApproved` | TRUTHLOCK → reducer | `speech_id, rendered_text, policy_id, through_sequence?, claim_versions` | validate sequence pin & exact claim versions; stale retries `ValidateSpeech`; valid approval sets APPROVED, persists proof, commands `QueueOutput` |
| `SpeechActBlocked` | TRUTHLOCK → reducer | `speech_id, reason, max_certainty` | record block; optionally propose safe wording |
| `SpeechQueued` | output dispatcher → reducer | `speech_id` | check claim versions current against state; if stale set CANCELLED; if current set QUEUED, command `EmitOutput` |
| `SpeechEmissionStarted` | output adapter → reducer | `speech_id` | mark emitting |
| `SpeechEmissionFinished` | output adapter → reducer | `speech_id, heard` | persist heard; if heard=false and cancellation_pending set CANCELLED; if heard=true and correction_pending set CORRECTION_REQUIRED and command `RequestSpeechCorrection`; else set EMITTED |
| `SpeechEmissionFailed` | output adapter → reducer | `speech_id, error_code, heard, retryable?` | adapter failure fact; if heard=false set CANCELLED; if heard=true and correction_pending set CORRECTION_REQUIRED; else if heard=true mark EMITTED; no auto retry |
| `SpeechCancellationRequested` | reducer → reducer | `speech_id` | command CancelSpeech; if QUEUED or EMITTING sets cancellation_pending=True awaiting adapter terminal fact; does not cancel operations |
| `DivergenceDetected` | reconciliation detector → reducer | `case` | store open; command build plan/surface |
| `ReconciliationPlanned` | planner → reducer | `plan` | capability hash and intent revision must match |
| `ReconciliationAuthorized` | user/policy → reducer | `plan_id, evidence_id` | allow run |
| `ReconciliationDenied` | user/policy → reducer | `plan_id, evidence_id, reason` | plan DRAFT and divergence PLANNED; set plan FAILED and divergence ESCALATED/manual-only; dispatch no plan step |
| `ReconciliationStepChanged` | executor → reducer | `plan_id, step_id, state, evidence_id?` | update; failure escalates/retries policy |
| `DivergenceResolved` | verifier → reducer | `divergence_id, evidence_ids` | requires desired/observed equality evidence |
| `FaultActivated` | scenario runner → reducer | `fault_id, operation_match` | test mode only; annotate trace |
| `ProtocolViolationObserved` | trusted boundary → reducer | `boundary, code, digest` | metric + safe error; redact raw secret data |

Every accepted operational event is consumed by the reducer. Derived engines run as reducer policies or commands but can only change state through a returned event. Replay consumes the same events with `dispatch_enabled=false`.

`VerifyOutcome` always carries `operation_id` and may additionally carry `provider_effect_id` for one physical effect. Duplicate physical effects under one logical action require separate targeted commands for each provider effect ID. Omission retains the operation-timeout meaning. A verifier must inspect the authoritative ledger snapshot and must not infer absence from timeout or cancellation acknowledgement.

For `appointment.book`, the nested result contract is canonical in `DOMAIN_MODEL.md` and `TOOL_DESCRIPTOR.md`. `outcome=ACKNOWLEDGED` accepts only acknowledgement-shaped results; `SUCCEEDED` requires a final confirmed result; `FAILED` requires a final failure; `UNKNOWN` requires the unknown shape. Outer and nested `provider_request_id` values must match. A schema-valid result for a different center or slot records the authoritative effect but cannot confirm the desired claim.
