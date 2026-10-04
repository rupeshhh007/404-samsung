import React, { useState, type FormEvent } from 'react';
import { Icons } from './Icons';

interface ComposerProps {
  readonly hasSession: boolean;
  readonly actionPending: boolean;
  readonly canCancelSpeech: boolean;
  readonly onCancelSpeech: () => void;
  readonly onSubmitText: (text: string) => Promise<void>;
  readonly prefillValue?: string;
  readonly onPrefillConsumed?: () => void;
}

const SUGGESTIONS = [
  'Book 11:00.',
  'Actually, make it 12:00.',
];

export const Composer: React.FC<ComposerProps> = ({
  hasSession,
  actionPending,
  canCancelSpeech,
  onCancelSpeech,
  onSubmitText,
  prefillValue,
  onPrefillConsumed,
}) => {
  const [text, setText] = useState('');

  React.useEffect(() => {
    if (prefillValue) {
      setText(prefillValue);
      onPrefillConsumed?.();
    }
  }, [prefillValue, onPrefillConsumed]);

  async function handleSubmit(e?: FormEvent) {
    if (e) e.preventDefault();
    const inputEl = document.getElementById('interlock-input') as HTMLTextAreaElement | null;
    const clean = text.trim() || (inputEl ? inputEl.value.trim() : '');
    if (!clean || actionPending || !hasSession) return;
    setText('');
    if (inputEl) inputEl.value = '';
    await onSubmitText(clean);
  }

  return (
    <div className="sticky bottom-0 z-20 border-t border-stone-200/80 bg-white/95 pb-6 pt-3 backdrop-blur-md dark:border-stone-800/80 dark:bg-[#0e0d0c]/95 transition-colors">
      <div className="mx-auto max-w-2xl px-2">
        {/* Suggestion Chips */}
        {hasSession && (
          <div className="mb-2.5 flex flex-wrap items-center gap-1.5 text-xs">
            <span className="text-[11px] font-mono uppercase tracking-wider text-stone-400 dark:text-stone-500 mr-1">
              Suggestions:
            </span>
            {SUGGESTIONS.map((suggestion) => (
              <button
                key={suggestion}
                type="button"
                onClick={() => setText(suggestion)}
                disabled={actionPending}
                className="rounded-full border border-stone-200/90 bg-stone-100/70 px-2.5 py-0.5 text-[11px] text-stone-600 transition-colors hover:bg-stone-200 dark:border-stone-800 dark:bg-stone-900/60 dark:text-stone-300 dark:hover:bg-stone-800"
              >
                {suggestion}
              </button>
            ))}
          </div>
        )}

        <form onSubmit={handleSubmit} className="relative flex items-end rounded-2xl border border-stone-300/80 bg-stone-50/50 p-2 shadow-sm focus-within:border-stone-500 focus-within:bg-white dark:border-stone-700/80 dark:bg-stone-900/50 dark:focus-within:border-stone-500 dark:focus-within:bg-stone-950 transition-all">
          <textarea
            id="interlock-input"
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                void handleSubmit();
              }
            }}
            rows={1}
            disabled={!hasSession || actionPending}
            placeholder={
              hasSession
                ? 'Tell INTERLOCK what to do… (Enter to send)'
                : 'Start a session to interact.'
            }
            className="max-h-32 flex-1 resize-none bg-transparent px-2.5 py-1.5 text-sm text-stone-900 placeholder:text-stone-400 focus:outline-none dark:text-stone-100 dark:placeholder:text-stone-500"
          />

          <div className="flex items-center gap-1.5 pb-0.5 pr-0.5">
            {canCancelSpeech && (
              <button
                type="button"
                onClick={onCancelSpeech}
                disabled={actionPending}
                className="rounded-xl border border-rose-300 bg-rose-50 px-2.5 py-1 text-xs font-medium text-rose-700 hover:bg-rose-100 dark:border-rose-900 dark:bg-rose-950/60 dark:text-rose-300 transition-colors"
                title="Barge-in / Cancel active assistant speech"
              >
                Cancel Speech
              </button>
            )}

            <button
              type="submit"
              disabled={!hasSession || actionPending || (!text.trim() && !(document.getElementById('interlock-input') as HTMLTextAreaElement)?.value.trim())}
              className="flex h-8 w-8 items-center justify-center rounded-xl bg-stone-900 text-white transition-all hover:bg-stone-800 disabled:cursor-not-allowed disabled:opacity-30 dark:bg-stone-100 dark:text-stone-900 dark:hover:bg-white"
              aria-label="Send message"
            >
              <Icons.ArrowRight className="h-4 w-4" />
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};
