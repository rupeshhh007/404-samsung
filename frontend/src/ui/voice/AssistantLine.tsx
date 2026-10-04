import React, { useState } from 'react';
import { motion } from 'motion/react';
import type { SpeechProjection, ClaimProjection, EvidenceProjection } from '../../api/types';

interface AssistantLineProps {
  readonly speech: SpeechProjection;
  readonly allClaims?: readonly ClaimProjection[];
  readonly allEvidence?: readonly EvidenceProjection[];
  readonly isNewest?: boolean;
}

export const AssistantLine: React.FC<AssistantLineProps> = ({
  speech,
}) => {
  const [showDetails, setShowDetails] = useState(false);

  const isCancelled = speech.state === 'CANCELLED';
  const isBlocked = speech.state === 'BLOCKED';
  const isUncertain = speech.act_type === 'UNCERTAINTY' || speech.requested_certainty !== 'CONFIRMED';
  const text = speech.rendered_text ?? '';

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.2, ease: 'easeOut' }}
      className="flex flex-col py-3.5 border-b border-ink-800/60 text-bone-50 group"
      aria-label={text ? `INTERLOCK: ${text}` : 'INTERLOCK statement'}
    >
      {/* Speaker Tag */}
      <div className="flex items-center justify-between pb-1 text-[11px] font-mono text-bone-500">
        <span className="font-semibold text-bone-400">INTERLOCK</span>
        {speech.approved_through_sequence !== null && (
          <span className="text-[10px] text-bone-600">#{speech.approved_through_sequence}</span>
        )}
      </div>

      {/* Spoken Text (Rendered Verbatim) */}
      {isBlocked ? (
        <div className="py-2 text-xs text-sig-alarm font-mono">
          ✕ Blocked by TRUTHLOCK — unconfirmed evidence
        </div>
      ) : (
        <div
          className={`font-voice italic text-[clamp(18px,1.5vw,26px)] leading-[1.3] text-bone-50 break-words ${
            isCancelled ? 'line-through opacity-50' : ''
          }`}
        >
          {text}
        </div>
      )}

      {/* Subtle Truthlock Verification Line */}
      <div className="flex items-center justify-between pt-2 text-xs">
        {isBlocked ? null : isCancelled ? (
          <span className="font-sans text-bone-500 text-[11px]">
            — Cancelled mid-speech
          </span>
        ) : isUncertain ? (
          <span className="font-sans text-sig-pending flex items-center gap-1.5 text-[12px]">
            <span className="w-1.5 h-1.5 rounded-full bg-sig-pending" />
            Evidence still incomplete
          </span>
        ) : (
          <span className="font-sans text-sig-verify flex items-center gap-1.5 text-[12px]">
            <span>✓</span>
            Verified by TRUTHLOCK
          </span>
        )}

        {/* Small subtle Details link */}
        <button
          type="button"
          onClick={() => setShowDetails((prev) => !prev)}
          className="font-mono text-[10px] text-bone-500 hover:text-bone-300 underline-offset-2 hover:underline focus-visible:outline-sig-active"
        >
          {showDetails ? 'Hide' : 'Details'}
        </button>
      </div>

      {/* Expandable Subtle Technical Proof */}
      {showDetails && (
        <div className="mt-2.5 p-2.5 bg-ink-900 border border-ink-700/60 font-mono text-[10px] text-bone-400 space-y-1">
          <div className="flex justify-between">
            <span className="text-bone-500">Act Type:</span>
            <span className="text-bone-200">{speech.act_type}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-bone-500">Certainty:</span>
            <span className="text-bone-200">{speech.requested_certainty}</span>
          </div>
          {speech.speech_id && (
            <div className="flex justify-between">
              <span className="text-bone-500">Speech ID:</span>
              <span className="text-bone-300">{speech.speech_id.slice(0, 12)}…</span>
            </div>
          )}
        </div>
      )}
    </motion.div>
  );
};
