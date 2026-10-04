import React from 'react';
import type { SpeechProjection } from '../api/types';
import { Icons } from './Icons';
import { TechnicalDetails } from './TechnicalDetails';

export interface ChatMessage {
  readonly id: string;
  readonly role: 'user' | 'assistant';
  readonly content: string;
  readonly timestamp?: number;
  readonly speechMeta?: SpeechProjection;
}

interface ConversationFeedProps {
  readonly messages: readonly ChatMessage[];
  readonly hasSession: boolean;
  readonly onStartSession: () => void;
  readonly onSelectPrompt: (prompt: string) => void;
}

export const ConversationFeed: React.FC<ConversationFeedProps> = ({
  messages,
  hasSession,
  onStartSession,
  onSelectPrompt,
}) => {
  // Case A: No session started yet (Minimal Bauhaus Welcome)
  if (!hasSession) {
    return (
      <div className="flex flex-col items-center justify-center py-24 text-center animate-fadeIn">
        <div className="flex h-16 w-16 items-center justify-center rounded-2xl bg-stone-900 text-white shadow-lg dark:bg-white dark:text-stone-950 mb-6">
          <Icons.Mark className="h-8 w-8" />
        </div>

        <h1 className="font-mono text-3xl font-bold tracking-tight text-stone-950 dark:text-white uppercase">
          INTERLOCK
        </h1>
        <p className="mt-2 text-sm text-stone-600 dark:text-stone-300 max-w-md leading-relaxed">
          Consistency runtime for interruptible real-time agents. Anticipate early, commit safely, speak only what reality confirms.
        </p>

        <p className="mt-10 text-xl font-medium text-stone-900 dark:text-stone-100">
          “What would you like me to do?”
        </p>

        <div className="mt-6 flex flex-col items-center gap-3">
          <button
            type="button"
            id="start-session-btn"
            onClick={onStartSession}
            className="rounded-full bg-stone-900 px-7 py-3 text-sm font-semibold text-white shadow-md hover:bg-stone-800 active:scale-95 dark:bg-white dark:text-stone-950 dark:hover:bg-stone-100 transition-all"
          >
            Start a Session
          </button>

          <div className="flex flex-wrap justify-center gap-2 mt-4 text-xs">
            <span className="text-stone-500 dark:text-stone-400 self-center font-mono text-[11px]">
              Try:
            </span>
            <button
              type="button"
              onClick={() => {
                onStartSession();
                setTimeout(() => onSelectPrompt('Book 11:00.'), 400);
              }}
              className="rounded-full border border-stone-300 dark:border-stone-700 bg-stone-100/90 dark:bg-stone-900 px-3.5 py-1 text-xs text-stone-800 dark:text-stone-200 hover:border-stone-400 dark:hover:border-stone-600 transition-colors"
            >
              “Book 11:00.”
            </button>
          </div>
        </div>
      </div>
    );
  }

  // Case B: Session started, but no messages yet
  if (messages.length === 0) {
    return (
      <div className="py-20 text-center text-stone-500 dark:text-stone-400">
        <p className="text-base font-medium text-stone-800 dark:text-stone-200">Session initialized & ready.</p>
        <p className="text-xs mt-1 text-stone-500 dark:text-stone-400">
          Tell INTERLOCK your instruction below to begin.
        </p>
      </div>
    );
  }

  // Case C: Message stream
  return (
    <div className="space-y-6 py-4">
      {messages.map((msg) => {
        if (msg.role === 'user') {
          return (
            <div key={msg.id} className="flex justify-end">
              <div className="max-w-md rounded-2xl bg-stone-200/80 px-4 py-2.5 text-sm text-stone-900 dark:bg-stone-800 dark:text-stone-100">
                <p className="leading-relaxed">{msg.content}</p>
              </div>
            </div>
          );
        }

        // Assistant Message (Elevated with inline TRUTHLOCK verification)
        const meta = msg.speechMeta;
        const isCancelled = meta?.state === 'CANCELLED';

        return (
          <div key={msg.id} className="flex flex-col items-start max-w-xl">
            <div className="flex items-center gap-2 mb-1.5">
              <span className="font-mono text-xs font-bold uppercase tracking-wider text-stone-950 dark:text-white">
                INTERLOCK
              </span>
              {meta && (
                <span className="font-mono text-[10px] text-stone-400 dark:text-stone-500 uppercase">
                  {meta.act_type}
                </span>
              )}
            </div>

            <div className="text-[15px] leading-relaxed text-stone-900 dark:text-stone-100">
              <p className="whitespace-pre-wrap">{msg.content}</p>
            </div>

            {/* TRUTHLOCK Verification metadata footer */}
            {meta && (
              <div className="mt-2.5 flex flex-wrap items-center gap-2 text-xs text-stone-500 dark:text-stone-400 border-l-2 border-stone-300 dark:border-stone-800 pl-2.5">
                {isCancelled ? (
                  <span className="text-amber-600 dark:text-amber-400 font-medium">
                    ⊘ Speech cancelled at safepoint
                  </span>
                ) : (
                  <>
                    <span className="inline-flex items-center gap-1 text-emerald-600 dark:text-emerald-400 font-medium">
                      <Icons.Check className="h-3 w-3" />
                      <span>Verified by TRUTHLOCK</span>
                    </span>
                    <span>·</span>
                    <span className="capitalize">
                      {meta.requested_certainty?.toLowerCase() || 'Verified'}
                    </span>
                    {meta.heard !== null && (
                      <>
                        <span>·</span>
                        <span>{meta.heard ? 'Delivered' : 'Console text'}</span>
                      </>
                    )}
                  </>
                )}
              </div>
            )}

            {meta && (
              <TechnicalDetails
                title="Proof details"
                items={[
                  { label: 'Speech ID', value: meta.speech_id },
                  { label: 'Approved Policy', value: meta.approved_policy_id ?? 'None' },
                  { label: 'State', value: meta.state },
                ]}
                className="mt-1"
              />
            )}
          </div>
        );
      })}
    </div>
  );
};
