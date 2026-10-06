import React from 'react';
import { motion } from 'motion/react';
import { Chip } from '../primitives/Chip';
import { CopyButton } from '../primitives/CopyButton';
import { shortenId } from '../../utils/formatters';
import type { SpeechProofViewModel } from '../viewmodel/proof';

interface ReceiptProps {
  readonly proof: SpeechProofViewModel;
  readonly onClose: () => void;
}

export const Receipt: React.FC<ReceiptProps> = ({ proof, onClose }) => {
  const isApproved = proof.state === 'APPROVED' || proof.state === 'EMITTED' || proof.state === 'EMITTING';
  const isCancelled = proof.state === 'CANCELLED';
  const isBlocked = proof.state === 'BLOCKED';
  const isCorrectionRequired = proof.state === 'CORRECTION_REQUIRED';

  let stampText = 'APPROVED';
  let stampColor = 'text-sig-verify border-sig-verify';

  if (isCorrectionRequired) {
    stampText = 'INVALIDATED / CORRECTION REQUIRED';
    stampColor = 'text-sig-alarm border-sig-alarm';
  } else if (isCancelled) {
    stampText = 'CANCELLED';
    stampColor = 'text-sig-pending border-sig-pending';
  } else if (isBlocked) {
    stampText = 'BLOCKED';
    stampColor = 'text-sig-alarm border-sig-alarm';
  }

  return (
    <motion.div
      initial={{ height: 0, opacity: 0 }}
      animate={{ height: 'auto', opacity: 1 }}
      exit={{ height: 0, opacity: 0 }}
      transition={{ duration: 0.28, ease: [0.22, 1, 0.36, 1] }}
      className="overflow-hidden mt-3 mb-2"
    >
      <div
        className="relative p-5 bg-[#ECE6DA] text-[#1A1714] font-mono text-[11px] leading-relaxed border border-[#C8C0B2] shadow-md transform rotate-[0.3deg] max-w-xl select-text"
        style={{
          boxShadow: '4px 6px 0px rgba(0,0,0,0.4)',
        }}
      >
        {/* Physical Stamp Animation */}
        <motion.div
          initial={{ scale: 1.6, opacity: 0, rotate: -8 }}
          animate={{ scale: 1, opacity: 0.85, rotate: -8 }}
          transition={{ duration: 0.18, ease: 'easeOut' }}
          className={`absolute top-4 right-5 border-2 border-dashed px-2.5 py-1 font-mono font-extrabold text-[11px] sm:text-xs uppercase tracking-wider pointer-events-none mix-blend-multiply ${stampColor}`}
        >
          {stampText}
        </motion.div>

        {/* Header */}
        <div className="border-b border-[#D0C8B8] pb-2 mb-3 pr-24">
          <div className="font-bold tracking-widest uppercase text-xs">
            TRUTHLOCK AUDIT PROOF // RECEIPT
          </div>
          <div className="text-[10px] text-[#5A544A] mt-0.5">
            SPEECH ID: {shortenId(proof.speechId, 8, 6)}
          </div>
        </div>

        {/* Core Metadata */}
        <div className="grid grid-cols-2 gap-2 pb-3 mb-3 border-b border-[#D0C8B8] text-[10px]">
          <div>
            <span className="text-[#6A645A] uppercase block">ACT TYPE / STATE</span>
            <span className="font-bold">{proof.actType} / {proof.state}</span>
          </div>
          <div>
            <span className="text-[#6A645A] uppercase block">APPROVED THROUGH</span>
            <span className="font-bold">
              {proof.approvedThroughSequence !== null ? `#${proof.approvedThroughSequence}` : '—'}
            </span>
          </div>
          <div>
            <span className="text-[#6A645A] uppercase block">POLICY ID</span>
            <span>{proof.approvedPolicyId ?? 'default'}</span>
          </div>
          <div>
            <span className="text-[#6A645A] uppercase block">SUPERSEDES</span>
            <span>{proof.supersedesSpeechId ? shortenId(proof.supersedesSpeechId, 6, 4) : 'none'}</span>
          </div>
        </div>

        {/* Supporting Claims */}
        <div className="space-y-2 mb-3">
          <div className="text-[10px] font-bold uppercase tracking-wider text-[#5A544A]">
            Claims Verified ({proof.claims.length})
          </div>
          {proof.claims.length === 0 ? (
            <div className="italic text-[#7A746A]">No claims attached</div>
          ) : (
            proof.claims.map((c) => (
              <div
                key={c.claimId}
                className="p-2 bg-[#E2DBD0] border border-[#D5CDC0] space-y-1"
              >
                <div className="flex items-center justify-between gap-1">
                  <span className="font-bold truncate">{c.predicate}</span>
                  <Chip variant={c.state === 'CONFIRMED' ? 'verify' : 'pending'} className="h-5 text-[9px]">
                    {c.state}
                  </Chip>
                </div>
                {c.evidenceRule && (
                  <div className="text-[10px] text-[#6A645A]">
                    Rule: {c.evidenceRule}
                  </div>
                )}
              </div>
            ))
          )}
        </div>

        {/* Supporting Evidence */}
        <div className="space-y-2">
          <div className="text-[10px] font-bold uppercase tracking-wider text-[#5A544A]">
            Supporting Evidence ({proof.evidence.length})
          </div>
          {proof.evidence.length === 0 ? (
            <div className="italic text-[#7A746A]">No evidence attached</div>
          ) : (
            proof.evidence.map((ev) => (
              <div
                key={ev.evidenceId}
                className="p-2 bg-[#E2DBD0] border border-[#D5CDC0] text-[10px] flex items-center justify-between"
              >
                <div>
                  <span className="font-bold uppercase mr-2">{ev.source}</span>
                  <span className="text-[#6A645A]">{ev.kind}</span>
                </div>
                <div className="text-[#7A746A]">
                  {shortenId(ev.evidenceId, 6, 4)}
                </div>
              </div>
            ))
          )}
        </div>

        {/* Dismiss footer */}
        <div className="mt-4 pt-2 border-t border-[#D0C8B8] flex justify-end">
          <button
            type="button"
            onClick={onClose}
            className="font-mono text-[10px] uppercase font-bold text-[#1A1714] hover:underline px-2 py-0.5"
          >
            [CLOSE PROOF RECEIPT]
          </button>
        </div>
      </div>
    </motion.div>
  );
};
