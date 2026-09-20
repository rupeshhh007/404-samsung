# Canonical Domain Model

All IDs are opaque strings (UUIDv7 in live mode; stable names in scenarios), timestamps are RFC 3339 UTC plus integer `logical_time`, and serialized enums use uppercase tokens. Records carry `schema_version: 1`.

## Enums

`ControlKind`: `BACKCHANNEL`, `CANCEL_SPEECH`, `CORRECT`, `ADD_GOAL`, `RETRACT_GOAL`, `PAUSE`, `RESUME`, `REFER`, `NEW_TOPIC`, `CLARIFY`.

`IntentMaturity`: `PROVISIONAL`, `COMMITTED`, `SUPERSEDED`; `Authorization`: `NOT_REQUESTED`, `REQUIRED`, `AUTHORIZED`, `DENIED`, `EXPIRED`.

`ActionType`: `READ_ONLY`, `REVERSIBLE`, `IRREVERSIBLE`; `CancellationPolicy`: `IMMEDIATE`, `AT_SAFEPOINT`, `NONCANCELLABLE`; `OperationState`: `CREATED`, `PREPARING`, `READY`, `DISPATCHED`, `WAITING`, `SUCCEEDED`, `FAILED`, `TIMED_OUT`, `CANCELLED`, `SUPERSEDED`; `CancellationState`: `NONE`, `REQUESTED`, `ACKNOWLEDGED`, `REJECTED`, `TOO_LATE`; `EffectState`: `NOT_STARTED`, `IN_FLIGHT`, `COMMITTED`, `FAILED`, `OUTCOME_UNKNOWN`, `COMPENSATED`.

`BranchState`: `PREDICTED`, `PREPARING`, `READY`, `PROMOTED`, `EXPIRED`, `EVICTED`, `INVALIDATED`, `FAILED`; `EvidenceSource`: `USER`, `TOOL`, `FRAME`, `AUDIO`, `SYSTEM`; `ClaimState`: `PROPOSED`, `PENDING`, `CONFIRMED`, `CONTRADICTED`, `UNCERTAIN`, `STALE`, `SUPERSEDED`; `SpeechState`: `PROPOSED`, `APPROVED`, `QUEUED`, `EMITTING`, `EMITTED`, `CANCELLED`, `BLOCKED`, `CORRECTION_REQUIRED`; `DivergenceState`: `OPEN`, `PLANNED`, `RECONCILING`, `RESOLVED`, `ESCALATED`; `PlanState`: `DRAFT`, `AUTHORIZED`, `RUNNING`, `SUCCEEDED`, `FAILED`, `SUPERSEDED`.

`EventSource`: `USER`, `INPUT_ADAPTER`, `MODEL`, `POLICY`, `TOOL`, `OUTPUT_ADAPTER`, `SCENARIO`, `SYSTEM`; `ToolOutcome`: `ACKNOWLEDGED`, `SUCCEEDED`, `FAILED`, `UNKNOWN`; `EvidenceAuthority`: `AUTHORITATIVE`, `NON_AUTHORITATIVE`, `DERIVED`; `PlanStepState`: `PENDING`, `RUNNING`, `SUCCEEDED`, `FAILED`, `SKIPPED`.

`RuntimeMode`: `DEMO`, `LIVE`, `TEST`, `REPLAY`; `EffectClassification`: `NONE`, `EXTERNAL_STATE_CHANGE`, `UNKNOWN`; `CancellationAckScope`: `LOCAL_TASK`, `PROVIDER_REQUEST_ACCEPTED`, `PROVIDER_CANCEL_ACCEPTED`; `SpeechActType`: `PROGRESS`, `CLARIFICATION`, `RESULT`, `FAILURE`, `UNCERTAINTY`, `DIVERGENCE`, `CORRECTION`; `ClaimCertainty`: `PROGRESS`, `ACKNOWLEDGED`, `CONFIRMED`, `UNCERTAIN`; `PlanStepKind`: `VERIFY_OBSERVED`, `COMPENSATE_OBSOLETE`, `VERIFY_COMPENSATION`, `PREPARE_DESIRED`, `COMMIT_DESIRED`, `VERIFY_FINAL`.

