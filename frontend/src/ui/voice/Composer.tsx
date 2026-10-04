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
    <div className="relative bg-ink-800 border border-ink-600 notch-tl p-2.5 slab-shadow">
      <div className="flex items-end gap-3">
        {/* Left Mono Prompt */}
        <span className="font-mono text-base font-bold text-bone-500 pb-2 pl-1 select-none">
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
          className="flex-1 bg-transparent text-bone-50 placeholder:font-voice placeholder:italic placeholder:text-bone-500 text-sm font-sans resize-none py-2 px-1 focus:outline-none min-h-[38px] max-h-[120px] leading-relaxed"
        />

        {/* Barge-In Button (If Assistant is speaking) */}
        {canBargeIn && (
          <button
            type="button"
            onClick={onBargeIn}
            className="h-10 px-3 bg-sig-pending/15 border border-sig-pending text-sig-pending hover:bg-sig-pending/25 transition-colors font-mono text-[11px] font-bold uppercase tracking-wider flex items-center gap-1.5 focus-visible:outline-sig-active"
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
          className="w-10 h-10 bg-bone-50 text-ink-950 hover:bg-white active:scale-95 transition-all flex items-center justify-center flex-shrink-0 disabled:opacity-30 disabled:pointer-events-none focus-visible:outline-sig-active"
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
