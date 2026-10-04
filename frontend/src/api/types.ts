export type JsonPrimitive = string | number | boolean | null;

export type JsonValue =
  | JsonPrimitive
  | { readonly [key: string]: JsonValue }
  | readonly JsonValue[];

export type JsonObject = { readonly [key: string]: JsonValue };

export type RuntimeMode = 'DEMO' | 'LIVE' | 'TEST';
export type IntentMaturity = 'PROVISIONAL' | 'COMMITTED' | 'SUPERSEDED';
export type Authorization =
  | 'NOT_REQUESTED'
  | 'REQUIRED'
  | 'AUTHORIZED'
  | 'DENIED'
  | 'EXPIRED';
export type ActionType = 'READ_ONLY' | 'REVERSIBLE' | 'IRREVERSIBLE';
export type CancellationPolicy = 'IMMEDIATE' | 'AT_SAFEPOINT' | 'NONCANCELLABLE';
export type OperationState =
  | 'CREATED'
  | 'PREPARING'
  | 'READY'
  | 'DISPATCHED'
  | 'WAITING'
  | 'SUCCEEDED'
  | 'FAILED'
  | 'TIMED_OUT'
  | 'CANCELLED'
  | 'SUPERSEDED';
export type CancellationState =
  | 'NONE'
  | 'REQUESTED'
  | 'ACKNOWLEDGED'
  | 'REJECTED'
  | 'TOO_LATE';
export type CancellationAckScope =
  | 'LOCAL_TASK'
  | 'PROVIDER_REQUEST_ACCEPTED'
  | 'PROVIDER_CANCEL_ACCEPTED';
export type EffectState =
  | 'NOT_STARTED'
  | 'IN_FLIGHT'
  | 'COMMITTED'
  | 'FAILED'
  | 'OUTCOME_UNKNOWN'
  | 'COMPENSATED';
export type EvidenceSource = 'USER' | 'TOOL' | 'FRAME' | 'AUDIO' | 'SYSTEM';
export type EvidenceAuthority = 'AUTHORITATIVE' | 'NON_AUTHORITATIVE' | 'DERIVED';
export type ClaimState =
  | 'PROPOSED'
  | 'PENDING'
  | 'CONFIRMED'
  | 'CONTRADICTED'
  | 'UNCERTAIN'
  | 'STALE'
  | 'SUPERSEDED';
export type SpeechState =
  | 'PROPOSED'
  | 'APPROVED'
  | 'QUEUED'
  | 'EMITTING'
  | 'EMITTED'
  | 'CANCELLED'
  | 'BLOCKED'
  | 'CORRECTION_REQUIRED';
export type SpeechActType =
  | 'PROGRESS'
  | 'CLARIFICATION'
  | 'RESULT'
  | 'FAILURE'
  | 'UNCERTAINTY'
  | 'DIVERGENCE'
  | 'CORRECTION';
export type ClaimCertainty = 'PROGRESS' | 'ACKNOWLEDGED' | 'CONFIRMED' | 'UNCERTAIN';
export type DivergenceState = 'OPEN' | 'PLANNED' | 'RECONCILING' | 'RESOLVED' | 'ESCALATED';
export type PlanState = 'DRAFT' | 'AUTHORIZED' | 'RUNNING' | 'SUCCEEDED' | 'FAILED' | 'SUPERSEDED';
export type PlanStepState = 'PENDING' | 'RUNNING' | 'SUCCEEDED' | 'FAILED' | 'SKIPPED';
export type PlanStepKind =
  | 'VERIFY_OBSERVED'
  | 'COMPENSATE_OBSOLETE'
  | 'VERIFY_COMPENSATION'
  | 'PREPARE_DESIRED'
  | 'COMMIT_DESIRED'
  | 'VERIFY_FINAL';

export interface DependencyBinding {
  readonly path: string;
  readonly value_hash: string;
  readonly evidence_ids: readonly string[];
}

export interface IntentRevision {
  readonly revision_id: string;
  readonly intent_id: string;
  readonly parent_revision_id: string | null;
  readonly values: JsonObject;
  readonly maturity: IntentMaturity;
  readonly authorization: Authorization;
  readonly created_by_event_id: string;
  readonly dependency_fingerprint: string;
}

export interface IntentProjection {
  readonly intent_id: string;
  readonly goal_type: string;
  readonly revisions: readonly string[];
  readonly active_revision_id: string | null;
  readonly active_revision: IntentRevision | null;
}

export interface ErrorRecord {
  readonly code: string;
  readonly message: string;
  readonly retryable: boolean;
}

