import React, { useMemo, useState } from 'react';
import { Eyebrow } from '../primitives/Eyebrow';
import { Hairline } from '../primitives/Hairline';
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
  const [composerText, setComposerText] = useState('');

  const speechList = projection?.speech ?? [];
  const allClaims = projection?.claims ?? [];
  const allEvidence = projection?.evidence ?? [];

  // Interleave user prompts and speech chronologically by sequence
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

    // Check if there is an emitted RESULT speech after these claims
    const hasEmittedResult = speechList.some(
      (s) => s.act_type === 'RESULT' && s.state === 'EMITTED',
    );
    if (hasEmittedResult) return null;

    return revisionClaims[0] ?? null;
  }, [projection, allClaims, speechList]);

  // Barge-in active when assistant speech is queued or emitting
  const emittingSpeech = useMemo(() => {
    return speechList.find((s) => s.state === 'EMITTING' || s.state === 'QUEUED') ?? null;
  }, [speechList]);

  // Interrupt flight check for suggestions
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
      aria-label="Agent Conversation and Voice"
      className="flex flex-col h-full bg-ink-900 border border-ink-600 p-4 min-w-0"
    >
      {/* Header */}
      <div className="flex items-center justify-between pb-3">
        <div className="flex items-center gap-2">
          <Eyebrow>THE VOICE</Eyebrow>
          <span className="font-mono text-[10px] text-bone-600">
            [{transcriptItems.length} MESSAGES]
          </span>
        </div>
        <span className="font-mono text-[10px] text-bone-500 uppercase">
          STAGE: {stage}
        </span>
      </div>

      <Hairline className="mb-3" />

      {/* Transcript feed */}
      <Transcript
        items={transcriptItems}
        allClaims={allClaims}
        allEvidence={allEvidence}
        pendingClaim={pendingClaim}
        onRetryUserPrompt={(text) => onSendText(text)}
      />

      {/* Bottom docked composer area */}
      <div className="pt-3 flex-shrink-0">
        <SuggestionChips
          stage={stage}
          onSelect={(text) => setComposerText(text)}
          hasInterruptableFlight={hasInterruptableFlight}
        />

        <Composer
          disabled={actionPending || stage === 'NO_SESSION'}
          onSend={onSendText}
          canBargeIn={emittingSpeech !== null}
          onBargeIn={() => {
            if (emittingSpeech && onCancelSpeech) {
              onCancelSpeech(emittingSpeech.speech_id);
            }
          }}
          initialText={composerText}
          onTextChange={setComposerText}
        />
      </div>
    </section>
  );
};
