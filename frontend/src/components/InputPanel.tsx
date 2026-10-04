import { useState, type FormEvent } from 'react';
import type { SpeechProjection } from '../api/types';

interface InputPanelProps {
  readonly speech: readonly SpeechProjection[];
  readonly sessionAvailable: boolean;
  readonly actionPending: boolean;
  readonly onSubmitText: (content: string) => Promise<void>;
  readonly onCancelSpeech: (speechId: string) => Promise<void>;
}

function heardLabel(heard: boolean | null): string {
  if (heard === true) return 'Heard: yes';
  if (heard === false) return 'Heard: no';
  return 'Heard: not reported';
}

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
    if (!normalized) return;
    await onSubmitText(normalized);
    setContent('');
  }

  return (
    <section className="panel h-full" aria-labelledby="conversation-heading">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">Conversation</p>
          <h2 id="conversation-heading">Input and verified output</h2>
        </div>
        <span className="status-pill status-neutral">{speech.length} speech acts</span>
      </div>

      <div className="space-y-3">
        {orderedSpeech.length === 0 ? (
          <div className="empty-state">
            <p>No projected speech is available.</p>
            <p>User-input history is not part of the current frontend projection.</p>
          </div>
        ) : (
          <ol className="space-y-2" aria-label="Projected speech acts">
            {orderedSpeech.map((item) => (
              <li key={item.speech_id} className="data-card">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="font-medium text-stone-800 dark:text-stone-100">
                    {item.act_type}
                  </span>
                  <span className="status-pill status-neutral">{item.state}</span>
                </div>
                <p className="mt-2 text-sm text-stone-700 dark:text-stone-200">
                  {item.rendered_text ?? 'Rendered text is not available.'}
                </p>
                <div className="mt-2 flex flex-wrap gap-2 text-xs text-stone-500 dark:text-stone-400">
                  <span>{item.requested_certainty}</span>
                  <span aria-hidden="true">·</span>
                  <span>{heardLabel(item.heard)}</span>
                  {item.supersedes_speech_id && (
                    <span className="mono-wrap">Supersedes {item.supersedes_speech_id}</span>
                  )}
                </div>
              </li>
            ))}
          </ol>
        )}
      </div>

      <form className="mt-4 space-y-2 border-t border-stone-200 pt-4 dark:border-stone-800" onSubmit={handleSubmit}>
        <label htmlFor="interlock-input" className="text-sm font-medium">
          Send text input
        </label>
        <textarea
          id="interlock-input"
          value={content}
          onChange={(event) => setContent(event.target.value)}
          rows={3}
          className="text-input"
          placeholder={sessionAvailable ? 'Describe or correct the request…' : 'Start a session to send input.'}
          disabled={!sessionAvailable || actionPending}
        />
        <div className="flex flex-wrap gap-2">
          <button
            type="submit"
            className="primary-button"
            disabled={!sessionAvailable || actionPending || content.trim().length === 0}
          >
            Submit input
          </button>
          {cancelable && (
            <button
              type="button"
              className="secondary-button"
              disabled={actionPending}
              onClick={() => void onCancelSpeech(cancelable.speech_id)}
            >
              Cancel active speech
            </button>
          )}
        </div>
      </form>
    </section>
  );
}
