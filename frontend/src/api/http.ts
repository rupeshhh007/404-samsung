import type {
  AcceptanceResponse,
  AuthorizationRequest,
  EventPageResponse,
  FaultRequest,
  HealthResponse,
  InputRequest,
  ProjectionEventMessage,
  ResetRequest,
  ResetResponse,
  SessionCreateRequest,
  SessionCreateResponse,
  SessionProjection,
  SessionSnapshotResponse,
  SpeechCancelRequest,
} from './types';

type FetchLike = (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>;

export interface HttpClientOptions {
  readonly baseUrl?: string;
  readonly fetch?: FetchLike;
}

export class HttpApplicationError extends Error {
  readonly status: number;
  readonly method: string;
  readonly url: string;
  readonly body: unknown;

  constructor(
    message: string,
    options: { readonly status: number; readonly method: string; readonly url: string; readonly body: unknown },
  ) {
    super(message);
    this.name = 'HttpApplicationError';
    this.status = options.status;
    this.method = options.method;
    this.url = options.url;
    this.body = options.body;
  }
}

export class HttpProtocolError extends Error {
  readonly method: string;
  readonly url: string;
  readonly body: unknown;

  constructor(
    message: string,
    options: { readonly method: string; readonly url: string; readonly body: unknown },
  ) {
    super(message);
    this.name = 'HttpProtocolError';
    this.method = options.method;
    this.url = options.url;
    this.body = options.body;
  }
}

const viteEnvironment = (
  import.meta as ImportMeta & { readonly env?: Readonly<Record<string, string | undefined>> }
).env;

export const DEFAULT_API_BASE_URL =
  viteEnvironment?.VITE_INTERLOCK_API_URL?.trim() || '/api/v1';

function normalizeBaseUrl(baseUrl: string): string {
  const normalized = baseUrl.trim().replace(/\/+$/, '');
  if (!normalized) throw new TypeError('HTTP base URL must not be empty.');
  return normalized;
}

function resolveUrl(baseUrl: string, path: string): string {
  if (/^https?:\/\//i.test(path)) return path;
  if (path.startsWith('/')) {
    if (/^https?:\/\//i.test(baseUrl)) return new URL(path, baseUrl).toString();
    return path;
  }
  return `${baseUrl}/${path.replace(/^\/+/, '')}`;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function isNonNegativeInteger(value: unknown): value is number {
  return Number.isInteger(value) && Number(value) >= 0;
}

function isPositiveInteger(value: unknown): value is number {
  return Number.isInteger(value) && Number(value) >= 1;
}

function isString(value: unknown): value is string {
  return typeof value === 'string';
}

function isBoolean(value: unknown): value is boolean {
  return typeof value === 'boolean';
}

function isNumber(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value);
}

function isNullableString(value: unknown): value is string | null {
  return value === null || isString(value);
}

function isStringArray(value: unknown): value is readonly string[] {
  return Array.isArray(value) && value.every(isString);
}

function isStringRecord(value: unknown): value is Readonly<Record<string, string>> {
  return isRecord(value) && Object.values(value).every(isString);
}

function isNumberRecord(value: unknown): value is Readonly<Record<string, number>> {
  return isRecord(value) && Object.values(value).every(isNumber);
}

function isJsonValue(value: unknown): boolean {
  if (value === null || isString(value) || isNumber(value) || isBoolean(value)) return true;
  if (Array.isArray(value)) return value.every(isJsonValue);
  return isRecord(value) && Object.values(value).every(isJsonValue);
}

function isJsonObject(value: unknown): boolean {
  return isRecord(value) && Object.values(value).every(isJsonValue);
}

function hasExactKeys(record: Record<string, unknown>, keys: readonly string[]): boolean {
  return Object.keys(record).length === keys.length && keys.every((key) => key in record);
}

function isOneOf(value: unknown, values: readonly string[]): value is string {
  return isString(value) && values.includes(value);
}

function isDependencyBinding(value: unknown): boolean {
  return (
    isRecord(value) &&
    hasExactKeys(value, ['path', 'value_hash', 'evidence_ids']) &&
    isString(value.path) &&
    isString(value.value_hash) &&
    isStringArray(value.evidence_ids)
  );
}

function isIntentRevision(value: unknown): boolean {
  return (
    isRecord(value) &&
    hasExactKeys(value, [
      'revision_id',
      'intent_id',
      'parent_revision_id',
      'values',
      'maturity',
      'authorization',
      'created_by_event_id',
      'dependency_fingerprint',
    ]) &&
    isString(value.revision_id) &&
    isString(value.intent_id) &&
    isNullableString(value.parent_revision_id) &&
    isJsonObject(value.values) &&
    isOneOf(value.maturity, ['PROVISIONAL', 'COMMITTED', 'SUPERSEDED']) &&
    isOneOf(value.authorization, [
      'NOT_REQUESTED',
      'REQUIRED',
      'AUTHORIZED',
      'DENIED',
      'EXPIRED',
    ]) &&
    isString(value.created_by_event_id) &&
    isString(value.dependency_fingerprint)
  );
}

function isIntentProjection(value: unknown): boolean {
  return (
    isRecord(value) &&
    hasExactKeys(value, [
      'intent_id',
      'goal_type',
      'revisions',
      'active_revision_id',
      'active_revision',
    ]) &&
    isString(value.intent_id) &&
    isString(value.goal_type) &&
    isStringArray(value.revisions) &&
    isNullableString(value.active_revision_id) &&
    (value.active_revision === null || isIntentRevision(value.active_revision))
  );
}

function isErrorRecord(value: unknown): boolean {
  return (
    isRecord(value) &&
    hasExactKeys(value, ['code', 'message', 'retryable']) &&
    isString(value.code) &&
    isString(value.message) &&
    isBoolean(value.retryable)
  );
}

function isOperation(value: unknown): boolean {
  return (
    isRecord(value) &&
    hasExactKeys(value, [
      'operation_id',
      'tool_name',
      'args',
      'intent_revision_id',
      'bindings',
      'fingerprint',
      'action_type',
      'cancellation_policy',
      'state',
      'cancellation_state',
      'cancellation_ack_scopes',
      'effect_state',
      'speculative',
      'logical_action_id',
      'idempotency_key',
      'descriptor_capability_hash',
      'schema_version',
      'provider_request_id',
      'dispatch_requested_event_id',
      'error',
    ]) &&
    isString(value.operation_id) &&
    isString(value.tool_name) &&
    isJsonObject(value.args) &&
    isString(value.intent_revision_id) &&
    Array.isArray(value.bindings) &&
    value.bindings.every(isDependencyBinding) &&
    isString(value.fingerprint) &&
    isOneOf(value.action_type, ['READ_ONLY', 'REVERSIBLE', 'IRREVERSIBLE']) &&
    isOneOf(value.cancellation_policy, ['IMMEDIATE', 'AT_SAFEPOINT', 'NONCANCELLABLE']) &&
    isOneOf(value.state, [
      'CREATED',
      'PREPARING',
      'READY',
      'DISPATCHED',
      'WAITING',
      'SUCCEEDED',
      'FAILED',
      'TIMED_OUT',
      'CANCELLED',
      'SUPERSEDED',
    ]) &&
    isOneOf(value.cancellation_state, [
      'NONE',
      'REQUESTED',
      'ACKNOWLEDGED',
      'REJECTED',
      'TOO_LATE',
    ]) &&
    Array.isArray(value.cancellation_ack_scopes) &&
    value.cancellation_ack_scopes.every((scope) =>
      isOneOf(scope, [
        'LOCAL_TASK',
        'PROVIDER_REQUEST_ACCEPTED',
        'PROVIDER_CANCEL_ACCEPTED',
      ]),
    ) &&
    isOneOf(value.effect_state, [
      'NOT_STARTED',
      'IN_FLIGHT',
      'COMMITTED',
      'FAILED',
      'OUTCOME_UNKNOWN',
      'COMPENSATED',
    ]) &&
    isBoolean(value.speculative) &&
    isString(value.logical_action_id) &&
    isString(value.idempotency_key) &&
    isNullableString(value.descriptor_capability_hash) &&
    value.schema_version === 1 &&
    isNullableString(value.provider_request_id) &&
    isNullableString(value.dispatch_requested_event_id) &&
    (value.error === null || isErrorRecord(value.error))
  );
}

function isEffect(value: unknown): boolean {
  return (
    isRecord(value) &&
    hasExactKeys(value, [
      'effect_id',
      'logical_action_id',
      'operation_id',
      'provider_effect_id',
      'effect_type',
      'subject',
      'parameters',
      'state',
      'observed_at',
      'authority',
      'evidence_ids',
      'schema_version',
      'supersedes_effect_id',
    ]) &&
    isString(value.effect_id) &&
    isString(value.logical_action_id) &&
    isString(value.operation_id) &&
    isString(value.provider_effect_id) &&
    isString(value.effect_type) &&
    isJsonObject(value.subject) &&
    isJsonObject(value.parameters) &&
    isOneOf(value.state, [
      'NOT_STARTED',
      'IN_FLIGHT',
      'COMMITTED',
      'FAILED',
      'OUTCOME_UNKNOWN',
      'COMPENSATED',
    ]) &&
    isString(value.observed_at) &&
    isOneOf(value.authority, ['AUTHORITATIVE', 'NON_AUTHORITATIVE', 'DERIVED']) &&
    isStringArray(value.evidence_ids) &&
    value.schema_version === 1 &&
    isNullableString(value.supersedes_effect_id)
  );
}

function isEvidence(value: unknown): boolean {
  return (
    isRecord(value) &&
    hasExactKeys(value, [
      'evidence_id',
      'source',
      'kind',
      'captured_at',
      'content_ref',
      'content_hash',
      'authority',
      'provenance',
      'schema_version',
      'expires_at',
      'derived_from',
    ]) &&
    isString(value.evidence_id) &&
    isOneOf(value.source, ['USER', 'TOOL', 'FRAME', 'AUDIO', 'SYSTEM']) &&
    isString(value.kind) &&
    isString(value.captured_at) &&
    isString(value.content_ref) &&
    isString(value.content_hash) &&
    isOneOf(value.authority, ['AUTHORITATIVE', 'NON_AUTHORITATIVE', 'DERIVED']) &&
    isJsonObject(value.provenance) &&
    value.schema_version === 1 &&
    isNullableString(value.expires_at) &&
    (value.derived_from === null || isStringArray(value.derived_from))
  );
}

function isClaim(value: unknown): boolean {
  return (
    isRecord(value) &&
    hasExactKeys(value, [
      'claim_id',
      'predicate',
      'subject',
      'object',
      'state',
      'required_evidence_rule',
      'supporting_evidence_ids',
      'intent_revision_id',
      'updated_by_event_id',
      'schema_version',
    ]) &&
    isString(value.claim_id) &&
    isString(value.predicate) &&
    isJsonObject(value.subject) &&
    isJsonObject(value.object) &&
    isOneOf(value.state, [
      'PROPOSED',
      'PENDING',
      'CONFIRMED',
      'CONTRADICTED',
      'UNCERTAIN',
      'STALE',
      'SUPERSEDED',
    ]) &&
    isString(value.required_evidence_rule) &&
    isStringArray(value.supporting_evidence_ids) &&
    isString(value.intent_revision_id) &&
    isString(value.updated_by_event_id) &&
    value.schema_version === 1
  );
}

function isSpeech(value: unknown): boolean {
  return (
    isRecord(value) &&
    hasExactKeys(value, [
      'speech_id',
      'act_type',
      'template_id',
      'slots',
      'claim_ids',
      'requested_certainty',
      'state',
      'created_by_event_id',
      'schema_version',
      'supersedes_speech_id',
      'rendered_text',
      'approved_policy_id',
      'approved_through_sequence',
      'approved_claim_versions',
      'heard',
      'cancellation_pending',
      'correction_pending',
    ]) &&
    isString(value.speech_id) &&
    isOneOf(value.act_type, [
      'PROGRESS',
      'CLARIFICATION',
      'RESULT',
      'FAILURE',
      'UNCERTAINTY',
      'DIVERGENCE',
      'CORRECTION',
    ]) &&
    isString(value.template_id) &&
    isJsonObject(value.slots) &&
    isStringArray(value.claim_ids) &&
    isOneOf(value.requested_certainty, [
      'PROGRESS',
      'ACKNOWLEDGED',
      'CONFIRMED',
      'UNCERTAIN',
    ]) &&
    isOneOf(value.state, [
      'PROPOSED',
      'APPROVED',
      'QUEUED',
      'EMITTING',
      'EMITTED',
      'CANCELLED',
      'BLOCKED',
      'CORRECTION_REQUIRED',
    ]) &&
    isString(value.created_by_event_id) &&
    value.schema_version === 1 &&
    isNullableString(value.supersedes_speech_id) &&
    isNullableString(value.rendered_text) &&
    isNullableString(value.approved_policy_id) &&
    (value.approved_through_sequence === null || isPositiveInteger(value.approved_through_sequence)) &&
    isStringRecord(value.approved_claim_versions) &&
    (value.heard === null || isBoolean(value.heard)) &&
    isBoolean(value.cancellation_pending) &&
    isBoolean(value.correction_pending)
  );
}

function isDivergence(value: unknown): boolean {
  return (
    isRecord(value) &&
    hasExactKeys(value, [
      'divergence_id',
      'desired_fingerprint',
      'observed_effect_ids',
      'kind',
      'state',
      'detected_by_event_id',
      'authorization_required',
      'schema_version',
    ]) &&
    isString(value.divergence_id) &&
    isString(value.desired_fingerprint) &&
    isStringArray(value.observed_effect_ids) &&
    isString(value.kind) &&
    isOneOf(value.state, ['OPEN', 'PLANNED', 'RECONCILING', 'RESOLVED', 'ESCALATED']) &&
    isString(value.detected_by_event_id) &&
    isBoolean(value.authorization_required) &&
    value.schema_version === 1
  );
}

function isPlanStep(value: unknown): boolean {
  return (
    isRecord(value) &&
    hasExactKeys(value, [
      'step_id',
      'kind',
      'tool_name',
      'arguments',
      'state',
      'requires_authorization',
      'idempotency_key',
    ]) &&
    isString(value.step_id) &&
    isOneOf(value.kind, [
      'VERIFY_OBSERVED',
      'COMPENSATE_OBSOLETE',
      'VERIFY_COMPENSATION',
      'PREPARE_DESIRED',
      'COMMIT_DESIRED',
      'VERIFY_FINAL',
    ]) &&
    isString(value.tool_name) &&
    isJsonObject(value.arguments) &&
    isOneOf(value.state, ['PENDING', 'RUNNING', 'SUCCEEDED', 'FAILED', 'SKIPPED']) &&
    isBoolean(value.requires_authorization) &&
    isNullableString(value.idempotency_key)
  );
}

function isPlan(value: unknown): boolean {
  return (
    isRecord(value) &&
    hasExactKeys(value, [
      'plan_id',
      'divergence_id',
      'based_on_intent_revision_id',
      'steps',
      'state',
      'provider_capability_hash',
      'schema_version',
      'authorized_by_evidence_id',
    ]) &&
    isString(value.plan_id) &&
    isString(value.divergence_id) &&
    isString(value.based_on_intent_revision_id) &&
    Array.isArray(value.steps) &&
    value.steps.every(isPlanStep) &&
    isOneOf(value.state, ['DRAFT', 'AUTHORIZED', 'RUNNING', 'SUCCEEDED', 'FAILED', 'SUPERSEDED']) &&
    isString(value.provider_capability_hash) &&
    value.schema_version === 1 &&
    isNullableString(value.authorized_by_evidence_id)
  );
}

function isMetrics(value: unknown): boolean {
  return (
    isRecord(value) &&
    hasExactKeys(value, [
      'session_id',
      'through_sequence',
      'counters',
      'durations_ms',
      'gauges',
    ]) &&
    isString(value.session_id) &&
    isNonNegativeInteger(value.through_sequence) &&
    isNumberRecord(value.counters) &&
    isNumberRecord(value.durations_ms) &&
    isNumberRecord(value.gauges)
  );
}

export function isSessionProjection(value: unknown): value is SessionProjection {
  return (
    isRecord(value) &&
    hasExactKeys(value, [
      'intent',
      'operations',
      'effects',
      'evidence',
      'claims',
      'divergences',
      'plans',
      'speech',
      'metrics',
    ]) &&
    (value.intent === null || isIntentProjection(value.intent)) &&
    Array.isArray(value.operations) &&
    value.operations.every(isOperation) &&
    Array.isArray(value.effects) &&
    value.effects.every(isEffect) &&
    Array.isArray(value.evidence) &&
    value.evidence.every(isEvidence) &&
    Array.isArray(value.claims) &&
    value.claims.every(isClaim) &&
    Array.isArray(value.divergences) &&
    value.divergences.every(isDivergence) &&
    Array.isArray(value.plans) &&
    value.plans.every(isPlan) &&
    Array.isArray(value.speech) &&
    value.speech.every(isSpeech) &&
    isMetrics(value.metrics)
  );
}

export function isProjectionEventMessage(value: unknown): value is ProjectionEventMessage {
  if (!isRecord(value) || value.type !== 'event' || value.schema_version !== 1) return false;
  if (
    !isString(value.session_id) ||
    !isPositiveInteger(value.sequence) ||
    !isString(value.event_type) ||
    !isRecord(value.trace) ||
    !isString(value.trace.correlation_id)
  ) {
    return false;
  }
  const delta = value.projection_delta;
  if (
    !isRecord(delta) ||
    !hasExactKeys(delta, ['through_sequence', 'changed', 'removed']) ||
    delta.through_sequence !== value.sequence ||
    !isRecord(delta.changed) ||
    !isRecord(delta.removed)
  ) {
    return false;
  }
  const changedValidators: Readonly<Record<string, (item: unknown) => boolean>> = {
    intent: (item) => item === null || isIntentProjection(item),
    operations: (item) => Array.isArray(item) && item.every(isOperation),
    effects: (item) => Array.isArray(item) && item.every(isEffect),
    evidence: (item) => Array.isArray(item) && item.every(isEvidence),
    claims: (item) => Array.isArray(item) && item.every(isClaim),
    divergences: (item) => Array.isArray(item) && item.every(isDivergence),
    plans: (item) => Array.isArray(item) && item.every(isPlan),
    speech: (item) => Array.isArray(item) && item.every(isSpeech),
    metrics: isMetrics,
  };
  if (
    !Object.entries(delta.changed).every(
      ([key, item]) => key in changedValidators && changedValidators[key](item),
    )
  ) {
    return false;
  }
  const removable = new Set([
    'intent',
    'operations',
    'effects',
    'evidence',
    'claims',
    'divergences',
    'plans',
    'speech',
  ]);
  return Object.entries(delta.removed).every(
    ([key, item]) => removable.has(key) && isStringArray(item),
  );
}

function parseSessionSnapshot(value: unknown): SessionSnapshotResponse | null {
  if (
    !isRecord(value) ||
    !isString(value.session_id) ||
    !isNonNegativeInteger(value.through_sequence) ||
    !isSessionProjection(value.projection)
  ) {
    return null;
  }
  return value as unknown as SessionSnapshotResponse;
}

function parseErrorMessage(body: unknown, status: number): string {
  if (isRecord(body)) {
    if (typeof body.detail === 'string') return body.detail;
    if (Array.isArray(body.detail)) {
      const messages = body.detail
        .filter(isRecord)
        .map((item) => (typeof item.msg === 'string' ? item.msg : null))
        .filter((item): item is string => item !== null);
      if (messages.length) return messages.join('; ');
    }
  }
  return `HTTP request failed with status ${status}.`;
}

async function decodeBody(response: Response): Promise<unknown> {
  const text = await response.text();
  if (!text) return null;
  try {
    return JSON.parse(text) as unknown;
  } catch {
    return text;
  }
}

export class InterlockHttpClient {
  readonly baseUrl: string;
  private readonly fetchValue: FetchLike;

  constructor(options: HttpClientOptions = {}) {
    this.baseUrl = normalizeBaseUrl(options.baseUrl ?? DEFAULT_API_BASE_URL);
    this.fetchValue = options.fetch ?? globalThis.fetch.bind(globalThis);
  }

  private async request<T>(
    path: string,
    init: RequestInit,
    parse: (body: unknown) => T | null,
  ): Promise<T> {
    const method = init.method ?? 'GET';
    const url = resolveUrl(this.baseUrl, path);
    const response = await this.fetchValue(url, {
      ...init,
      headers: {
        Accept: 'application/json',
        ...(init.body === undefined ? {} : { 'Content-Type': 'application/json' }),
        ...init.headers,
      },
    });
    const body = await decodeBody(response);
    if (!response.ok) {
      throw new HttpApplicationError(parseErrorMessage(body, response.status), {
        status: response.status,
        method,
        url,
        body,
      });
    }
    const parsed = parse(body);
    if (parsed === null) {
      throw new HttpProtocolError('Backend returned an invalid JSON response shape.', {
        method,
        url,
        body,
      });
    }
    return parsed;
  }

  health(): Promise<HealthResponse> {
    return this.request('health', { method: 'GET' }, (body) => {
      if (!isRecord(body) || !isString(body.status)) return null;
      if (body.mode !== 'DEMO' && body.mode !== 'LIVE' && body.mode !== 'TEST') return null;
      return body as unknown as HealthResponse;
    });
  }

  createSession(request: SessionCreateRequest): Promise<SessionCreateResponse> {
    return this.request('sessions', { method: 'POST', body: JSON.stringify(request) }, (body) => {
      if (
        !isRecord(body) ||
        !isString(body.session_id) ||
        !isNonNegativeInteger(body.last_sequence) ||
        !isString(body.ws_url)
      ) {
        return null;
      }
      return body as unknown as SessionCreateResponse;
    });
  }

  getSession(sessionId: string): Promise<SessionSnapshotResponse> {
    return this.request(
      `sessions/${encodeURIComponent(sessionId)}`,
      { method: 'GET' },
      parseSessionSnapshot,
    );
  }

  getSnapshotUrl(snapshotUrl: string): Promise<SessionSnapshotResponse> {
    return this.request(snapshotUrl, { method: 'GET' }, parseSessionSnapshot);
  }

  submitInput(sessionId: string, request: InputRequest): Promise<AcceptanceResponse> {
    return this.accepted(`sessions/${encodeURIComponent(sessionId)}/inputs`, request);
  }

  authorize(sessionId: string, request: AuthorizationRequest): Promise<AcceptanceResponse> {
    return this.accepted(`sessions/${encodeURIComponent(sessionId)}/authorizations`, request);
  }

  cancelSpeech(
    sessionId: string,
    speechId: string,
    request: SpeechCancelRequest,
  ): Promise<AcceptanceResponse> {
    return this.accepted(
      `sessions/${encodeURIComponent(sessionId)}/speech/${encodeURIComponent(speechId)}/cancel`,
      request,
    );
  }

  setDemoFault(sessionId: string, request: FaultRequest): Promise<AcceptanceResponse> {
    return this.accepted(`sessions/${encodeURIComponent(sessionId)}/demo/faults`, request);
  }

  resetDemo(sessionId: string, request: ResetRequest): Promise<ResetResponse> {
    return this.request(
      `sessions/${encodeURIComponent(sessionId)}/demo/reset`,
      { method: 'POST', body: JSON.stringify(request) },
      (body) => {
        if (
          !isRecord(body) ||
          !isString(body.session_id) ||
          !isNonNegativeInteger(body.last_sequence)
        ) {
          return null;
        }
        return body as unknown as ResetResponse;
      },
    );
  }

  getEvents(
    sessionId: string,
    afterSequence = 0,
    limit?: number,
  ): Promise<EventPageResponse> {
    const query = new URLSearchParams({ after_sequence: String(afterSequence) });
    if (limit !== undefined) query.set('limit', String(limit));
    return this.request(
      `sessions/${encodeURIComponent(sessionId)}/events?${query.toString()}`,
      { method: 'GET' },
      (body) => {
        if (
          !isRecord(body) ||
          !Array.isArray(body.events) ||
          !body.events.every(isProjectionEventMessage) ||
          !isNonNegativeInteger(body.through_sequence) ||
          typeof body.has_more !== 'boolean'
        ) {
          return null;
        }
        return body as unknown as EventPageResponse;
      },
    );
  }

  private accepted(path: string, request: object): Promise<AcceptanceResponse> {
    return this.request(path, { method: 'POST', body: JSON.stringify(request) }, (body) => {
      if (!isRecord(body) || !isString(body.event_id) || !isNonNegativeInteger(body.sequence)) {
        return null;
      }
      return body as unknown as AcceptanceResponse;
    });
  }
}
