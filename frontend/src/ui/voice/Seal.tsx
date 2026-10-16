import React from 'react';
import { Icon, type IconName } from '../primitives/Icon';
import { Chip, type SignalVariant } from '../primitives/Chip';
import type { SpeechProjection } from '../../api/types';

interface SealProps {
  readonly speech: SpeechProjection;
  readonly receiptOpen: boolean;
  readonly onToggleReceipt: () => void;
}

export const Seal: React.FC<SealProps> = ({
  speech,
  receiptOpen,
  onToggleReceipt,
}) => {
  const isCancelled = speech.state === 'CANCELLED' || speech.cancellation_pending;
  const isBlocked = speech.state === 'BLOCKED';
  const isCorrection = speech.state === 'CORRECTION_REQUIRED' || speech.correction_pending;

  let sealVariant: SignalVariant = 'verify';
  let sealIcon: IconName = 'seal';

  switch (speech.act_type) {
    case 'UNCERTAINTY':
      sealVariant = 'pending';
      sealIcon = 'alert';
      break;
    case 'DIVERGENCE':
    case 'CORRECTION':
      sealVariant = 'alarm';
      sealIcon = 'alert';
      break;
    case 'PROGRESS':
      sealVariant = 'active';
      sealIcon = 'seal';
      break;
    case 'CLARIFICATION':
      sealVariant = 'neutral';
      sealIcon = 'seal';
      break;
    case 'RESULT':
    default:
      if (speech.requested_certainty === 'CONFIRMED') {
        sealVariant = 'verify';
        sealIcon = 'seal';
      } else {
        sealVariant = 'pending';
        sealIcon = 'alert';
      }
      break;
  }

  // Authoritative seal label (§6.4.3)
  let sealLabel = `TRUTHLOCK APPROVED · ${speech.act_type} · ${speech.requested_certainty}`;
  if (isCancelled) {
    sealLabel = speech.cancellation_pending || speech.state === 'CANCELLED'
      ? (speech.heard ? 'CANCELLED DURING EMISSION' : 'CANCELLED BEFORE EMISSION')
      : 'CANCELLED BEFORE EMISSION';
  } else if (isBlocked) {
    sealLabel = 'BLOCKED BY TRUTHLOCK';
  } else if (isCorrection) {
    sealLabel = 'CORRECTION REQUIRED';
  }

  // Delivery status chip
  let deliveryLabel = 'DELIVERY NOT REPORTED';
  let deliveryVariant: SignalVariant = 'neutral';
  if (speech.heard === true) {
    deliveryLabel = 'HEARD';
    deliveryVariant = 'verify';
  } else if (speech.heard === false) {
    deliveryLabel = 'CONSOLE TEXT · NOT HEARD';
    deliveryVariant = 'pending';
  }

  return (
    <div className="space-y-1.5 pt-2">
      {/* Correction Warning Banner */}
      {isCorrection && (
        <div className="flex items-center gap-2 p-2 bg-sig-alarm/10 border border-sig-alarm/40 text-sig-alarm font-mono text-[11px]">
          <Icon name="alert" size={14} />
          <span>CORRECTION REQUIRED — this statement may no longer be true</span>
        </div>
      )}

      {/* Main Seal Row */}
      <div className="flex flex-wrap items-center gap-2 font-mono text-[11px] select-none">
        <Chip variant={sealVariant} icon={sealIcon}>
          {sealLabel}
        </Chip>

        <Chip variant={deliveryVariant}>
          {deliveryLabel}
        </Chip>

        {/* Proof Toggle Button */}
        <button
          type="button"
          onClick={onToggleReceipt}
          aria-expanded={receiptOpen}
          aria-label="Toggle truthlock proof receipt"
          className="inline-flex items-center gap-1 px-2 h-6 border border-ink-600 bg-ink-850 hover:bg-ink-800 text-bone-300 hover:text-bone-50 transition-colors uppercase text-[10px] focus-visible:outline-sig-active"
        >
          <Icon name="stamp" size={11} />
          <span>{receiptOpen ? 'Hide Proof' : 'Proof'}</span>
        </button>
      </div>
    </div>
  );
};
