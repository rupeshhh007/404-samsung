import React, { useMemo, useState } from 'react';
import { Transcript } from './Transcript';
import { Composer } from './Composer';
import { IntentRealityHero } from '../deck/IntentRealityHero';
import { CurrentActionStrip } from '../deck/CurrentActionStrip';
import { extractDesiredSlot, formatSlotParts } from '../viewmodel/slots';
import { mergeTranscript, type UserPromptEntry } from '../viewmodel/transcript';
import type { Stage } from '../viewmodel/stage';
import type { SessionProjection } from '../../api/types';

interface VoiceColumnProps {
  readonly stage: Stage;
  readonly gapPx: number;
  readonly projection: SessionProjection | null;
  readonly userPrompts: readonly UserPromptEntry[];
  readonly onSendText: (text: string) => Promise<void> | void;
  readonly onCancelSpeech?: (speechId: string) => void;
  readonly onOpenBlackBox: () => void;
  readonly actionPending?: boolean;
  readonly voiceState?: 'idle' | 'connecting' | 'listening' | 'agent_speaking' | 'muted' | 'error';
  readonly voiceError?: string | null;
  readonly onStartVoice?: () => void;
  readonly onStopVoice?: () => void;
  readonly onToggleVoiceMute?: () => void;
}

export const VoiceColumn: React.FC<VoiceColumnProps> = ({
  stage,
  gapPx,
  projection,
  userPrompts,
  onSendText,
  onCancelSpeech,
  onOpenBlackBox,
  actionPending = false,
  voiceState = 'idle',
  voiceError = null,
  onStartVoice,
  onStopVoice,
  onToggleVoiceMute,
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

  const desiredSlot = extractDesiredSlot(
    projection?.intent ?? null,
    projection?.intent?.active_revision ?? null,
  );
  const requestedTime = desiredSlot ? formatSlotParts(desiredSlot).numerals : null;
  const hasOpenDivergence = projection?.divergences.some(
    (divergence) => divergence.state === 'OPEN' || divergence.state === 'ESCALATED',
  ) ?? false;
  const supportingLine = hasOpenDivergence && requestedTime
    ? `${requestedTime} has not been confirmed.`
    : null;

  const latestVoiceTranscript = useMemo(() => {
    const transcripts = (projection?.evidence ?? []).filter(
      (item) =>
        item.source === 'AUDIO' &&
        item.kind === 'transcript' &&
        item.authority === 'AUTHORITATIVE' &&
        typeof item.content_ref === 'string' &&
        item.content_ref.trim().length > 0,
    );
    return transcripts.length > 0 ? transcripts[transcripts.length - 1]?.content_ref ?? null : null;
  }, [projection?.evidence]);

  return (
    <section aria-label="Conversation" className="editorial-console flex min-w-0 flex-1 flex-col select-text">
      <div className="flex-1">
        <Transcript
          items={transcriptItems}
          pendingClaim={hasOpenDivergence ? null : pendingClaim}
          supportingLine={supportingLine}
          interlude={(
            <IntentRealityHero stage={stage} gapPx={gapPx} projection={projection} />
          )}
          onRetryUserPrompt={(text) => onSendText(text)}
        />

        <CurrentActionStrip projection={projection} />
        <button type="button" onClick={onOpenBlackBox} className="editorial-inspect">
          Inspect what happened →
        </button>
      </div>

      <div>
        {voiceState !== 'idle' && latestVoiceTranscript ? (
          <div
            className="mb-2 flex items-baseline gap-2 px-1 text-[11px] text-stone-500 dark:text-stone-400"
            aria-live="polite"
            data-testid="voice-heard-line"
          >
            <span className="font-mono text-[9px] uppercase tracking-[0.16em] text-stone-400 dark:text-stone-500">
              Heard
            </span>
            <span className="truncate">“{latestVoiceTranscript}”</span>
          </div>
        ) : null}
        <Composer
          disabled={actionPending}
          onSend={(text) => onSendText(text)}
          canBargeIn={!!emittingSpeech}
          onBargeIn={() => {
            if (emittingSpeech && onCancelSpeech) {
              onCancelSpeech(emittingSpeech.speech_id);
            }
          }}
          voiceState={voiceState}
          voiceError={voiceError}
          onStartVoice={onStartVoice}
          onStopVoice={onStopVoice}
          onToggleVoiceMute={onToggleVoiceMute}
        />
      </div>
    </section>
  );
};
