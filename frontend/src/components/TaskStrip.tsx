import React from 'react';
import type {
  IntentProjection,
  IntentRevision,
  OperationProjection,
  JsonObject,
} from '../api/types';
import { TechnicalDetails, type DetailItem } from './TechnicalDetails';
import {
  formatGoalType,
  formatSlot,
  formatToolName,
  formatCancellationState,
} from '../utils/formatters';

interface TaskStripProps {
  readonly intent: IntentProjection | null;
  readonly revision: IntentRevision | null;
  readonly operations: readonly OperationProjection[];
  readonly divergences?: readonly DivergenceProjection[];
}

export const TaskStrip: React.FC<TaskStripProps> = ({
  intent,
  revision,
  operations,
  divergences = [],
}) => {
  if (!intent || !revision) return null;

  const hasDivergence = divergences.length > 0;
  const activeOp = operations[0];
  const values = revision.values as JsonObject;
  const slotValue = values.requested_slot ?? values.slot ?? null;
  const formattedSlot = slotValue ? formatSlot(slotValue) : null;

  // Derive contextual task status
  let statusText = 'Goal registered';
  let dotColor = 'bg-stone-400';

  if (hasDivergence) {
    statusText = 'Desired state updated (unreconciled)';
    dotColor = 'bg-amber-500';
  } else if (activeOp) {
    if (activeOp.state === 'DISPATCHED' || activeOp.state === 'WAITING') {
      statusText = 'Executing provider call…';
      dotColor = 'bg-sky-500 animate-pulse';
    } else if (activeOp.state === 'SUCCEEDED' || activeOp.effect_state === 'COMMITTED') {
      statusText = 'Confirmed with external provider';
      dotColor = 'bg-emerald-500';
    } else if (activeOp.state === 'TIMED_OUT' || activeOp.state === 'FAILED') {
      statusText = `Operation ${activeOp.state.toLowerCase()}`;
      dotColor = 'bg-red-500';
    }
  } else if (revision.maturity === 'COMMITTED') {
    statusText = 'Desired state committed';
    dotColor = 'bg-purple-500';
  }

  const cancelInfo = activeOp ? formatCancellationState(activeOp.cancellation_state) : null;

  const techItems: DetailItem[] = [
    { label: 'Revision ID', value: revision.revision_id },
    { label: 'Tool Function', value: activeOp?.tool_name ? formatToolName(activeOp.tool_name) : 'None' },
    { label: 'Operation ID', value: activeOp?.operation_id ?? 'None' },
    { label: 'Authorization', value: revision.authorization, mono: false },
    { label: 'Idempotency Key', value: activeOp?.idempotency_key ?? 'None' },
  ];

  return (
    <div className="mb-4 rounded-xl border border-stone-200/80 bg-white/70 p-4 transition-colors dark:border-stone-800/80 dark:bg-stone-900/40">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <span className="font-mono text-[10px] font-semibold uppercase tracking-widest text-stone-400 dark:text-stone-500">
            {formatGoalType(intent.goal_type)}
          </span>
          <div className="mt-1 flex items-baseline gap-2">
            <span className="text-lg font-semibold text-stone-900 dark:text-stone-100">
              {formattedSlot ?? 'Appointment'}
            </span>
            <div className="flex items-center gap-1.5 text-xs text-stone-600 dark:text-stone-400">
              <span className={`h-2 w-2 rounded-full ${dotColor}`} aria-hidden="true" />
              <span>{statusText}</span>
            </div>
          </div>
        </div>

        {cancelInfo && cancelInfo.label !== 'None' && (
          <div className="text-right">
            <span className="text-[10px] font-mono uppercase tracking-wider text-stone-400">
              Cancellation Status
            </span>
            <p className="text-xs font-medium text-amber-700 dark:text-amber-400">
              {cancelInfo.label}
            </p>
          </div>
        )}
      </div>

      <TechnicalDetails title="Task details" items={techItems} className="mt-2.5" />
    </div>
  );
};
