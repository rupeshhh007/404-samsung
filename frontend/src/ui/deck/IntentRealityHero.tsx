import React, { useState, useMemo } from 'react';
import { Cable } from './Cable';
import {
  formatSlotParts,
  extractDesiredSlot,
  selectObservedWorld,
  selectActiveOperation,
  matchSlots,
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

  // Pure semantic selectors
  const observed = useMemo(() => selectObservedWorld(projection), [projection]);
  const activeDivergence = observed.divergence;
  const activeOp = useMemo(() => selectActiveOperation(projection), [projection]);

  // Extract desired & observed slots cleanly using pure viewmodels
  const rawDesired = useMemo(() => extractDesiredSlot(intent, revision), [intent, revision]);
  const desiredParts = useMemo(() => formatSlotParts(rawDesired), [rawDesired]);
  const observedParts = useMemo(() => formatSlotParts(observed.rawSlot), [observed.rawSlot]);

  const hasObservedSlot = observed.slot !== null && !observedParts.unknown;
  const isDiverged =
    stage === 'DIVERGED' ||
    activeDivergence?.state === 'OPEN' ||
    activeDivergence?.state === 'ESCALATED';
  const isAligned =
    stage === 'ALIGNED' ||
    stage === 'RESOLVED' ||
    (observed.state === 'COMMITTED' &&
      hasObservedSlot &&
      rawDesired !== null &&
      observed.rawSlot !== null &&
      matchSlots(observed.rawSlot, rawDesired));
  const isOutcomeUnknown = stage === 'UNKNOWN' || observed.state === 'OUTCOME_UNKNOWN';
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
              <span className="font-display font-extrabold text-[clamp(28px,3.5vw,56px)] text-bone-50 leading-none tabular tracking-tight">
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
          <div className="flex items-center justify-between">
            <span className="font-mono text-[11px] uppercase tracking-wider text-bone-500 font-semibold">
              REALITY
            </span>
            {hasObservedSlot && observed.state ? (
              <span
                className={`font-mono text-[10px] px-1.5 py-0.5 border ${
                  observed.state === 'COMMITTED'
                    ? 'border-sig-verify/60 text-sig-verify bg-sig-verify/10'
                    : 'border-ink-600 text-bone-400 bg-ink-900'
                }`}
              >
                {observed.state === 'COMMITTED' ? 'COMMITTED' : observed.state}
              </span>
            ) : (
              <span className="font-mono text-[10px] px-1.5 py-0.5 border border-ink-700 text-bone-500 bg-ink-900/50">
                NOT OBSERVED
              </span>
            )}
          </div>

          <div className="my-auto py-2">
            <div className="flex items-baseline gap-1.5">
              <span
                className={`font-display font-extrabold text-[clamp(28px,3.5vw,56px)] leading-none tabular tracking-tight ${
                  !hasObservedSlot ? 'text-bone-600' : 'text-bone-50'
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
            {!hasObservedSlot
              ? 'No External Effect'
              : observed.state === 'COMMITTED'
              ? 'Confirmed External Booking'
              : `External State: ${observed.state}`}
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
              {hasObservedSlot && desiredParts.formatted !== '—'
                ? `Divergence detected — external ${observedParts.formatted} ≠ desired ${desiredParts.formatted}`
                : isTooLate
                ? 'Cancellation was too late.'
                : 'Reality does not match your latest request.'}
            </div>
          </div>
        ) : isOutcomeUnknown ? (
          <div className="font-sans text-xs text-sig-pending flex items-center gap-1.5">
            <span className="w-2 h-2 rounded-full border border-sig-pending animate-pulse" />
            <span>Verification in progress</span>
          </div>
        ) : !hasObservedSlot ? (
          <div className="font-sans text-xs text-bone-400 flex items-center gap-1.5">
            <span className="w-2 h-2 rounded-full border border-bone-500 animate-pulse" />
            <span>No external observation recorded</span>
          </div>
        ) : !isAligned ? (
          <div className="font-sans text-xs text-sig-pending flex items-center gap-1.5">
            <span className="w-2 h-2 rounded-full bg-sig-pending" />
            <span>
              {`External booking confirmed at ${observedParts.formatted}; desired ${desiredParts.formatted} unverified`}
            </span>
          </div>
        ) : (
          <div className="font-sans text-xs text-sig-verify flex items-center gap-1.5">
            <span className="w-2 h-2 rounded-full bg-sig-verify" />
            <span>In sync — verified booking at {observedParts.formatted}</span>
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
            <span className="text-bone-200">{observed.rawSlot ?? '—'}</span>
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
