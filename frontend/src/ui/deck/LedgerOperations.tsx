import React from 'react';
import { Chip } from '../primitives/Chip';
import { Details } from '../primitives/Details';
import { Eyebrow } from '../primitives/Eyebrow';
import { formatOperationRail, OPERATION_RAIL_STAGES } from '../viewmodel/ledger';
import { formatCancellationState, formatToolName } from '../../utils/formatters';
import type { OperationProjection, EffectProjection } from '../../api/types';

interface LedgerOperationsProps {
  readonly operations: readonly OperationProjection[];
  readonly effects: readonly EffectProjection[];
}

export const LedgerOperations: React.FC<LedgerOperationsProps> = ({
  operations,
  effects,
}) => {
  const opViewModels = formatOperationRail(operations, effects);

  if (operations.length === 0) {
    return (
      <div className="p-4 bg-ink-850 border border-ink-600 font-mono text-xs text-bone-500 text-center">
        No operation is currently projected. This does not imply completion.
      </div>
    );
  }

  return (
    <div className="space-y-3 font-mono text-xs">
      {opViewModels.map(({ operation: op, railIndex, isTerminalFailure, terminalLabel }) => {
        const isSpeculative = op.speculative;
        const cancellation = formatCancellationState(op.cancellation_state);

        return (
          <div
            key={op.operation_id}
            className={`p-3 bg-ink-850 border ${
              isSpeculative ? 'border-sig-spec border-dashed' : 'border-ink-600'
            } space-y-2`}
          >
            {/* Header */}
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                <span className="font-bold text-bone-50">
                  {formatToolName(op.tool_name)}
                </span>
                {isSpeculative && (
                  <Chip variant="spec" dashed className="h-5 text-[9px]">
                    ANTICIPATED · READ-ONLY
                  </Chip>
                )}
              </div>
              <div className="flex items-center gap-1.5">
                <Chip
                  variant={op.state === 'SUCCEEDED' ? 'verify' : op.state === 'FAILED' ? 'alarm' : 'active'}
                  className="h-5 text-[9px]"
                >
                  {op.state}
                </Chip>
                {op.cancellation_state !== 'NONE' && (
                  <Chip
                    variant={op.cancellation_state === 'TOO_LATE' ? 'alarm' : 'pending'}
                    className="h-5 text-[9px]"
                  >
                    {cancellation.label}
                  </Chip>
                )}
              </div>
            </div>

            {/* Lifecycle Rail (6 nodes) */}
            <div className="py-2">
              <div className="flex items-center justify-between relative">
                {/* Connecting Line */}
                <div className="absolute left-0 right-0 top-1/2 -translate-y-1/2 h-0.5 bg-ink-700 -z-0" />
                {OPERATION_RAIL_STAGES.map((stageName, idx) => {
                  const isReached = idx <= railIndex;
                  const isCurrent = idx === railIndex;

                  return (
                    <div
                      key={stageName}
                      className="relative z-10 flex flex-col items-center gap-1"
                      title={stageName}
                    >
                      <div
                        className={`w-3 h-3 rounded-none border ${
                          isReached
                            ? 'bg-sig-active border-sig-active'
                            : 'bg-ink-900 border-ink-600'
                        } ${isCurrent ? 'ring-2 ring-sig-active/40 animate-pulse' : ''}`}
                      />
                      <span className="text-[8px] text-bone-600 uppercase tracking-tighter hidden sm:inline">
                        {stageName.slice(0, 4)}
                      </span>
                    </div>
                  );
                })}
              </div>
            </div>

            {/* Terminal failure side marker if applicable */}
            {isTerminalFailure && (
              <div className="text-sig-alarm text-[10px] uppercase font-bold pt-1">
                TERMINAL STATE: {terminalLabel}
              </div>
            )}

            {/* Details */}
            <Details
              title="Operation Details"
              items={[
                { label: 'Operation ID', value: op.operation_id },
                { label: 'Idempotency Key', value: op.idempotency_key },
                { label: 'Action Type', value: op.action_type },
                { label: 'Capability Hash', value: op.descriptor_capability_hash },
              ]}
            />
          </div>
        );
      })}
    </div>
  );
};
