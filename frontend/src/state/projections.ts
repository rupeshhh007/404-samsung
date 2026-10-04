import type {
  ClaimProjection,
  DivergenceProjection,
  IntentProjection,
  IntentRevision,
  OperationProjection,
  ProjectionDelta,
  ReconciliationPlanProjection,
  SessionProjection,
  SpeechProjection,
} from '../api/types';

const ACTIVE_OPERATION_STATES = new Set<OperationProjection['state']>([
  'CREATED',
  'PREPARING',
  'READY',
  'DISPATCHED',
  'WAITING',
]);

const ACTIVE_DIVERGENCE_STATES = new Set<DivergenceProjection['state']>([
  'OPEN',
  'PLANNED',
  'RECONCILING',
  'ESCALATED',
]);

function cloneProjection(projection: SessionProjection): SessionProjection {
  return JSON.parse(JSON.stringify(projection)) as SessionProjection;
}

function withoutIds<T>(
  items: readonly T[],
  removed: readonly string[] | undefined,
  identity: (item: T) => string,
): readonly T[] {
  if (!removed || removed.length === 0) return items;
  const removedIds = new Set(removed);
  return items.filter((item) => !removedIds.has(identity(item)));
}

export function applyProjectionDelta(
  current: SessionProjection,
  delta: ProjectionDelta,
): SessionProjection {
  const removed = delta.removed;
  const changed = delta.changed;
  const currentIntent =
    current.intent && removed.intent?.includes(current.intent.intent_id)
      ? null
      : current.intent;

  const next: SessionProjection = {
    intent: Object.prototype.hasOwnProperty.call(changed, 'intent')
      ? changed.intent ?? null
      : currentIntent,
    operations:
      changed.operations ??
      withoutIds(current.operations, removed.operations, (item) => item.operation_id),
    effects:
      changed.effects ?? withoutIds(current.effects, removed.effects, (item) => item.effect_id),
    evidence:
      changed.evidence ??
      withoutIds(current.evidence, removed.evidence, (item) => item.evidence_id),
    claims:
      changed.claims ?? withoutIds(current.claims, removed.claims, (item) => item.claim_id),
    divergences:
      changed.divergences ??
      withoutIds(current.divergences, removed.divergences, (item) => item.divergence_id),
    plans:
      changed.plans ?? withoutIds(current.plans, removed.plans, (item) => item.plan_id),
    speech:
      changed.speech ?? withoutIds(current.speech, removed.speech, (item) => item.speech_id),
    metrics: changed.metrics ?? current.metrics,
  };

  return cloneProjection(next);
}

export function copyProjection(projection: SessionProjection): SessionProjection {
  return cloneProjection(projection);
}

export function selectActiveIntent(projection: SessionProjection): IntentProjection | null {
  return projection.intent;
}

export function selectActiveRevision(projection: SessionProjection): IntentRevision | null {
  return projection.intent?.active_revision ?? null;
}

export function selectOperations(
  projection: SessionProjection,
): readonly OperationProjection[] {
  return projection.operations;
}

export function selectActiveOperations(
  projection: SessionProjection,
): readonly OperationProjection[] {
  return projection.operations.filter((operation) => ACTIVE_OPERATION_STATES.has(operation.state));
}

export function selectClaims(projection: SessionProjection): readonly ClaimProjection[] {
  return projection.claims;
}

export function selectSpeech(projection: SessionProjection): readonly SpeechProjection[] {
  return projection.speech;
}

export function selectDivergences(
  projection: SessionProjection,
): readonly DivergenceProjection[] {
  return projection.divergences;
}

export function selectActiveDivergences(
  projection: SessionProjection,
): readonly DivergenceProjection[] {
  return projection.divergences.filter((item) => ACTIVE_DIVERGENCE_STATES.has(item.state));
}

export function selectPlans(
  projection: SessionProjection,
): readonly ReconciliationPlanProjection[] {
  return projection.plans;
}

export interface SessionProjectionSummary {
  readonly intent_id: string | null;
  readonly operation_count: number;
  readonly effect_count: number;
  readonly claim_count: number;
  readonly speech_count: number;
  readonly divergence_count: number;
  readonly metrics_through_sequence: number;
}

export function selectSessionSummary(
  projection: SessionProjection,
): SessionProjectionSummary {
  return {
    intent_id: projection.intent?.intent_id ?? null,
    operation_count: projection.operations.length,
    effect_count: projection.effects.length,
    claim_count: projection.claims.length,
    speech_count: projection.speech.length,
    divergence_count: projection.divergences.length,
    metrics_through_sequence: projection.metrics.through_sequence,
  };
}