export interface OperationProjection {
  readonly operation_id: string;
  readonly tool_name: string;
  readonly args: JsonObject;
  readonly intent_revision_id: string;
  readonly bindings: readonly DependencyBinding[];
  readonly fingerprint: string;
  readonly action_type: ActionType;
  readonly cancellation_policy: CancellationPolicy;
  readonly state: OperationState;
  readonly cancellation_state: CancellationState;
  readonly cancellation_ack_scopes: readonly CancellationAckScope[];
  readonly effect_state: EffectState;
  readonly speculative: boolean;
  readonly logical_action_id: string;
  readonly idempotency_key: string;
  readonly descriptor_capability_hash: string | null;
  readonly schema_version: 1;
  readonly provider_request_id: string | null;
  readonly dispatch_requested_event_id: string | null;
  readonly error: ErrorRecord | null;
}

export interface EffectProjection {
  readonly effect_id: string;
  readonly logical_action_id: string;
  readonly operation_id: string;
  readonly provider_effect_id: string;
  readonly effect_type: string;
  readonly subject: JsonObject;
  readonly parameters: JsonObject;
  readonly state: EffectState;
  readonly observed_at: string;
  readonly authority: EvidenceAuthority;
  readonly evidence_ids: readonly string[];
  readonly schema_version: 1;
  readonly supersedes_effect_id: string | null;
}

export interface EvidenceProjection {
  readonly evidence_id: string;
  readonly source: EvidenceSource;
  readonly kind: string;
  readonly captured_at: string;
  readonly content_ref: string;
  readonly content_hash: string;
  readonly authority: EvidenceAuthority;
  readonly provenance: JsonObject;
  readonly schema_version: 1;
  readonly expires_at: string | null;
  readonly derived_from: readonly string[] | null;
}

export interface ClaimProjection {
  readonly claim_id: string;
  readonly predicate: string;
  readonly subject: JsonObject;
  readonly object: JsonObject;
  readonly state: ClaimState;
  readonly required_evidence_rule: string;
  readonly supporting_evidence_ids: readonly string[];
  readonly intent_revision_id: string;
  readonly updated_by_event_id: string;
  readonly schema_version: 1;
}

export interface SpeechProjection {
  readonly speech_id: string;
  readonly act_type: SpeechActType;
  readonly template_id: string;
  readonly slots: JsonObject;
  readonly claim_ids: readonly string[];
  readonly requested_certainty: ClaimCertainty;
  readonly state: SpeechState;
  readonly created_by_event_id: string;
  readonly schema_version: 1;
  readonly supersedes_speech_id: string | null;
  readonly rendered_text: string | null;
  readonly approved_policy_id: string | null;
  readonly approved_through_sequence: number | null;
  readonly approved_claim_versions: Readonly<Record<string, string>>;
  readonly heard: boolean | null;
  readonly cancellation_pending: boolean;
  readonly correction_pending: boolean;
}

export interface DivergenceProjection {
  readonly divergence_id: string;
  readonly desired_fingerprint: string;
  readonly observed_effect_ids: readonly string[];
  readonly kind: string;
  readonly state: DivergenceState;
  readonly detected_by_event_id: string;
  readonly authorization_required: boolean;
  readonly schema_version: 1;
}

export interface PlanStepProjection {
  readonly step_id: string;
  readonly kind: PlanStepKind;
  readonly tool_name: string;
  readonly arguments: JsonObject;
  readonly state: PlanStepState;
  readonly requires_authorization: boolean;
  readonly idempotency_key: string | null;
}

export interface ReconciliationPlanProjection {
  readonly plan_id: string;
  readonly divergence_id: string;
  readonly based_on_intent_revision_id: string;
  readonly steps: readonly PlanStepProjection[];
  readonly state: PlanState;
  readonly provider_capability_hash: string;
  readonly schema_version: 1;
  readonly authorized_by_evidence_id: string | null;
}

export interface MetricsProjection {
  readonly session_id: string;
  readonly through_sequence: number;
  readonly counters: Readonly<Record<string, number>>;
  readonly durations_ms: Readonly<Record<string, number>>;
  readonly gauges: Readonly<Record<string, number>>;
}

export interface SessionProjection {
  readonly intent: IntentProjection | null;
  readonly operations: readonly OperationProjection[];
  readonly effects: readonly EffectProjection[];
  readonly evidence: readonly EvidenceProjection[];
  readonly claims: readonly ClaimProjection[];
  readonly divergences: readonly DivergenceProjection[];
  readonly plans: readonly ReconciliationPlanProjection[];
  readonly speech: readonly SpeechProjection[];
  readonly metrics: MetricsProjection;
}