`SafePointName`: `BEFORE_PROVIDER_DISPATCH`; `SafePointDecision`: `CONTINUE`, `CANCEL`, `HOLD`, `UNKNOWN`; `BranchMissReason`: `NOT_FOUND`, `NOT_READY`, `EXPIRED`, `FINGERPRINT_MISMATCH`, `CAPABILITY_CHANGED`.

## Entity catalog

| Entity | Required fields | Purpose, validation, lifecycle |
|---|---|---|
| `EventEnvelope` | `event_id: ID, session_id: ID, sequence: int, event_type: string, source: EventSource, occurred_at: datetime, logical_time: int, schema_version: int, payload: object`; optional `correlation_id: ID, causation_id: ID, dedupe_key: string` | Immutable accepted fact. Sequence > 0; logical time ≥ 0; payload validates by event type. |
| `SessionState` | `session_id, last_sequence, mode, paused, intents, active_intent_id, branches, operations, effects, evidence, claims, divergences, plans, speech, metrics` | Reducer-owned aggregate; maps keyed by IDs. `paused` is the reducer-owned reversible runtime pause snapshot and defaults to `false`; it is distinct from fatal session halt metadata. |
| `ControlIntent` | `control_id, kind, confidence, consequential, target_refs, raw_evidence_id`; optional `clarification` | Model proposal; confidence 0..1; reducer applies deterministic policy. |
| `IntentNode` | `intent_id, goal_type, revisions, active_revision_id` | Stable goal identity and revision chain. |
| `IntentRevision` | `revision_id, intent_id, parent_revision_id, values, maturity, authorization, created_by_event_id, dependency_fingerprint` | Immutable revision; one active revision per active goal. |
| `IntentDelta` | `set_fields, unset_fields, add_goals, retract_goals, target_intent_id, confidence` | Validated proposed change; unknown fields rejected by goal schema. |
| `DependencyBinding` | `path: string, value_hash: string, evidence_ids: ID[]` | Exact operation/branch input; path is canonical dotted form; arrays are sorted before canonical JSON SHA-256 hashing. |
| `BranchRecord` | `branch_id, candidate_delta, confidence, state, bindings, fingerprint, expires_at, estimated_cost, operation_ids` | Bounded speculative read plan. |
| `ToolDescriptor` | `tool_name, manifest_version, argument_schema, result_schema, effect_classification, action_type, cancellation_policy, safe_points, timeout_ms, retry_policy, idempotency, compensation, confirmation_semantics` | Normalized trusted registration; unknown capability uses conservative defaults. |
| `OperationRecord` | `operation_id: ID, tool_name: string, args: object, intent_revision_id: ID, bindings: DependencyBinding[], fingerprint: string, action_type: ActionType, cancellation_policy: CancellationPolicy, state: OperationState, cancellation_state: CancellationState, effect_state: EffectState, speculative: bool, logical_action_id: string, idempotency_key: string`; optional `descriptor_capability_hash: string, provider_request_id: string, error: ErrorRecord` | Tracks local execution separately from world effects. `descriptor_capability_hash` is the exact `ToolRegistry` capability hash of the trusted descriptor used at creation; `None` means creation-time capability provenance is unavailable and later dispatch checks must fail closed. `speculative=true` requires READ_ONLY and effect classification NONE. |
| `EffectRecord` | `effect_id: ID, logical_action_id: string, operation_id: ID, provider_effect_id: string, effect_type: string, subject: object, parameters: object, state: EffectState, observed_at: datetime, authority: EvidenceAuthority, evidence_ids: ID[]`; optional `supersedes_effect_id: ID` | Append-only world ledger; COMMITTED/COMPENSATED effects require AUTHORITATIVE evidence; duplicate provider IDs merge provenance, not effects. |
| `EvidenceRecord` | `evidence_id, source, kind, captured_at, content_ref, content_hash, authority, provenance`; optional `expires_at, derived_from` | Immutable source or interpretation; derived evidence never replaces source. |
| `ClaimRecord` | `claim_id, predicate, subject, object, state, required_evidence_rule, supporting_evidence_ids, intent_revision_id, updated_by_event_id` | Claim graph node; state recalculated as evidence changes. |
| `SpeechAct` | `speech_id, act_type: SpeechActType, template_id, slots, claim_ids, requested_certainty: ClaimCertainty, state, created_by_event_id`; optional `supersedes_speech_id` | Structured output; consequential acts require claim IDs and controlled templates. |
| `DivergenceCase` | `divergence_id, desired_fingerprint, observed_effect_ids, kind, state, detected_by_event_id, authorization_required` | Explicit intent/world mismatch. |
| `ReconciliationPlan` | `plan_id: ID, divergence_id: ID, based_on_intent_revision_id: ID, steps: PlanStep[], state: PlanState, provider_capability_hash: string`; optional `authorized_by_evidence_id: ID` | Ordered verify/compensate/commit/verify steps; every step has `step_id, kind: PlanStepKind, tool_name, arguments, state: PlanStepState, idempotency_key?, requires_authorization`; stale intent supersedes plan. |
| `ScenarioDefinition` | `scenario_id, initial_state, tools, faults, steps, expect` | Deterministic test specification. `steps` is the ordered union of timed input, absolute-time advance, and checkpoint assertion records. |
| `MetricsSnapshot` | `session_id, through_sequence, counters, durations_ms, gauges` | Derived projection; never authoritative domain input. |

