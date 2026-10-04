import React, { useState, useMemo } from 'react';
import { motion } from 'motion/react';
import { Seal } from './Seal';
import { Receipt } from './Receipt';
import { buildSpeechProof } from '../viewmodel/proof';
import type { SpeechProjection, ClaimProjection, EvidenceProjection } from '../../api/types';

interface AssistantLineProps {
  readonly speech: SpeechProjection;
  readonly allClaims: readonly ClaimProjection[];
  readonly allEvidence: readonly EvidenceProjection[];
  readonly isNewest?: boolean;
}

export const AssistantLine: React.FC<AssistantLineProps> = ({
  speech,
  allClaims,
  allEvidence,
}) => {
  const [receiptOpen, setReceiptOpen] = useState(false);

  const proof = useMemo(() => {
    return buildSpeechProof(speech, allClaims, allEvidence);
  }, [speech, allClaims, allEvidence]);

  const isCancelled = speech.state === 'CANCELLED';
  const isBlocked = speech.state === 'BLOCKED';
  const text = speech.rendered_text ?? '';

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.28, ease: [0.22, 1, 0.36, 1] }}
      className="flex gap-4 py-4 border-b border-ink-600/40 text-bone-50 group"
      aria-label={text ? `Assistant: ${text}` : 'Assistant statement'}
    >
      {/* 72px Left Gutter */}
      <div className="w-[72px] flex-shrink-0 flex flex-col items-start font-mono text-[11px] pt-1.5 select-none">
        <span className="text-sig-verify font-bold tracking-wider">IL</span>
        <span className="text-bone-600 text-[10px]">
          {speech.approved_through_sequence !== null
            ? `#${speech.approved_through_sequence}`
            : '—'}
        </span>
      </div>

      {/* Spoken Content & Seal */}
      <div className="flex-1 min-w-0 space-y-2">
        {isBlocked ? (
          /* Redaction line for blocked speech */
          <div className="p-3 bg-sig-alarm/10 border border-sig-alarm/30 font-mono text-xs text-sig-alarm flex items-center gap-2">
            <span className="w-2.5 h-2.5 rounded-full bg-sig-alarm animate-pulse" />
            <span>BLOCKED BY TRUTHLOCK — STATEMENT REDACTED (UNCONFIRMED EVIDENCE)</span>
          </div>
        ) : (
          /* Voice Italic Spoken Sentence (Rendered Verbatim) */
          <div
            className={`font-voice italic text-[clamp(22px,1.8vw,32px)] leading-[1.25] text-bone-50 break-words ${
              isCancelled ? 'line-through opacity-55' : ''
            }`}
          >
            {text}
          </div>
        )}

        {/* Seal Row */}
        <Seal
          speech={speech}
          receiptOpen={receiptOpen}
          onToggleReceipt={() => setReceiptOpen((prev) => !prev)}
        />

        {/* Paper Receipt Proof */}
        {receiptOpen && (
          <Receipt proof={proof} onClose={() => setReceiptOpen(false)} />
        )}
      </div>
    </motion.div>
  );
};
