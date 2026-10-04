import React, { useState, useMemo } from 'react';
import { Cable } from './Cable';
import {
  formatSlotParts,
  extractDesiredSlot,
  extractObservedSlot,
} from '../viewmodel/slots';
import type { Stage } from '../viewmodel/stage';
import type { SessionProjection } from '../../api/types';

interface IntentRealityHeroProps {
  readonly stage: Stage;
  readonly gapPx: number;
  readonly projection: SessionProjection | null;
  readonly onOpenBlackBox?: () => void;
}

export const IntentRealityHero: React.FC<IntentRealityHeroProps> = ({
  stage,
  gapPx,
  projection,
  onOpenBlackBox,
}) => {
  const [showDetails, setShowDetails] = useState(false);

  const intent = projection?.intent ?? null;
  const revision = intent?.active_revision ?? null;
  const effects = projection?.effects ?? [];
  const divergences = projection?.divergences ?? [];
  const operations = projection?.operations ?? [];

  const activeDivergence = useMemo(() => {
    return (
      divergences.find((d) => d.state === 'OPEN' || d.state === 'ESCALATED') ??
      divergences.find((d) => d.state === 'RECONCILING' || d.state === 'PLANNED') ??
      divergences[divergences.length - 1] ??
      null
    );
  }, [divergences]);

  const activeOp = operations[operations.length - 1] ?? null;

  // Extract desired & observed slots cleanly using pure viewmodels
  const rawDesired = useMemo(() => extractDesiredSlot(intent, revision), [intent, revision]);
  const desiredParts = useMemo(() => formatSlotParts(rawDesired), [rawDesired]);

  const rawObserved = useMemo(
    () => extractObservedSlot(activeDivergence, effects),
    [activeDivergence, effects],
  );
  const observedParts = useMemo(() => formatSlotParts(rawObserved), [rawObserved]);

  const isDiverged = stage === 'DIVERGED' || activeDivergence?.state === 'OPEN' || activeDivergence?.state === 'ESCALATED';
  const isAligned = stage === 'ALIGNED' || stage === 'RESOLVED' || (rawDesired && rawObserved && rawDesired === rawObserved);
  const isUnknown = !rawObserved || observedParts.unknown;

  const isTooLate = activeOp?.cancellation_state === 'TOO_LATE';

  return (
    <div className="flex flex-col bg-ink-900 border border-ink-700/80 p-5 sm:p-6 select-none space-y-4">
      {/* Slabs Comparison */}
      <div className="relative flex items-center justify-between gap-3 min-h-[170px]">
        {/* Left Slab: INTENT */}
        <div
          className={`flex-1 p-5 border ${
            isDiverged ? 'border-sig-alarm/50 bg-ink-950/90' : 'border-ink-700 bg-ink-950/70'
          } flex flex-col justify-between min-h-[170px] relative`}
        >
          <span className="font-mono text-[11px] uppercase tracking-wider text-bone-500 font-semibold">
            INTENT
          </span>

          <div className="my-auto py-2">
            <div className="flex items-baseline gap-1.5">
              <span className="font-display font-extrabold text-[clamp(36px,4vw,64px)] text-bone-50 leading-none tabular">
                {desiredParts.numerals}
              </span>
              {desiredParts.meridiem && (
                <span className="font-display font-bold text-lg text-bone-500">
                  {desiredParts.meridiem}
                </span>
              )}
            </div>
            {desiredParts.dateLabel && (
              <span className="font-mono text-[11px] text-bone-500 mt-1 block">
                {desiredParts.dateLabel}
              </span>
            )}
          </div>

          <span className="font-mono text-[10px] text-bone-600">
            {revision ? 'Latest User Request' : 'No Request'}
          </span>

          {/* Bauhaus edge bump */}
          <div
            className={`hidden sm:block absolute right-0 top-1/2 -translate-y-1/2 translate-x-1/2 w-4 h-4 rounded-full border ${
              isDiverged ? 'border-sig-alarm bg-ink-950' : 'border-ink-700 bg-ink-900'
            } z-10`}
          />
        </div>

        {/* Central Gap & Physics Cable */}
        <div
          className="flex-shrink-0 flex items-center justify-center overflow-visible"
          style={{ width: Math.max(32, gapPx) }}
        >
          <Cable stage={stage} gapPx={gapPx} />
        </div>

        {/* Right Slab: REALITY */}
        <div
          className={`flex-1 p-5 border ${
            isDiverged
              ? 'border-sig-alarm/50 bg-ink-950/90'
              : isAligned
              ? 'border-sig-verify/50 bg-ink-950/70'
              : 'border-ink-700 bg-ink-950/70'
          } flex flex-col justify-between min-h-[170px] relative`}
        >
          <span className="font-mono text-[11px] uppercase tracking-wider text-bone-500 font-semibold">
            REALITY
          </span>

          <div className="my-auto py-2">
            <div className="flex items-baseline gap-1.5">
              <span
                className={`font-display font-extrabold text-[clamp(36px,4vw,64px)] leading-none tabular ${
                  isUnknown ? 'text-bone-600' : 'text-bone-50'
                }`}
              >
                {observedParts.numerals}
              </span>
              {observedParts.meridiem && (
                <span className="font-display font-bold text-lg text-bone-500">
                  {observedParts.meridiem}
                </span>
              )}
            </div>
            {observedParts.dateLabel && (
              <span className="font-mono text-[11px] text-bone-500 mt-1 block">
                {observedParts.dateLabel}
              </span>
            )}
          </div>

          <span className="font-mono text-[10px] text-bone-600">
            {isUnknown ? 'External State' : 'Confirmed Booking'}
          </span>

          {/* Bauhaus edge socket */}
          <div
            className={`hidden sm:block absolute left-0 top-1/2 -translate-y-1/2 -translate-x-1/2 w-4 h-4 rounded-full border ${
              isDiverged ? 'border-sig-alarm bg-ink-950' : 'border-ink-700 bg-ink-900'
            } z-10`}
          />
        </div>
      </div>

      {/* Primary Semantic Status Banner */}
      <div className="pt-2 border-t border-ink-800/80 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3">
        {isDiverged ? (
          <div className="space-y-0.5">
            <div className="font-display font-extrabold text-sm sm:text-base tracking-wide text-sig-alarm uppercase flex items-center gap-2">
              <span>≠ REALITY MISMATCH</span>
            </div>
            <div className="font-sans text-xs text-bone-300">
              {isTooLate ? 'Cancellation was too late.' : 'Reality does not match your latest request.'}
            </div>
          </div>
        ) : isUnknown ? (
          <div className="font-sans text-xs text-bone-400 flex items-center gap-1.5">
            <span className="w-2 h-2 rounded-full border border-bone-500 animate-pulse" />
            <span>Waiting for external confirmation</span>
          </div>
        ) : (
          <div className="font-sans text-xs text-sig-verify flex items-center gap-1.5">
            <span className="w-2 h-2 rounded-full bg-sig-verify" />
            <span>In sync</span>
          </div>
        )}

        {/* Small Controls */}
        <div className="flex items-center gap-3 self-end sm:self-auto font-mono text-xs">
          <button
            type="button"
            onClick={() => setShowDetails((p) => !p)}
            className="px-2 py-1 bg-ink-800 hover:bg-ink-700 border border-ink-700 text-bone-300 text-[11px] focus-visible:outline-sig-active"
          >
            {showDetails ? 'Hide Details' : 'Details'}
          </button>

          {onOpenBlackBox && (
            <button
              type="button"
              onClick={onOpenBlackBox}
              className="text-bone-400 hover:text-bone-100 text-[11px] flex items-center gap-1 underline-offset-2 hover:underline"
            >
              Black Box ↗
            </button>
          )}
        </div>
      </div>

      {/* Collapsible Technical Details (Clean metadata, no noisy hashes) */}
      {showDetails && (
        <div className="p-3 bg-ink-950 border border-ink-800 font-mono text-[11px] space-y-1 text-bone-400 animate-fadeIn">
          <div className="flex justify-between">
            <span className="text-bone-500">Desired Slot:</span>
            <span className="text-bone-200">{rawDesired ?? '—'}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-bone-500">Observed Slot:</span>
            <span className="text-bone-200">{rawObserved ?? '—'}</span>
          </div>
          {activeOp && (
            <div className="flex justify-between">
              <span className="text-bone-500">Operation State:</span>
              <span className="text-bone-200">{activeOp.state}</span>
            </div>
          )}
          {activeOp && activeOp.cancellation_state !== 'NONE' && (
            <div className="flex justify-between">
              <span className="text-bone-500">Cancellation:</span>
              <span className="text-bone-200">{activeOp.cancellation_state}</span>
            </div>
          )}
          {activeDivergence && (
            <div className="flex justify-between text-sig-alarm">
              <span>Divergence Kind:</span>
              <span>{activeDivergence.kind}</span>
            </div>
          )}
        </div>
      )}
    </div>
  );
};