## Canonical example

```json
{
  "operation_id":"op-book-11","tool_name":"appointment.book","args":{"center_id":"ctr-01","requested_slot":"2030-01-15T11:00:00+05:30","idempotency_key":"sess-demo:booking:ctr-01:slot-11:v1"},
  "intent_revision_id":"ir-1","bindings":[{"path":"appointment.slot","value_hash":"sha256:11","evidence_ids":["ev-user-7"]}],
  "fingerprint":"sha256:deps-11","action_type":"REVERSIBLE","cancellation_policy":"AT_SAFEPOINT","state":"DISPATCHED",
  "cancellation_state":"REQUESTED","effect_state":"NOT_STARTED","speculative":false,"logical_action_id":"booking:ctr-01:slot-11",
  "idempotency_key":"sess-demo:booking:ctr-01:slot-11:v1","schema_version":1
}
```

Invalid: a speculative operation with `action_type: REVERSIBLE`, a `CONFIRMED` claim with no satisfying evidence, or an event sequence of zero. Schema evolution is additive within version 1; breaking changes increment the owning schema version and follow contract policy.

## Canonical simulated booking types

These types belong to the local demo adapter and do not claim an official Samsung schema.

| Type | Required fields | Conditional validation |
|---|---|---|
| `BookingRequest` | `center_id: string`, `requested_slot: RFC3339 datetime`, `idempotency_key: string` | Center and slot must match the authorized intent fingerprint; unknown fields are rejected. |
| `BookingResult` acknowledgement | `phase: ACKNOWLEDGEMENT`, `status: REQUEST_RECEIVED`, `provider_request_id: string`, `center_id`, `requested_slot` | Must not establish a committed effect; booking ID may be absent. |
| `BookingResult` confirmed | `phase: FINAL`, `status: BOOKING_CONFIRMED`, `provider_request_id`, `provider_booking_id`, `center_id`, `requested_slot`, `confirmed_slot` | IDs must be nonempty. Confirmed center and slot must equal the authorized request before the desired-booking claim can confirm. A mismatched authoritative result is still a world effect and creates divergence. |
| `BookingResult` failed | `phase: FINAL`, `status: BOOKING_FAILED`, `provider_request_id`, `error: {code,message,retryable}` | No committed effect is inferred. Retry follows descriptor/idempotency policy. |
| `BookingResult` unknown | `phase: FINAL`, `status: OUTCOME_UNKNOWN`, `provider_request_id` | Effect becomes OUTCOME_UNKNOWN and verification is required; blind write retry is forbidden. |
| `CancellationRequest` | `provider_booking_id`, `center_id`, `idempotency_key` | Targets an observed committed effect and requires plan/user authorization. |
| `CancellationResult` | `status: CANCELLATION_CONFIRMED`, `provider_request_id`, `provider_booking_id`, `center_id`, `cancelled_at` | Only an authoritative matching result or verification permits COMMITTED→COMPENSATED. Failure/unknown variants follow booking failure/unknown rules. |
