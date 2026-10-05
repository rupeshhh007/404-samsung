import React, { useState, useRef, useEffect } from 'react';
import { Icon } from '../primitives/Icon';

interface ComposerProps {
  readonly disabled?: boolean;
  readonly onSend: (text: string) => Promise<void> | void;
  readonly canBargeIn?: boolean;
  readonly onBargeIn?: () => void;
  readonly initialText?: string;
  readonly onTextChange?: (text: string) => void;
}

export const Composer: React.FC<ComposerProps> = ({
  disabled = false,
  onSend,
  canBargeIn = false,
  onBargeIn,
  initialText = '',
  onTextChange,
}) => {
  const [content, setContent] = useState(initialText);
  const [sending, setSending] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (initialText !== undefined && initialText !== content) {
      setContent(initialText);
    }
  }, [initialText]);

  const handleSend = async () => {
    const trimmed = content.trim();
    if (!trimmed || disabled || sending) return;

    setSending(true);
    const backup = content;
    setContent('');
    onTextChange?.('');

    try {
      await onSend(trimmed);
    } catch {
      // Restore on failure
      setContent(backup);
      onTextChange?.(backup);
    } finally {
      setSending(false);
      textareaRef.current?.focus();
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      void handleSend();
    }
  };

  const handleChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    const nextVal = e.target.value;
    setContent(nextVal);
    onTextChange?.(nextVal);

    // Auto-grow textarea
    const el = textareaRef.current;
    if (el) {
      el.style.height = 'auto';
      el.style.height = `${Math.min(el.scrollHeight, 120)}px`;
    }
  };

  const isSendDisabled = disabled || sending || !content.trim();

  return (
    <div className="editorial-composer relative">
      <div className="flex w-full min-w-0 items-end gap-3">
        {/* Left Mono Prompt */}
        <span className="select-none pb-2 pl-1 font-mono text-base font-bold text-[var(--console-muted)]">
          ›
        </span>

        {/* Fully Controlled Textarea */}
        <textarea
          id="interlock-composer-input"
          ref={textareaRef}
          rows={1}
          value={content}
          onChange={handleChange}
          onKeyDown={handleKeyDown}
          disabled={disabled}
          placeholder="Tell it what to do…"
          className="min-h-[38px] max-h-[120px] min-w-0 flex-1 resize-none bg-transparent px-1 py-2 font-sans text-sm leading-relaxed focus:outline-none placeholder:font-voice placeholder:italic"
        />

        {/* Barge-In Button (If Assistant is speaking) */}
        {canBargeIn && (
          <button
            type="button"
            onClick={onBargeIn}
            className="flex h-10 items-center gap-1.5 border border-[var(--console-ink)] px-3 font-mono text-[10px] font-bold uppercase tracking-wider"
            title="Interrupt assistant speech emission"
          >
            <Icon name="pause" size={12} />
            <span>BARGE IN</span>
          </button>
        )}

        {/* Send Button */}
        <button
          type="button"
          onClick={handleSend}
          disabled={isSendDisabled}
          aria-label="Send instruction"
          className="flex h-10 w-10 flex-shrink-0 items-center justify-center bg-[var(--console-ink)] text-[var(--console-paper)] transition-opacity disabled:pointer-events-none disabled:opacity-25"
        >
          {sending ? (
            <span className="w-4 h-4 border-2 border-ink-950 border-t-transparent animate-spin" />
          ) : (
            <Icon name="arrow-right" size={16} />
          )}
        </button>
      </div>
    </div>
  );
};
