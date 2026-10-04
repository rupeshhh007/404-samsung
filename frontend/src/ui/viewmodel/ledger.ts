import type {
  ClaimProjection,
  EffectProjection,
  EvidenceProjection,
  OperationProjection,
  ReconciliationPlanProjection,
  PlanStepProjection,
  PlanStepKind,
} from '../../api/types';

export const OPERATION_RAIL_STAGES = [
  'CREATED',
  'PREPARING',
  'READY',
  'DISPATCHED',
  'WAITING',
  'SUCCEEDED',
] as const;

export interface OperationItemViewModel {
  readonly operation: OperationProjection;
  readonly railIndex: number;
  readonly isTerminalFailure: boolean;
  readonly terminalLabel: string | null;
  readonly effects: readonly EffectProjection[];
}

export function formatOperationRail(
  operations: readonly OperationProjection[],
  effects: readonly EffectProjection[],
): readonly OperationItemViewModel[] {
  // Sorted newest first
  return [...operations].reverse().map((op) => {
    const railIndex = OPERATION_RAIL_STAGES.indexOf(
      op.state as typeof OPERATION_RAIL_STAGES[number],
    );

    let isTerminalFailure = false;
    let terminalLabel: string | null = null;

    if (['FAILED', 'TIMED_OUT', 'CANCELLED', 'SUPERSEDED'].includes(op.state)) {
      isTerminalFailure = true;
      terminalLabel = op.state;
    }

    const opEffects = effects.filter((e) => e.operation_id === op.operation_id);

    return {
      operation: op,
      railIndex: railIndex >= 0 ? railIndex : 0,
      isTerminalFailure,
      terminalLabel,
      effects: opEffects,
    };
  });
}

export interface ClaimWithEvidence {
  readonly claim: ClaimProjection;
  readonly evidence: readonly EvidenceProjection[];
  readonly lockIcon: 'lock-closed' | 'lock-open' | 'lock-broken';
  readonly lockColor: 'verify' | 'alarm' | 'pending' | 'neutral';
}

export function resolveClaimsAndEvidence(
  claims: readonly ClaimProjection[],
  evidenceList: readonly EvidenceProjection[],
): {
  readonly claims: readonly ClaimWithEvidence[];
  readonly unlinkedEvidence: readonly EvidenceProjection[];
} {
  const evidenceMap = new Map<string, EvidenceProjection>();
  evidenceList.forEach((e) => evidenceMap.set(e.evidence_id, e));

  const linkedEvidenceIds = new Set<string>();

  const sortedClaims = [...claims].sort((a, b) => a.claim_id.localeCompare(b.claim_id));

  const claimViewModels: ClaimWithEvidence[] = sortedClaims.map((claim) => {
    const claimEvidence = claim.supporting_evidence_ids
      .map((id) => {
        linkedEvidenceIds.add(id);
        return evidenceMap.get(id);
      })
      .filter((e): e is EvidenceProjection => e !== undefined);

    let lockIcon: 'lock-closed' | 'lock-open' | 'lock-broken' = 'lock-closed';
    let lockColor: 'verify' | 'alarm' | 'pending' | 'neutral' = 'pending';

    switch (claim.state) {
      case 'CONFIRMED':
        lockIcon = 'lock-open';
        lockColor = 'verify';
        break;
      case 'CONTRADICTED':
        lockIcon = 'lock-broken';
        lockColor = 'alarm';
        break;
      case 'UNCERTAIN':
      case 'PENDING':
      case 'PROPOSED':
        lockIcon = 'lock-closed';
        lockColor = 'pending';
        break;
      case 'STALE':
      case 'SUPERSEDED':
      default:
        lockIcon = 'lock-closed';
        lockColor = 'neutral';
        break;
    }

    return {
      claim,
      evidence: claimEvidence,
      lockIcon,
      lockColor,
    };
  });

  const unlinkedEvidence = evidenceList
    .filter((e) => !linkedEvidenceIds.has(e.evidence_id))
    .sort((a, b) => a.captured_at.localeCompare(b.captured_at));

  return {
    claims: claimViewModels,
    unlinkedEvidence,
  };
}

export const STEP_KIND_LABELS: Record<PlanStepKind, string> = {
  VERIFY_OBSERVED: 'Verify what exists',
  COMPENSATE_OBSOLETE: 'Cancel the obsolete booking',
  VERIFY_COMPENSATION: 'Confirm the cancellation',
  PREPARE_DESIRED: 'Prepare the requested slot',
  COMMIT_DESIRED: 'Book the requested slot',
  VERIFY_FINAL: 'Verify the final state',
};

export interface PlanStepViewModel {
  readonly step: PlanStepProjection;
  readonly label: string;
  readonly isRunning: boolean;
  readonly isSucceeded: boolean;
  readonly isFailed: boolean;
}

export interface PlanViewModel {
  readonly plan: ReconciliationPlanProjection;
  readonly steps: readonly PlanStepViewModel[];
  readonly succeededCount: number;
  readonly totalSteps: number;
  readonly runningStep: PlanStepProjection | null;
  readonly needsAuthorization: boolean;
}

export function formatPlanViewModel(plan: ReconciliationPlanProjection | null): PlanViewModel | null {
  if (!plan) return null;

  let runningStep: PlanStepProjection | null = null;
  let succeededCount = 0;

  const steps: PlanStepViewModel[] = plan.steps.map((step) => {
    const isRunning = step.state === 'RUNNING';
    const isSucceeded = step.state === 'SUCCEEDED';
    const isFailed = step.state === 'FAILED';

    if (isRunning) runningStep = step;
    if (isSucceeded) succeededCount += 1;

    const label = STEP_KIND_LABELS[step.kind] ?? step.kind;

    return {
      step,
      label,
      isRunning,
      isSucceeded,
      isFailed,
    };
  });

  const needsAuthorization =
    plan.state === 'DRAFT' ||
    plan.steps.some((s) => s.requires_authorization);

  return {
    plan,
    steps,
    succeededCount,
    totalSteps: steps.length,
    runningStep,
    needsAuthorization,
  };
}
