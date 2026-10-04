import { describe, it, expect } from 'vitest';
import { deriveStage } from './stage';
import type { SessionProjection, OperationProjection, DivergenceProjection } from '../../api/types';

function createMockOperation(overrides: Partial<OperationProjection> = {}): OperationProjection {
  return {
    operation_id: 'op-1',
    tool_name: 'test',
    args: {},
    intent_revision_id: 'rev-1',
    bindings: [],
    fingerprint: 'fp-1',
    action_type: 'REVERSIBLE',
    cancellation_policy: 'AT_SAFEPOINT',
    state: 'DISPATCHED',
    cancellation_state: 'NONE',
    cancellation_ack_scopes: [],
    effect_state: 'IN_FLIGHT',
    speculative: false,
    logical_action_id: 'act-1',
    idempotency_key: 'idem-1',
    descriptor_capability_hash: 'hash-1',
    schema_version: 1,
    provider_request_id: null,
    dispatch_requested_event_id: null,
    error: null,
    ...overrides,
  };
}

function createMockDivergence(overrides: Partial<DivergenceProjection> = {}): DivergenceProjection {
  return {
    divergence_id: 'div-1',
    desired_fingerprint: 'fp-1',
    observed_effect_ids: ['eff-1'],
    kind: 'DESIRED_SLOT_DIFFERS_FROM_CONFIRMED_SLOT',
    state: 'OPEN',
    detected_by_event_id: 'evt-1',
    authorization_required: false,
    schema_version: 1,
    ...overrides,
  };
}

function createMockProjection(overrides: Partial<SessionProjection> = {}): SessionProjection {
  return {
    intent: null,
    operations: [],
    effects: [],
    evidence: [],
    claims: [],
    divergences: [],
    plans: [],
    speech: [],
    metrics: {
      session_id: 'test-session',
      through_sequence: 1,
      counters: {},
      durations_ms: {},
      gauges: {},
    },
    ...overrides,
  };
}

describe('viewmodel/stage', () => {
  it('returns NO_SESSION when sessionId is null', () => {
    const stage = deriveStage(null, null, 'DISCONNECTED');
    expect(stage.stage).toBe('NO_SESSION');
    expect(stage.tension).toBe(0);
  });

  it('returns READY when session exists without intent', () => {
    const proj = createMockProjection();
    const stage = deriveStage(proj, 'sess-1', 'CONNECTED');
    expect(stage.stage).toBe('READY');
    expect(stage.tension).toBe(0);
  });

  it('returns EXECUTING when an operation is dispatched', () => {
    const proj = createMockProjection({
      operations: [createMockOperation({ state: 'DISPATCHED' })],
    });
    const stage = deriveStage(proj, 'sess-1', 'CONNECTED');
    expect(stage.stage).toBe('EXECUTING');
    expect(stage.tension).toBe(0.15);
  });

  it('returns CANCEL_RACE when cancellation_state is TOO_LATE', () => {
    const proj = createMockProjection({
      operations: [createMockOperation({ state: 'SUCCEEDED', cancellation_state: 'TOO_LATE' })],
    });
    const stage = deriveStage(proj, 'sess-1', 'CONNECTED');
    expect(stage.stage).toBe('CANCEL_RACE');
    expect(stage.tension).toBe(0.35);
  });

  it('returns DIVERGED when open divergence exists', () => {
    const proj = createMockProjection({
      divergences: [createMockDivergence({ state: 'OPEN' })],
    });
    const stage = deriveStage(proj, 'sess-1', 'CONNECTED');
    expect(stage.stage).toBe('DIVERGED');
    expect(stage.tension).toBe(1.0);
    expect(stage.gapPx).toBe(160);
  });

  it('returns RESOLVED when divergence is resolved', () => {
    const proj = createMockProjection({
      divergences: [createMockDivergence({ state: 'RESOLVED' })],
    });
    const stage = deriveStage(proj, 'sess-1', 'CONNECTED');
    expect(stage.stage).toBe('RESOLVED');
    expect(stage.tension).toBe(0);
    expect(stage.gapPx).toBe(0);
    expect(stage.resolvedProgress).toBe(1);
  });
});
