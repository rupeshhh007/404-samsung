import type { SessionProjection } from '../../../api/types';

export type CueId =
  | 'SESSION_READY'
  | 'INTENT_REVISED'
  | 'OP_DISPATCHED'
  | 'CANCEL_REQUESTED'
  | 'CANCEL_TOO_LATE'
  | 'REALITY_OBSERVED'
  | 'DIVERGENCE_OPEN'
  | 'SPEECH_APPROVED'
  | 'PLAN_PROJECTED'
  | 'STEP_SUCCEEDED'
  | 'LOCK_SNAP'
  | 'SPEECH_CANCELLED_OR_CORRECTION'
  | 'STALE';

export interface CueEvent {
  readonly id: CueId;
  readonly announcement?: {
    readonly type: 'polite' | 'assertive';
    readonly message: string;
  };
  readonly payload?: unknown;
}

/**
 * Pure transition detector comparing previous and next projections.
 * Never celebrates early: LOCK_SNAP triggers strictly when divergence.state === 'RESOLVED'.
 */
export function detectCues(
  prev: SessionProjection | null,
  next: SessionProjection | null,
  prevSessionId: string | null,
  nextSessionId: string | null,
): readonly CueEvent[] {
  const cues: CueEvent[] = [];

  // T1: SESSION_READY
  if (!prevSessionId && nextSessionId) {
    cues.push({
      id: 'SESSION_READY',
      announcement: { type: 'polite', message: 'Session ready.' },
    });
  }

  if (!next) return cues;

  // T2: INTENT_REVISED
  const prevRevId = prev?.intent?.active_revision_id;
  const nextRevId = next.intent?.active_revision_id;
  if (nextRevId && nextRevId !== prevRevId) {
    const slot = next.intent?.active_revision?.values?.requested_slot ?? 'new slot';
    cues.push({
      id: 'INTENT_REVISED',
      announcement: { type: 'polite', message: `Request is now ${slot}.` },
    });
  }

  // T3, T4, T5: Operations check
  const prevOps = prev?.operations ?? [];
  const nextOps = next.operations ?? [];

  for (const op of nextOps) {
    const oldOp = prevOps.find((o) => o.operation_id === op.operation_id);

    // T3: OP_DISPATCHED
    if ((!oldOp || oldOp.state !== 'DISPATCHED') && op.state === 'DISPATCHED') {
      cues.push({ id: 'OP_DISPATCHED' });
    }

    // T4: CANCEL_REQUESTED
    if (
      (!oldOp || oldOp.cancellation_state !== 'REQUESTED') &&
      op.cancellation_state === 'REQUESTED'
    ) {
      cues.push({
        id: 'CANCEL_REQUESTED',
        announcement: {
          type: 'polite',
          message: 'Cancellation requested for the earlier request.',
        },
      });
    }

    // T5: CANCEL_TOO_LATE
    if (
      (!oldOp || oldOp.cancellation_state !== 'TOO_LATE') &&
      op.cancellation_state === 'TOO_LATE'
    ) {
      cues.push({
        id: 'CANCEL_TOO_LATE',
        announcement: {
          type: 'polite',
          message: 'Cancellation arrived too late.',
        },
      });
    }
  }

  // T6: REALITY_OBSERVED
  const prevEffects = prev?.effects ?? [];
  const nextEffects = next.effects ?? [];
  if (nextEffects.length > prevEffects.length) {
    const newCommitted = nextEffects.find(
      (e) => e.state === 'COMMITTED' && !prevEffects.some((pe) => pe.effect_id === e.effect_id),
    );
    if (newCommitted) {
      cues.push({
        id: 'REALITY_OBSERVED',
        announcement: { type: 'polite', message: 'World reports confirmed effect.' },
      });
    }
  }

  // T7: DIVERGENCE_OPEN
  const prevDivergences = prev?.divergences ?? [];
  const nextDivergences = next.divergences ?? [];
  const newlyOpened = nextDivergences.find(
    (d) =>
      (d.state === 'OPEN' || d.state === 'ESCALATED') &&
      !prevDivergences.some((pd) => pd.divergence_id === d.divergence_id && pd.state === d.state),
  );
  if (newlyOpened) {
    cues.push({
      id: 'DIVERGENCE_OPEN',
      announcement: {
        type: 'assertive',
        message: 'Divergence detected between requested intent and external reality.',
      },
    });
  }

  // T8 & T12: Speech check
  const prevSpeech = prev?.speech ?? [];
  const nextSpeech = next.speech ?? [];
  for (const s of nextSpeech) {
    const oldSpeech = prevSpeech.find((ps) => ps.speech_id === s.speech_id);

    // T8: SPEECH_APPROVED
    if (
      (!oldSpeech || oldSpeech.state !== 'EMITTED') &&
      s.state === 'EMITTED' &&
      s.rendered_text
    ) {
      cues.push({
        id: 'SPEECH_APPROVED',
        announcement: {
          type: s.act_type === 'PROGRESS' ? 'polite' : 'assertive',
          message: s.rendered_text,
        },
      });
    }

    // T12: SPEECH_CANCELLED_OR_CORRECTION
    if (
      (!oldSpeech || oldSpeech.state !== 'CORRECTION_REQUIRED') &&
      s.state === 'CORRECTION_REQUIRED'
    ) {
      cues.push({
        id: 'SPEECH_CANCELLED_OR_CORRECTION',
        announcement: {
          type: 'assertive',
          message: 'Correction required: previous statement may no longer be true.',
        },
      });
    }
  }

  // T9 & T10: Plan & Steps
  const prevPlans = prev?.plans ?? [];
  const nextPlans = next.plans ?? [];
  if (nextPlans.length > prevPlans.length) {
    cues.push({
      id: 'PLAN_PROJECTED',
      announcement: { type: 'polite', message: 'Repair plan projected.' },
    });
  }

  // T11: LOCK_SNAP (Money shot: fires strictly when divergence.state === 'RESOLVED')
  const newlyResolved = nextDivergences.find(
    (d) =>
      d.state === 'RESOLVED' &&
      !prevDivergences.some((pd) => pd.divergence_id === d.divergence_id && pd.state === 'RESOLVED'),
  );
  if (newlyResolved) {
    cues.push({
      id: 'LOCK_SNAP',
      announcement: {
        type: 'assertive',
        message: 'Divergence resolved.',
      },
    });
  }

  return cues;
}
