import React, { useMemo, useState } from 'react';
import { Transcript } from './Transcript';
import { SuggestionChips } from './SuggestionChips';
import { Composer } from './Composer';
import { mergeTranscript, type UserPromptEntry } from '../viewmodel/transcript';
import type { Stage } from '../viewmodel/stage';
import type { SessionProjection, OperationProjection } from '../../api/types';

interface VoiceColumnProps {
  readonly stage: Stage;
  readonly projection: SessionProjection | null;
  readonly userPrompts: readonly UserPromptEntry[];
  readonly onSendText: (text: string) => Promise<void> | void;
  readonly onCancelSpeech?: (speechId: string) => void;
  readonly actionPending?: boolean;
}

export const VoiceColumn: React.FC<VoiceColumnProps> = ({
  stage,
  projection,
  userPrompts,
  onSendText,
  onCancelSpeech,
  actionPending = false,
}) => {
  const speechList = projection?.speech ?? [];
  const allClaims = projection?.claims ?? [];

  // Interleave user prompts and speech chronologically
  const transcriptItems = useMemo(() => {
    return mergeTranscript(userPrompts, speechList);
  }, [userPrompts, speechList]);

  // Determine if active intent revision has pending claim with no following RESULT speech
  const pendingClaim = useMemo(() => {
    if (!projection?.intent?.active_revision) return null;
    const revId = projection.intent.active_revision.revision_id;
    const revisionClaims = allClaims.filter(
      (c) =>
        c.intent_revision_id === revId &&
        (c.state === 'PENDING' || c.state === 'PROPOSED' || c.state === 'UNCERTAIN'),
    );
    if (revisionClaims.length === 0) return null;

    const targetClaim = revisionClaims[0];
    if (!targetClaim) return null;

    // Only suppress pending claim if an emitted RESULT references that exact claim or current revision
    const hasEmittedResult = speechList.some(
      (s) =>
        s.act_type === 'RESULT' &&
        (s.state === 'EMITTED' || s.state === 'APPROVED' || s.state === 'QUEUED' || s.state === 'EMITTING') &&
        (s.claim_ids.includes(targetClaim.claim_id) ||
          allClaims.some((c) => c.intent_revision_id === revId && s.claim_ids.includes(c.claim_id))),
    );
    if (hasEmittedResult) return null;

    return targetClaim;
  }, [projection, allClaims, speechList]);

  // Barge-in active when assistant speech is emitting
  const emittingSpeech = useMemo(() => {
    return speechList.find((s) => s.state === 'EMITTING' || s.state === 'QUEUED') ?? null;
  }, [speechList]);

  // Interrupt flight check for quick suggestion prompt
  const hasInterruptableFlight = useMemo(() => {
    const ops = projection?.operations ?? [];
    return ops.some(
      (op: OperationProjection) =>
        !op.speculative &&
        (op.state === 'DISPATCHED' || op.state === 'WAITING'),
    );
  }, [projection]);

  return (
    <section
      aria-label="Conversation"
      className="flex flex-col h-full bg-ink-950/70 p-4 sm:p-6 min-w-0 select-text"
    >
      {/* Transcript feed */}
      <Transcript
        items={transcriptItems}
        pendingClaim={pendingClaim}
        onRetryUserPrompt={(text) => onSendText(text)}
      />

      {/* Suggested Quick Prompts */}
      <div className="pt-2">
        <SuggestionChips
          stage={stage}
          hasInterruptableFlight={hasInterruptableFlight}
          onSelect={(text) => onSendText(text)}
        />
      </div>

      {/* Input Composer */}
      <div className="pt-2">
        <Composer
          disabled={actionPending}
          onSend={(text) => onSendText(text)}
          canBargeIn={!!emittingSpeech}
          onBargeIn={() => {
            if (emittingSpeech && onCancelSpeech) {
              onCancelSpeech(emittingSpeech.speech_id);
            }
          }}
        />
      </div>
    </section>
  );
};
