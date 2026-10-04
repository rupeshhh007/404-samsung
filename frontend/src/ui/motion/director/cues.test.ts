import { describe, it, expect } from 'vitest';
import { detectCues } from './cues';
import type { SessionProjection, DivergenceProjection, ReconciliationPlanProjection } from '../../../api/types';

function mockProj(overrides: Partial<SessionProjection> = {}): SessionProjection {
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
      session_id: 'sess',
      through_sequence: 1,
      counters: {},
      durations_ms: {},
      gauges: {},
    },
    ...overrides,
  };
}

describe('director/cues', () => {
  it('detects SESSION_READY when sessionId transitions from null to string', () => {
    const cues = detectCues(null, mockProj(), null, 'sess-123');
    expect(cues.some((c) => c.id === 'SESSION_READY')).toBe(true);
  });

  it('detects DIVERGENCE_OPEN when divergence opens', () => {
    const prev = mockProj({ divergences: [] });
    const next = mockProj({
      divergences: [
        {
          divergence_id: 'div-1',
          desired_fingerprint: 'fp',
          observed_effect_ids: ['eff-1'],
          kind: 'DESIRED_SLOT_DIFFERS_FROM_CONFIRMED_SLOT',
          state: 'OPEN',
          detected_by_event_id: 'evt-1',
          authorization_required: false,
          schema_version: 1,
        },
      ],
    });

    const cues = detectCues(prev, next, 's', 's');
    expect(cues.some((c) => c.id === 'DIVERGENCE_OPEN')).toBe(true);
  });

  it('LOCK_SNAP fires strictly when divergence.state === RESOLVED', () => {
    const prev = mockProj({
      divergences: [
        {
          divergence_id: 'div-1',
          desired_fingerprint: 'fp',
          observed_effect_ids: ['eff-1'],
          kind: 'DESIRED_SLOT_DIFFERS_FROM_CONFIRMED_SLOT',
          state: 'RECONCILING',
          detected_by_event_id: 'evt-1',
          authorization_required: false,
          schema_version: 1,
        },
      ],
    });
    const next = mockProj({
      divergences: [
        {
          divergence_id: 'div-1',
          desired_fingerprint: 'fp',
          observed_effect_ids: ['eff-1'],
          kind: 'DESIRED_SLOT_DIFFERS_FROM_CONFIRMED_SLOT',
          state: 'RESOLVED',
          detected_by_event_id: 'evt-1',
          authorization_required: false,
          schema_version: 1,
        },
      ],
    });

    const cues = detectCues(prev, next, 's', 's');
    expect(cues.some((c) => c.id === 'LOCK_SNAP')).toBe(true);
  });

  it('NEVER triggers LOCK_SNAP while reconciliation plan is RUNNING', () => {
    const prev = mockProj({
      divergences: [
        {
          divergence_id: 'div-1',
          desired_fingerprint: 'fp',
          observed_effect_ids: ['eff-1'],
          kind: 'DESIRED_SLOT_DIFFERS_FROM_CONFIRMED_SLOT',
          state: 'RECONCILING',
          detected_by_event_id: 'evt-1',
          authorization_required: false,
          schema_version: 1,
        },
      ],
    });
    const next = mockProj({
      divergences: [
        {
          divergence_id: 'div-1',
          desired_fingerprint: 'fp',
          observed_effect_ids: ['eff-1'],
          kind: 'DESIRED_SLOT_DIFFERS_FROM_CONFIRMED_SLOT',
          state: 'RECONCILING',
          detected_by_event_id: 'evt-1',
          authorization_required: false,
          schema_version: 1,
        },
      ],
      plans: [
        {
          plan_id: 'plan-1',
          divergence_id: 'div-1',
          based_on_intent_revision_id: 'rev-1',
          state: 'RUNNING',
          steps: [],
          provider_capability_hash: 'hash',
          schema_version: 1,
          authorized_by_evidence_id: null,
        },
      ],
    });

    const cues = detectCues(prev, next, 's', 's');
    expect(cues.some((c) => c.id === 'LOCK_SNAP')).toBe(false);
  });
});
