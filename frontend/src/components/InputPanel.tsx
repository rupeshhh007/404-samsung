import { useState, type FormEvent } from 'react';
import type { SpeechProjection } from '../api/types';
import { Icons } from './Icons';
import { TechnicalDetails } from './TechnicalDetails';

interface InputPanelProps {
  readonly speech: readonly SpeechProjection[];
  readonly sessionAvailable: boolean;
  readonly actionPending: boolean;
  readonly onSubmitText: (content: string) => Promise<void>;
  readonly onCancelSpeech: (speechId: string) => Promise<void>;
}

const QUICK_PROMPTS = [
  'Book 11:00.',
  'Actually, make it 12:00.',
  'What is the status of my appointment?',
];

export function InputPanel({
  speech,
  sessionAvailable,
  actionPending,
  onSubmitText,
  onCancelSpeech,
}: InputPanelProps) {
  const [content, setContent] = useState('');
  const orderedSpeech = [...speech].reverse();
  const cancelable = orderedSpeech.find(
    (item) => item.state === 'QUEUED' || item.state === 'EMITTING',
  );

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const normalized = content.trim();
    if (!normalized || actionPending) return;
    setContent('');
    await onSubmitText(normalized);
  }

  function handlePromptClick(promptText: string) {
    if (!sessionAvailable || actionPending) return;
    setContent(promptText);
  }

  return (
    <section className="panel flex flex-col h-full" aria-labelledby="conversation-heading">
      <div className="panel-heading">
        <div className="flex items-center gap-2">
          <Icons.MessageSquare className="h-4 w-4 text-sky-600 dark:text-sky-400" />
          <div>
            <p className="eyebrow">Interaction</p>
            <h2 id="conversation-heading">Conversation & Input</h2>
          </div>
        </div>
        <span className="status-pill status-neutral">
          {speech.length} {speech.length === 1 ? 'utterance' : 'utterances'}
        </span>
      </div>

      {/* Input submission box (Placed prominently at top of interaction panel) */}
      <form onSubmit={handleSubmit} className="space-y-3 pb-4">
        <div>
          <label htmlFor="interlock-input" className="sr-only">
            Send text command or prompt
          </label>
          <div className="relative">
            <textarea
              id="interlock-input"
              value={content}
              onChange={(event) => setContent(event.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault();
                  void handleSubmit(e as unknown as FormEvent<HTMLFormElement>);
                }
              }}
              rows={3}
              className="text-input text-sm leading-relaxed"
              placeholder={
                sessionAvailable
                  ? 'Type an instruction (e.g. "Book 11:00", "Actually, make it 12:00")…'
                  : 'Start a session to interact with the assistant.'
              }
              disabled={!sessionAvailable || actionPending}
            />
          </div>
        </div>

        {/* Demo Quick Prompts */}
        {sessionAvailable && (
          <div className="flex flex-wrap items-center gap-1.5 text-xs">
            <span className="text-[11px] text-stone-400 dark:text-stone-500 font-medium mr-1">
              Suggestions:
            </span>
            {QUICK_PROMPTS.map((prompt) => (
              <button
                key={prompt}
                type="button"
                onClick={() => handlePromptClick(prompt)}
                disabled={actionPending}
                className="rounded-full border border-stone-200/90 bg-stone-100/70 px-2.5 py-1 text-[11px] text-stone-600 transition-colors hover:bg-stone-200 hover:text-stone-900 dark:border-stone-800 dark:bg-stone-800/60 dark:text-stone-400 dark:hover:bg-stone-700 dark:hover:text-stone-200"
              >
                {prompt}
              </button>
            ))}
          </div>
        )}

        <div className="flex flex-wrap items-center justify-between gap-2 pt-1">
          <div className="flex items-center gap-2">
            <button
              type="submit"
              className="primary-button inline-flex items-center gap-1.5"
              disabled={!sessionAvailable || actionPending || content.trim().length === 0}
            >
              <span>{actionPending ? 'Processing…' : 'Send message'}</span>
              <Icons.ArrowRight className="h-3.5 w-3.5" />
            </button>
            {cancelable && (
              <button
                type="button"
                className="secondary-button inline-flex items-center gap-1 text-rose-700 dark:text-rose-400 border-rose-300 dark:border-rose-900"
                disabled={actionPending}
                onClick={() => void onCancelSpeech(cancelable.speech_id)}
              >
                <Icons.AlertTriangle className="h-3.5 w-3.5" />
                <span>Barge-in / Cancel speech</span>
              </button>
            )}
          </div>
          <span className="text-[11px] text-stone-400 dark:text-stone-500 hidden sm:inline">
            Press Enter to send
          </span>
        </div>
      </form>

      {/* Verified Speech Acts Feed */}
      <div className="border-t border-stone-200/70 pt-4 dark:border-stone-800/70 flex-1">
        <div className="mb-2.5 flex items-center justify-between">
          <span className="text-[10px] font-semibold uppercase tracking-wider text-stone-400 dark:text-stone-500">
            Assistant Utterance History
          </span>
        </div>

        {orderedSpeech.length === 0 ? (
          <div className="empty-state">
            No assistant utterances recorded yet. Responses will appear here once verified by TRUTHLOCK.
          </div>
        ) : (
          <ol className="space-y-2.5" aria-label="Speech history">
            {orderedSpeech.map((item, index) => {
              const isLatest = index === 0;

              return (
                <li
                  key={item.speech_id}
                  className={`rounded-xl border p-3.5 text-sm transition-all ${
                    isLatest
                      ? 'border-sky-300/80 bg-white/95 shadow-sm dark:border-sky-900/60 dark:bg-stone-900/90'
                      : 'border-stone-200/70 bg-stone-50/60 dark:border-stone-800/70 dark:bg-stone-950/40 opacity-85'
                  }`}
                >
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="flex items-center gap-1.5">
                      <span className="text-xs font-semibold text-stone-900 dark:text-stone-100">
                        Assistant
                      </span>
                      {isLatest && (
                        <span className="rounded-full bg-sky-100 px-1.5 py-0.2 text-[9px] font-medium text-sky-800 dark:bg-sky-950 dark:text-sky-300">
                          Latest
                        </span>
                      )}
                    </div>
                    <span className="rounded-full border border-stone-200 bg-stone-100 px-2 py-0.5 text-[10px] font-mono text-stone-600 dark:border-stone-800 dark:bg-stone-800 dark:text-stone-400">
                      {item.act_type}
                    </span>
                  </div>

                  <p className="mt-2 text-xs leading-relaxed text-stone-800 dark:text-stone-200">
                    "{item.rendered_text ?? 'Controlled text is pending verification.'}"
                  </p>

                  <div className="mt-2.5 flex flex-wrap items-center gap-2 text-[11px] text-stone-500 dark:text-stone-400">
                    <span>Certainty: {item.requested_certainty}</span>
                    <span aria-hidden="true">·</span>
                    <span>State: {item.state.toLowerCase()}</span>
                    {item.heard !== null && (
                      <>
                        <span aria-hidden="true">·</span>
                        <span>{item.heard ? 'Delivered' : 'Console text'}</span>
                      </>
                    )}
                  </div>

                  {/* Progressive technical disclosure */}
                  <TechnicalDetails
                    title="Speech details"
                    items={[
                      { label: 'Speech ID', value: item.speech_id },
                      { label: 'Policy ID', value: item.approved_policy_id ?? 'None' },
                      { label: 'Supersedes', value: item.supersedes_speech_id ?? 'None' },
                    ]}
                  />
                </li>
              );
            })}
          </ol>
        )}
      </div>
    </section>
  );
}
