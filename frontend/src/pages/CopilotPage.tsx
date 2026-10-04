import React, { useState } from 'react';
import type { ProjectionStoreState } from '../state/store';
import {
  selectActiveIntent,
  selectActiveRevision,
  selectDivergences,
  selectOperations,
  selectSpeech,
} from '../state/projections';
import { RealityStrip } from '../components/RealityStrip';
import { TaskStrip } from '../components/TaskStrip';
import { ConversationFeed, type ChatMessage } from '../components/ConversationFeed';
import { Composer } from '../components/Composer';

interface CopilotPageProps {
  readonly state: ProjectionStoreState;
  readonly actionPending: boolean;
  readonly actionError: string | null;
  readonly onStartSession: () => void;
  readonly onSubmitText: (content: string) => Promise<void>;
  readonly onCancelSpeech: (speechId: string) => Promise<void>;
  readonly userPrompts: readonly { id: string; text: string; timestamp: number }[];
}

export const CopilotPage: React.FC<CopilotPageProps> = ({
  state,
  actionPending,
  actionError,
  onStartSession,
  onSubmitText,
  onCancelSpeech,
  userPrompts,
}) => {
  const [prefill, setPrefill] = useState<string | undefined>();
  const projection = state.projection;
  const intent = projection ? selectActiveIntent(projection) : null;
  const revision = projection ? selectActiveRevision(projection) : null;
  const operations = projection ? selectOperations(projection) : [];
  const speech = projection ? selectSpeech(projection) : [];
  const divergences = projection ? selectDivergences(projection) : [];
  const effects = projection?.effects ?? [];

  const hasSession = state.sessionId !== null;

  // Synthesize conversational messages from user inputs + authoritative speech projections
  const messages: ChatMessage[] = React.useMemo(() => {
    const list: ChatMessage[] = [];

    // Interleave user inputs and assistant utterances chronologically
    userPrompts.forEach((p) => {
      list.push({
        id: `user-${p.id}`,
        role: 'user',
        content: p.text,
        timestamp: p.timestamp,
      });
    });

    speech.forEach((s) => {
      if (s.rendered_text) {
        list.push({
          id: `speech-${s.speech_id}`,
          role: 'assistant',
          content: s.rendered_text,
          speechMeta: s,
        });
      }
    });

    return list;
  }, [userPrompts, speech]);

  const cancelableSpeech = speech.find(
    (s) => s.state === 'QUEUED' || s.state === 'EMITTING',
  );

  return (
    <main id="main-content" className="mx-auto flex min-h-[calc(100vh-140px)] w-full max-w-3xl flex-col px-4 pt-4">
      {/* Action / Transport Error notification */}
      {(state.error || actionError) && (
        <div className="mb-4 rounded-xl border border-rose-300 bg-rose-50/90 p-3 text-xs text-rose-800 dark:border-rose-900 dark:bg-rose-950/40 dark:text-rose-200">
          {actionError ?? state.error?.message}
        </div>
      )}

      {/* 1. Contextual Signature Elements (Visible only when session and actions exist) */}
      {hasSession && (
        <div className="space-y-1">
          {/* INTERLOCK Signature: Reality / Consistency Strip */}
          <RealityStrip
            divergences={divergences}
            intent={intent}
            revision={revision}
            effects={effects}
            operations={operations}
          />

          {/* Contextual Active Task Strip */}
          <TaskStrip
            intent={intent}
            revision={revision}
            operations={operations}
            divergences={divergences}
          />
        </div>
      )}

      {/* 2. Visual Center: Conversation Feed */}
      <div className="flex-1 pb-6">
        <ConversationFeed
          messages={messages}
          hasSession={hasSession}
          onStartSession={onStartSession}
          onSelectPrompt={(text) => setPrefill(text)}
        />
      </div>

      {/* 3. Central Interaction Composer */}
      {hasSession && (
        <Composer
          hasSession={hasSession}
          actionPending={actionPending}
          canCancelSpeech={Boolean(cancelableSpeech)}
          onCancelSpeech={() => {
            if (cancelableSpeech) void onCancelSpeech(cancelableSpeech.speech_id);
          }}
          onSubmitText={onSubmitText}
          prefillValue={prefill}
          onPrefillConsumed={() => setPrefill(undefined)}
        />
      )}
    </main>
  );
};
