import React from 'react';
import type { OperationProjection } from '../api/types';
import { Icons } from './Icons';
import { TechnicalDetails, type DetailItem } from './TechnicalDetails';
import {
  formatToolName,
  formatOperationState,
  formatEffectState,
  formatCancellationState,
} from '../utils/formatters';

interface OperationPanelProps {
  readonly operations: readonly OperationProjection[];
}

function toneClass(tone: string): string {
  if (tone === 'success') return 'status-success';
  if (tone === 'active') return 'status-active';
  if (tone === 'warning') return 'status-warning';
  if (tone === 'danger') return 'status-danger';
  return 'status-neutral';
}

export const OperationPanel: React.FC<OperationPanelProps> = ({ operations }) => {
  const ordered = [...operations].sort((left, right) =>
    left.operation_id.localeCompare(right.operation_id),
  );

  return (
    <section className="panel" aria-labelledby="operation-heading">
      <div className="panel-heading">
        <div className="flex items-center gap-2">
          <Icons.Zap className="h-4 w-4 text-amber-500 dark:text-amber-400" />
          <div>
            <p className="eyebrow">Tool Execution</p>
            <h2 id="operation-heading">Operations</h2>
          </div>
        </div>
        <span className="status-pill status-neutral">
          {operations.length} {operations.length === 1 ? 'operation' : 'operations'}
        </span>
      </div>

      {ordered.length === 0 ? (
        <div className="empty-state">
          No tool operations recorded. Operations dispatch through SAFEPOINT when goals are authorized.
        </div>
      ) : (
        <div className="space-y-3">
          {ordered.map((operation) => {
            const opState = formatOperationState(operation.state);
            const effectState = formatEffectState(operation.effect_state);
            const cancelState = formatCancellationState(operation.cancellation_state);

            const techItems: DetailItem[] = [
              { label: 'Operation ID', value: operation.operation_id },
              { label: 'Tool Function', value: operation.tool_name },
              { label: 'Action Classification', value: operation.action_type, mono: false },
              { label: 'Cancellation Policy', value: operation.cancellation_policy, mono: false },
              { label: 'Idempotency Key', value: operation.idempotency_key },
            ];

            return (
              <div
                key={operation.operation_id}
                className="rounded-lg border border-stone-200/80 bg-stone-50/60 p-3 text-sm transition-colors dark:border-stone-800/80 dark:bg-stone-950/40"
              >
                {/* Header: Human-friendly tool name + State pill */}
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="flex items-center gap-1.5">
                    <span className="font-semibold text-stone-900 dark:text-stone-100">
                      {formatToolName(operation.tool_name)}
                    </span>
                    <span className="text-[11px] text-stone-400 dark:text-stone-500 font-mono">
                      ({operation.tool_name})
                    </span>
                  </div>
                  <span className={`status-pill ${toneClass(opState.tone)}`}>
                    {opState.label}
                  </span>
                </div>

                {/* Key operational status grid */}
                <div className="mt-2.5 grid grid-cols-2 gap-2 text-xs">
                  <div className="flex flex-col">
                    <span className="text-[10px] uppercase tracking-wider text-stone-400 dark:text-stone-500">
                      World Effect
                    </span>
                    <span className="mt-0.5 font-medium text-stone-700 dark:text-stone-300">
                      {effectState.label}
                    </span>
                  </div>
                  <div className="flex flex-col">
                    <span className="text-[10px] uppercase tracking-wider text-stone-400 dark:text-stone-500">
                      Cancellation
                    </span>
                    <span className="mt-0.5 font-medium text-stone-700 dark:text-stone-300">
                      {cancelState.label}
                    </span>
                  </div>
                </div>

                {operation.error && (
                  <div className="mt-2.5 rounded border border-rose-200 bg-rose-50/80 p-2 text-xs text-rose-800 dark:border-rose-900/60 dark:bg-rose-950/40 dark:text-rose-300">
                    <span className="font-semibold">{operation.error.code}: </span>
                    {operation.error.message}
                  </div>
                )}

                {/* Progressive disclosure for technical identifiers */}
                <TechnicalDetails title="Protocol metadata" items={techItems}>
                  {operation.args && Object.keys(operation.args).length > 0 && (
                    <div className="mt-2">
                      <span className="text-[10px] uppercase tracking-wider text-stone-400 dark:text-stone-500 font-medium">
                        Arguments Payload
                      </span>
                      <pre className="mt-1 max-h-32 overflow-auto rounded bg-white p-2 font-mono text-[11px] text-stone-700 dark:bg-stone-900 dark:text-stone-300">
                        {JSON.stringify(operation.args, null, 2)}
                      </pre>
                    </div>
                  )}
                </TechnicalDetails>
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
};
