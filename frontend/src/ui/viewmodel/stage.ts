import type {
  SessionProjection,
  DivergenceProjection,
  ReconciliationPlanProjection,
  ConnectionStatus,
} from '../../api/types';

export type Stage =
  | 'NO_SESSION'
  | 'STALE'
  | 'RESOLVED'
  | 'RECONCILING'
  | 'DIVERGED'
  | 'CANCEL_RACE'
  | 'EXECUTING'
  | 'READY'
  | 'ALIGNED';

export interface StageInfo {
  readonly stage: Stage;
  readonly tension: number;
  readonly gapPx: number;
  readonly resolvedProgress: number;
  readonly activeDivergence: DivergenceProjection | null;
  readonly activePlan: ReconciliationPlanProjection | null;
  readonly isStale: boolean;
}

export function deriveStage(
  projection: SessionProjection | null,
  sessionId: string | null,
  connectionStatus: ConnectionStatus,
  isStale = false,
): StageInfo {
  // 1. NO_SESSION
  if (!sessionId || !projection) {
    return {
      stage: 'NO_SESSION',
      tension: 0,
      gapPx: 48,
      resolvedProgress: 0,
      activeDivergence: null,
      activePlan: null,
      isStale: false,
    };
  }

  // 2. STALE flag
  const throughSeq = projection.metrics?.through_sequence ?? 0;
  const staleState = isStale || (connectionStatus !== 'CONNECTED' && throughSeq > 0);

  // Divergence check
  const divergences = projection.divergences ?? [];
  const openDivergence = divergences.find(
    (d) => d.state === 'OPEN' || d.state === 'ESCALATED',
  );
  const reconcilingDivergence = divergences.find(
    (d) => d.state === 'PLANNED' || d.state === 'RECONCILING',
  );
  const resolvedDivergence = divergences.find((d) => d.state === 'RESOLVED');

  // Plans check
  const plans = projection.plans ?? [];
  const activePlan = plans.find(
    (p) => p.state === 'AUTHORIZED' || p.state === 'RUNNING',
  ) ?? plans[plans.length - 1] ?? null;

  // Plan step progress
  let succeededSteps = 0;
  let totalSteps = 0;
  if (activePlan) {
    totalSteps = activePlan.steps.length;
    succeededSteps = activePlan.steps.filter((s) => s.state === 'SUCCEEDED').length;
  }

  // Operations check
  const operations = projection.operations ?? [];
  const hasCancelRace = operations.some(
    (op) =>
      op.cancellation_state === 'REQUESTED' ||
      op.cancellation_state === 'TOO_LATE' ||
      op.cancellation_state === 'ACKNOWLEDGED',
  );
  const hasExecutingOp = operations.some(
    (op) =>
      !op.speculative &&
      ['CREATED', 'PREPARING', 'READY', 'DISPATCHED', 'WAITING'].includes(op.state),
  );

  // Evaluate stages in strict priority order (§5.2):
  // 3. RESOLVED
  if (resolvedDivergence && !openDivergence && !reconcilingDivergence) {
    return {
      stage: staleState ? 'STALE' : 'RESOLVED',
      tension: 0,
      gapPx: 0,
      resolvedProgress: 1,
      activeDivergence: resolvedDivergence,
      activePlan,
      isStale: staleState,
    };
  }

  // 4. RECONCILING
  if (reconcilingDivergence || (activePlan && (activePlan.state === 'AUTHORIZED' || activePlan.state === 'RUNNING'))) {
    const progress = totalSteps > 0 ? succeededSteps / totalSteps : 0;
    const tension = Math.max(0.15, 1 - progress);
    const gapPx = Math.round(160 * (1 - progress));
    return {
      stage: staleState ? 'STALE' : 'RECONCILING',
      tension,
      gapPx,
      resolvedProgress: progress,
      activeDivergence: reconcilingDivergence ?? openDivergence ?? null,
      activePlan,
      isStale: staleState,
    };
  }

  // 5. DIVERGED
  if (openDivergence) {
    return {
      stage: staleState ? 'STALE' : 'DIVERGED',
      tension: 1.0,
      gapPx: 160,
      resolvedProgress: 0,
      activeDivergence: openDivergence,
      activePlan,
      isStale: staleState,
    };
  }

  // 6. CANCEL_RACE
  if (hasCancelRace) {
    return {
      stage: staleState ? 'STALE' : 'CANCEL_RACE',
      tension: 0.35,
      gapPx: 48,
      resolvedProgress: 0,
      activeDivergence: null,
      activePlan: null,
      isStale: staleState,
    };
  }

  // 7. EXECUTING
  if (hasExecutingOp) {
    return {
      stage: staleState ? 'STALE' : 'EXECUTING',
      tension: 0.15,
      gapPx: 48,
      resolvedProgress: 0,
      activeDivergence: null,
      activePlan: null,
      isStale: staleState,
    };
  }

  // 8. READY
  if (!projection.intent) {
    return {
      stage: staleState ? 'STALE' : 'READY',
      tension: 0,
      gapPx: 48,
      resolvedProgress: 0,
      activeDivergence: null,
      activePlan: null,
      isStale: staleState,
    };
  }

  // 9. ALIGNED
  return {
    stage: staleState ? 'STALE' : 'ALIGNED',
    tension: 0,
    gapPx: 0,
    resolvedProgress: 1,
    activeDivergence: null,
    activePlan: null,
    isStale: staleState,
  };
}
