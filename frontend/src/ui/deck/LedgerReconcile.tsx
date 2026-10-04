import React from 'react';
import { Chip } from '../primitives/Chip';
import { Button } from '../primitives/Button';
import { Icon } from '../primitives/Icon';
import { formatPlanViewModel } from '../viewmodel/ledger';
import { shortenId } from '../../utils/formatters';
import type { ReconciliationPlanProjection, DivergenceProjection } from '../../api/types';

interface LedgerReconcileProps {
  readonly plan: ReconciliationPlanProjection | null;
  readonly divergence: DivergenceProjection | null;
  readonly onAuthorize?: (planId: string, decision: 'AUTHORIZE' | 'DENY') => void;
  readonly actionPending?: boolean;
}

export const LedgerReconcile: React.FC<LedgerReconcileProps> = ({
  plan,
  divergence,
  onAuthorize,
  actionPending = false,
}) => {
  const planVm = formatPlanViewModel(plan);

  if (!divergence) {
    return (
      <div className="p-4 bg-ink-850 border border-ink-600 font-mono text-xs text-bone-500 text-center">
        No divergence to reconcile.
      </div>
    );
  }

  if (!planVm) {
    return (
      <div className="p-4 bg-ink-850 border border-sig-alarm/30 font-mono text-xs text-bone-500 text-center space-y-1">
        <div className="text-sig-alarm font-bold">DIVERGENCE OPEN</div>
        <div>No repair plan projected yet. The runtime has not attempted a repair.</div>
      </div>
    );
  }

  const isResolved = divergence.state === 'RESOLVED';

  return (
    <div className="space-y-4 font-mono text-xs bg-ink-850 border border-ink-600 p-4">
      {/* Plan Header */}
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-ink-600/60 pb-3">
        <div>
          <span className="font-bold text-bone-50 mr-2">REPAIR PLAN</span>
          <span className="text-bone-500 text-[10px]">
            BASED ON r{shortenId(planVm.plan.based_on_intent_revision_id, 4, 3)}
          </span>
        </div>

        <div className="flex items-center gap-2">
          <span className="text-bone-500 text-[11px]">
            {planVm.succeededCount} / {planVm.totalSteps} VERIFIED
          </span>
          <Chip
            variant={isResolved ? 'verify' : planVm.plan.state === 'RUNNING' ? 'adapt' : 'neutral'}
            className="h-5 text-[9px]"
          >
            {isResolved ? 'RESOLVED' : planVm.plan.state}
          </Chip>
        </div>
      </div>

      {/* Vertical Stepper */}
      <div className="space-y-3 pl-2">
        {planVm.steps.map(({ step, label, isRunning, isSucceeded, isFailed }, index) => {
          let nodeIcon = null;
          let nodeStyle = 'border-ink-600 bg-ink-900 text-bone-500';

          if (isSucceeded) {
            nodeStyle = 'border-sig-adapt bg-sig-adapt text-ink-950 font-bold';
            nodeIcon = <Icon name="check" size={10} />;
          } else if (isRunning) {
            nodeStyle = 'border-sig-adapt bg-sig-adapt/20 text-sig-adapt animate-pulse';
            nodeIcon = <span className="w-1.5 h-1.5 rounded-full bg-sig-adapt" />;
          } else if (isFailed) {
            nodeStyle = 'border-sig-alarm bg-sig-alarm text-bone-50';
            nodeIcon = <Icon name="cross" size={10} />;
          }

          return (
            <div key={step.step_id} className="flex items-start gap-3 relative">
              {/* Vertical connecting line */}
              {index < planVm.steps.length - 1 && (
                <div className="absolute left-[9px] top-5 bottom-[-14px] w-0.5 bg-ink-700" />
              )}

              {/* Step Node */}
              <div
                className={`w-5 h-5 flex items-center justify-center flex-shrink-0 border text-[10px] z-10 ${nodeStyle}`}
              >
                {nodeIcon ?? index + 1}
              </div>

              {/* Step Details */}
              <div className="flex-1 min-w-0 pt-0.5">
                <div className="flex items-center justify-between gap-1">
                  <span className={`font-semibold ${isSucceeded ? 'text-bone-50' : 'text-bone-300'}`}>
                    {label}
                  </span>
                  <Chip
                    variant={isSucceeded ? 'adapt' : isRunning ? 'active' : 'neutral'}
                    className="h-4 text-[8px]"
                  >
                    {step.state}
                  </Chip>
                </div>
                <div className="text-[10px] text-bone-500 truncate mt-0.5">
                  TOOL: {step.tool_name}
                </div>
              </div>
            </div>
          );
        })}
      </div>

      {/* Authorization Required Action Buttons */}
      {planVm.needsAuthorization && onAuthorize && (
        <div className="pt-3 border-t border-ink-600 flex items-center justify-end gap-3">
          <Button
            variant="ghost"
            onClick={() => onAuthorize(planVm.plan.plan_id, 'DENY')}
            disabled={actionPending}
            className="text-xs h-8"
          >
            Deny
          </Button>
          <Button
            variant="primary"
            onClick={() => onAuthorize(planVm.plan.plan_id, 'AUTHORIZE')}
            disabled={actionPending}
            className="text-xs h-8 font-bold"
          >
            Authorize Repair
          </Button>
        </div>
      )}
    </div>
  );
};
