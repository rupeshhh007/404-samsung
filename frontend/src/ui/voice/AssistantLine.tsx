import React from 'react';
import type { SpeechProjection, ClaimProjection, EvidenceProjection } from '../../api/types';

interface AssistantLineProps {
  readonly speech: SpeechProjection;
  readonly allClaims?: readonly ClaimProjection[];
  readonly allEvidence?: readonly EvidenceProjection[];
  readonly isNewest?: boolean;
  readonly supportingLine?: string | null;
}

export const AssistantLine: React.FC<AssistantLineProps> = ({
  speech,
  supportingLine,
}) => {
  const isCancelled = speech.state === 'CANCELLED' || speech.cancellation_pending;
  const isBlocked = speech.state === 'BLOCKED';
  const isCorrection = speech.state === 'CORRECTION_REQUIRED' || speech.correction_pending;
  const isUncertain = speech.act_type === 'UNCERTAINTY' || speech.requested_certainty !== 'CONFIRMED';
  const isEmitting = speech.state === 'EMITTING' || speech.state === 'QUEUED';
  const text = speech.rendered_text ?? '';

  return (
    <div
      className="editorial-assistant flex flex-col"
      aria-label={text ? `INTERLOCK: ${text}` : 'INTERLOCK statement'}
    >
      {/* Speaker Tag */}
      <div className="editorial-kicker mb-3 flex items-center justify-between">
        <span>TRUTHLOCK response</span>
        {speech.approved_through_sequence !== null && (
          <span className="opacity-60">#{speech.approved_through_sequence}</span>
        )}
      </div>

      {/* Spoken Text (Rendered Verbatim) */}
      {isBlocked ? (
        <div className="editorial-assistant-text">
          ✕ Blocked by TRUTHLOCK — unconfirmed evidence
        </div>
      ) : (
        <div
          className={`editorial-assistant-text break-words ${
            isCancelled ? 'line-through opacity-50' : ''
          }`}
        >
          {text}
        </div>
      )}

      {!isBlocked && supportingLine && (
        <div className="editorial-assistant-support">{supportingLine}</div>
      )}

      {/* Subtle Truthlock Verification Line */}
      <div className="editorial-truthlock">
        {isBlocked ? null : isCancelled ? (
          <span>Cancelled mid-speech</span>
        ) : isCorrection ? (
          <span>TRUTHLOCK · Correction required</span>
        ) : isUncertain ? (
          <span>TRUTHLOCK · Evidence incomplete</span>
        ) : isEmitting ? (
          <span>TRUTHLOCK · Playing...</span>
        ) : speech.heard === false ? (
          <span>TRUTHLOCK · Not heard</span>
        ) : (
          <span>TRUTHLOCK · Verified</span>
        )}
      </div>
    </div>
  );
};
