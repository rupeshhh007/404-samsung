import React, { useMemo } from 'react';
import { Slab } from './Slab';
import { Cable } from './Cable';
import { Chip } from '../primitives/Chip';
import { Details } from '../primitives/Details';
import {
  formatSlotParts,
  extractDesiredSlot,
  selectObservedWorld,
  selectActiveOperation,
} from '../viewmodel/slots';
import { formatCancellationState } from '../../utils/formatters';
import type { Stage } from '../viewmodel/stage';
import type { SessionProjection } from '../../api/types';

interface InterlockBridgeProps {
  readonly stage: Stage;
  readonly gapPx: number;
  readonly projection: SessionProjection | null;
  readonly readOnly?: boolean;
}

export const InterlockBridge: React.FC<InterlockBridgeProps> = ({
  stage,
  gapPx,
  projection,
}) => {
  const intent = projection?.intent ?? null;
  const revision = intent?.active_revision ?? null;

  // Pure semantic selectors
  const observed = useMemo(() => selectObservedWorld(projection), [projection]);
  const activeDivergence = observed.divergence;
  const activeOp = useMemo(() => selectActiveOperation(projection), [projection]);

  // Extract desired & observed slots cleanly using pure viewmodels
  const rawDesired = useMemo(() => extractDesiredSlot(intent, revision), [intent, revision]);
  const desiredParts = useMemo(() => formatSlotParts(rawDesired), [rawDesired]);
  const observedParts = useMemo(() => formatSlotParts(observed.rawSlot), [observed.rawSlot]);

  const isDiverged = stage === 'DIVERGED';
  const isMeshed = stage === 'ALIGNED' || stage === 'RESOLVED';

  const cancellation = activeOp
    ? formatCancellationState(activeOp.cancellation_state)
    : null;

  return (
    <div className="flex flex-col space-y-3 bg-ink-900 border border-ink-600 p-4 select-none">
      {/* Hero Bridge: Two Slabs with Taut Cable / Meshed Seam */}
      <div className="relative flex items-center justify-between min-h-[220px]">
        {/* Left Slab: Intent */}
        <Slab
          side="intent"
          eyebrow="INTENT · WHAT YOU ASKED FOR"
          slotParts={desiredParts}
          revisionTag={revision ? `r${revision.revision_id.slice(-2)}` : null}
          maturity={revision?.maturity}
          authorization={revision?.authorization}
          isMeshed={isMeshed}
          isDiverged={isDiverged}
        />

        {/* Dynamic Centre Gap / Cable */}
        <div
          className="flex-shrink-0 flex items-center justify-center transition-all duration-500 overflow-visible"
          style={{ width: gapPx }}
        >
          <Cable stage={stage} gapPx={gapPx} />
        </div>

        {/* Right Slab: Reality */}
        <Slab
          side="reality"
          eyebrow="REALITY · WHAT THE WORLD SAYS"
          slotParts={observedParts}
          effectState={observed.state}
          isMeshed={isMeshed}
          isDiverged={isDiverged}
        />
      </div>

      {/* Facts Row / Runtime Details */}
      <div className="flex flex-wrap items-center justify-between gap-2 pt-2 border-t border-ink-600/50 font-mono text-[11px]">
        <div className="flex flex-wrap items-center gap-2">
          {activeOp && (
            <Chip variant={activeOp.speculative ? 'spec' : 'active'} className="h-5 text-[10px]">
              {activeOp.tool_name}
            </Chip>
          )}

          {activeOp && activeOp.cancellation_state !== 'NONE' && (
            <Chip
              variant={activeOp.cancellation_state === 'TOO_LATE' ? 'alarm' : 'pending'}
              className="h-5 text-[10px]"
            >
              {cancellation?.label ?? activeOp.cancellation_state}
            </Chip>
          )}

          {activeDivergence && (
            <Chip variant="alarm" icon="alert" className="h-5 text-[10px]">
              DIVERGENCE: {activeDivergence.kind.replace(/_/g, ' ')}
            </Chip>
          )}
        </div>

        {/* Progressive Disclosure of Raw IDs */}
        <Details
          title="Runtime IDs"
          items={[
            { label: 'Active Revision ID', value: revision?.revision_id },
            { label: 'Fingerprint', value: revision?.dependency_fingerprint },
            { label: 'Observed Effect ID', value: observed.effectId },
            { label: 'Divergence ID', value: activeDivergence?.divergence_id },
          ]}
        />
      </div>
    </div>
  );
};
