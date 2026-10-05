import { describe, it, expect } from 'vitest';
import { deriveStage } from './stage';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { IntentRealityHero } from '../deck/IntentRealityHero';
import { CurrentActionStrip } from '../deck/CurrentActionStrip';
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
  it.each(['FAILED', 'UNKNOWN', 'STALE', 'RESOLVED'] as const)('preserves %s in the hero', (stage) => {
    const markup = renderToStaticMarkup(createElement(IntentRealityHero, {
      stage, gapPx: 0, projection: createMockProjection(),
    }));
    expect(markup).not.toContain('Aligned · Verified');
    expect(markup).toContain(`intent-reality--${stage.toLowerCase()}`);
  });

  it('labels a timed-out action as an unknown outcome', () => {
    const markup = renderToStaticMarkup(createElement(CurrentActionStrip, {
      projection: createMockProjection({operations: [createMockOperation({state: 'TIMED_OUT'})]}),
    }));
    expect(markup).toContain('Booking appointment · Outcome unknown');
    expect(markup).not.toContain('Failed');
  });

  it('does not imply investigation for an open divergence', () => {
    const markup = renderToStaticMarkup(createElement(CurrentActionStrip, {
      projection: createMockProjection({divergences: [createMockDivergence()]}),
    }));
    expect(markup).toContain('Divergence open · no repair started');
  });
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

  it('returns ALIGNED strictly when authoritative observed reality matches active desired state', () => {
    const proj = createMockProjection({
      intent: {
        intent_id: 'int-1',
        goal_type: 'appointment_booking',
        revisions: ['rev-1'],
        active_revision_id: 'rev-1',
        active_revision: {
          revision_id: 'rev-1',
          intent_id: 'int-1',
          parent_revision_id: null,
          values: { requested_slot: '2030-01-15T11:00:00+05:30' },
          maturity: 'COMMITTED',
          authorization: 'AUTHORIZED',
          created_by_event_id: 'e1',
          dependency_fingerprint: 'fp-1',
        },
      },
      operations: [createMockOperation({ state: 'SUCCEEDED' })],
      effects: [
        {
          effect_id: 'eff-1',
          logical_action_id: 'act-1',
          operation_id: 'op-1',
          provider_effect_id: 'p-1',
          effect_type: 'appointment.booking',
          subject: {},
          parameters: { confirmed_slot: '2030-01-15T11:00:00+05:30' },
          state: 'COMMITTED',
          observed_at: '2030-01-15T10:00:00Z',
          authority: 'AUTHORITATIVE',
          evidence_ids: ['ev-1'],
          schema_version: 1,
          supersedes_effect_id: null,
        },
      ],
    });
    const stage = deriveStage(proj, 'sess-1', 'CONNECTED');
    expect(stage.stage).toBe('ALIGNED');
    expect(stage.tension).toBe(0);
    expect(stage.gapPx).toBe(0);
    expect(stage.resolvedProgress).toBe(1);
  });

  it('returns UNVERIFIED when intent is accepted but no authoritative effect exists yet', () => {
    const proj = createMockProjection({
      intent: {
        intent_id: 'int-1',
        goal_type: 'appointment_booking',
        revisions: ['rev-1'],
        active_revision_id: 'rev-1',
        active_revision: {
          revision_id: 'rev-1',
          intent_id: 'int-1',
          parent_revision_id: null,
          values: { requested_slot: '2030-01-15T11:00:00+05:30' },
          maturity: 'COMMITTED',
          authorization: 'AUTHORIZED',
          created_by_event_id: 'e1',
          dependency_fingerprint: 'fp-1',
        },
      },
      operations: [],
      effects: [],
    });
    const stage = deriveStage(proj, 'sess-1', 'CONNECTED');
    expect(stage.stage).toBe('UNVERIFIED');
    expect(stage.tension).toBe(0.1);
  });

  it('returns FAILED when active operation has failed', () => {
    const proj = createMockProjection({
      intent: {
        intent_id: 'int-1',
        goal_type: 'appointment_booking',
        revisions: ['rev-1'],
        active_revision_id: 'rev-1',
        active_revision: {
          revision_id: 'rev-1',
          intent_id: 'int-1',
          parent_revision_id: null,
          values: { requested_slot: '2030-01-15T11:00:00+05:30' },
          maturity: 'COMMITTED',
          authorization: 'AUTHORIZED',
          created_by_event_id: 'e1',
          dependency_fingerprint: 'fp-1',
        },
      },
      operations: [
        createMockOperation({
          state: 'FAILED',
          error: { code: 'PROVIDER_ERROR', message: 'Failed', retryable: false },
        }),
      ],
    });
    const stage = deriveStage(proj, 'sess-1', 'CONNECTED');
    expect(stage.stage).toBe('FAILED');
    expect(stage.tension).toBe(0.8);
  });

  it('returns UNKNOWN when active operation timed out', () => {
    const proj = createMockProjection({
      intent: {
        intent_id: 'int-1',
        goal_type: 'appointment_booking',
        revisions: ['rev-1'],
        active_revision_id: 'rev-1',
        active_revision: {
          revision_id: 'rev-1',
          intent_id: 'int-1',
          parent_revision_id: null,
          values: { requested_slot: '2030-01-15T11:00:00+05:30' },
          maturity: 'COMMITTED',
          authorization: 'AUTHORIZED',
          created_by_event_id: 'e1',
          dependency_fingerprint: 'fp-1',
        },
      },
      operations: [createMockOperation({ state: 'TIMED_OUT' })],
    });
    const stage = deriveStage(proj, 'sess-1', 'CONNECTED');
    expect(stage.stage).toBe('UNKNOWN');
    expect(stage.tension).toBe(0.5);
  });
});