export interface ProjectionChanged {
  readonly intent?: IntentProjection | null;
  readonly operations?: readonly OperationProjection[];
  readonly effects?: readonly EffectProjection[];
  readonly evidence?: readonly EvidenceProjection[];
  readonly claims?: readonly ClaimProjection[];
  readonly divergences?: readonly DivergenceProjection[];
  readonly plans?: readonly ReconciliationPlanProjection[];
  readonly speech?: readonly SpeechProjection[];
  readonly metrics?: MetricsProjection;
}

export interface ProjectionRemoved {
  readonly intent?: readonly string[];
  readonly operations?: readonly string[];
  readonly effects?: readonly string[];
  readonly evidence?: readonly string[];
  readonly claims?: readonly string[];
  readonly divergences?: readonly string[];
  readonly plans?: readonly string[];
  readonly speech?: readonly string[];
}

export interface ProjectionDelta {
  readonly through_sequence: number;
  readonly changed: ProjectionChanged;
  readonly removed: ProjectionRemoved;
}

export interface SnapshotMessage {
  readonly type: 'snapshot';
  readonly schema_version: 1;
  readonly session_id: string;
  readonly through_sequence: number;
  readonly projection: SessionProjection;
}

export interface ProjectionEventMessage {
  readonly type: 'event';
  readonly schema_version: 1;
  readonly session_id: string;
  readonly sequence: number;
  readonly event_type: string;
  readonly projection_delta: ProjectionDelta;
  readonly trace: { readonly correlation_id: string };
}

export interface ResyncRequiredMessage {
  readonly type: 'resync_required';
  readonly reason: 'GAP_OR_EXPIRED';
  readonly snapshot_url: string;
}

export interface WebSocketErrorMessage {
  readonly type: 'error';
  readonly code: string;
  readonly recoverable: boolean;
}

export interface SessionClosingMessage {
  readonly type: 'closing';
  readonly schema_version: 1;
  readonly session_id: string;
  readonly through_sequence: number;
  readonly reason: string;
}

export interface ShutdownClosingMessage {
  readonly type: 'closing';
  readonly reason: 'SHUTDOWN';
  readonly through_sequence: number;
}

export type WebSocketServerMessage =
  | SnapshotMessage
  | ProjectionEventMessage
  | ResyncRequiredMessage
  | WebSocketErrorMessage
  | SessionClosingMessage
  | ShutdownClosingMessage;

export type WebSocketClientMessage =
  | { readonly type: 'ack'; readonly through_sequence: number }
  | { readonly type: 'ping'; readonly nonce: string };

export interface SessionCreateRequest {
  readonly mode: RuntimeMode;
  readonly client_request_id: string;
}

export type InputRequest =
  | { readonly modality: 'TEXT'; readonly content: string; readonly client_request_id: string }
  | {
      readonly modality: 'FRAME_REF' | 'AUDIO_REF';
      readonly content_ref: string;
      readonly client_request_id: string;
    };

export type AuthorizationRequest =
  | {
      readonly revision_id: string;
      readonly decision: 'AUTHORIZE' | 'DENY';
      readonly client_request_id: string;
    }
  | {
      readonly plan_id: string;
      readonly decision: 'AUTHORIZE' | 'DENY';
      readonly client_request_id: string;
    };

export interface SpeechCancelRequest {
  readonly client_request_id: string;
}

export interface FaultRequest {
  readonly fault_id: string;
  readonly enabled: boolean;
}

export interface ResetRequest {
  readonly fixture_id: 'samsung-demo-v1';
  readonly client_request_id: string;
}

export interface SessionCreateResponse {
  readonly session_id: string;
  readonly last_sequence: number;
  readonly ws_url: string;
}

export interface SessionSnapshotResponse {
  readonly session_id: string;
  readonly through_sequence: number;
  readonly projection: SessionProjection;
}

export interface AcceptanceResponse {
  readonly event_id: string;
  readonly sequence: number;
}

export interface ResetResponse {
  readonly session_id: string;
  readonly last_sequence: number;
}

export interface EventPageResponse {
  readonly events: readonly ProjectionEventMessage[];
  readonly through_sequence: number;
  readonly has_more: boolean;
}

export interface HealthResponse {
  readonly status: string;
  readonly mode: RuntimeMode;
}

export type ConnectionStatus =
  | 'DISCONNECTED'
  | 'CONNECTING'
  | 'CONNECTED'
  | 'RECONNECTING'
  | 'ERROR';

export interface FrontendError {
  readonly kind: 'HTTP' | 'PROTOCOL' | 'CONNECTION' | 'RESYNC';
  readonly message: string;
  readonly recoverable: boolean;
  readonly status: number | null;
}
