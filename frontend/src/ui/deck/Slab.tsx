import React from 'react';
import { Eyebrow } from '../primitives/Eyebrow';
import { Chip, type SignalVariant } from '../primitives/Chip';
import type { SlotParts } from '../viewmodel/slots';

interface SlabProps {
  readonly side: 'intent' | 'reality';
  readonly eyebrow: string;
  readonly slotParts: SlotParts;
  readonly revisionTag?: string | null;
  readonly maturity?: string | null;
  readonly authorization?: string | null;
  readonly effectState?: string | null;
  readonly statusCaption?: string | null;
  readonly isMeshed?: boolean;
  readonly isDiverged?: boolean;
}

export const Slab: React.FC<SlabProps> = ({
  side,
  eyebrow,
  slotParts,
  revisionTag,
  maturity,
  authorization,
  effectState,
  statusCaption,
  isMeshed = false,
  isDiverged = false,
}) => {
  const isIntent = side === 'intent';
  const isUnknown = slotParts.unknown;
  const isCommitted = effectState === 'COMMITTED';
  const isInFlight = effectState === 'IN_FLIGHT';

  let borderColor = 'border-ink-600';
  let slabBg = 'bg-ink-850';

  if (isDiverged) {
    borderColor = 'border-sig-alarm/60';
  } else if (isMeshed || isCommitted) {
    borderColor = 'border-sig-verify/60';
  }

  return (
    <div
      className={`relative flex-1 p-5 border ${borderColor} ${slabBg} slab-shadow flex flex-col justify-between min-h-[220px] overflow-hidden select-none`}
    >
      {/* Background Animated Hatch if IN_FLIGHT */}
      {isInFlight && (
        <div
          className="absolute inset-0 pointer-events-none opacity-15"
          style={{
            backgroundImage:
              'repeating-linear-gradient(45deg, transparent, transparent 12px, rgba(76, 141, 255, 0.4) 12px, rgba(76, 141, 255, 0.4) 24px)',
            backgroundSize: '200% 200%',
            animation: 'hatchMove 2s linear infinite',
          }}
        />
      )}

      {/* Header Eyebrow */}
      <div className="flex items-center justify-between pb-2 border-b border-ink-600/60 z-10">
        <Eyebrow className="text-bone-500 font-bold tracking-widest text-[10px]">
          {eyebrow}
        </Eyebrow>
        {isIntent && revisionTag && (
          <span className="font-mono text-[10px] text-bone-500 font-bold uppercase">
            {revisionTag}
          </span>
        )}
        {!isIntent && effectState && (
          <Chip
            variant={isCommitted ? 'verify' : isInFlight ? 'active' : 'neutral'}
            className="h-5 text-[9px]"
          >
            {effectState}
          </Chip>
        )}
      </div>

      {/* Giant Numerals Display */}
      <div className="py-4 z-10 flex flex-col items-start justify-center">
        <div className="flex items-baseline gap-2">
          <span
            className={`font-display font-extrabold tabular text-[clamp(48px,5vw,96px)] leading-none ${
              isUnknown ? 'text-bone-600 tracking-wider' : 'text-bone-50'
            }`}
          >
            {slotParts.numerals}
          </span>
          {slotParts.meridiem && (
            <span className="font-display font-bold text-lg md:text-2xl text-bone-500">
              {slotParts.meridiem}
            </span>
          )}
        </div>

        {/* Date and Zone label */}
        <div className="flex items-center gap-2 mt-1 font-mono text-[11px] text-bone-500">
          {slotParts.dateLabel && <span>{slotParts.dateLabel}</span>}
          {slotParts.zone && (
            <span className="text-bone-600 border border-ink-600 px-1 text-[9px]">
              {slotParts.zone}
            </span>
          )}
        </div>
      </div>

      {/* Status Footer / Tags */}
      <div className="pt-2 border-t border-ink-600/40 flex flex-wrap items-center justify-between gap-2 z-10 font-mono text-[10px]">
        {isIntent ? (
          <div className="flex items-center gap-2">
            {maturity && (
              <Chip
                variant={maturity === 'COMMITTED' ? 'neutral' : 'spec'}
                dashed={maturity !== 'COMMITTED'}
                className="h-5 text-[9px]"
              >
                {maturity}
              </Chip>
            )}
            {authorization && (
              <Chip variant="neutral" className="h-5 text-[9px]">
                {authorization}
              </Chip>
            )}
          </div>
        ) : (
          <div className="text-bone-500 truncate max-w-full">
            {statusCaption ??
              (isUnknown
                ? 'NO WORLD EFFECT OBSERVED YET'
                : isInFlight
                ? 'AWAITING PROVIDER'
                : 'CONFIRMED IN EXTERNAL WORLD')}
          </div>
        )}
      </div>

      {/* Signature Edge Bump / Socket (Bauhaus mark motif) */}
      {isIntent && (
        <div
          className={`absolute right-0 top-1/2 -translate-y-1/2 translate-x-1/2 w-6 h-6 rounded-full border-2 ${borderColor} bg-ink-850 z-20`}
          title="Interlock Bump"
        />
      )}
      {!isIntent && (
        <div
          className={`absolute left-0 top-1/2 -translate-y-1/2 -translate-x-1/2 w-6 h-6 rounded-full border-2 ${borderColor} bg-ink-950 z-20`}
          title="Interlock Socket"
        />
      )}
    </div>
  );
};
