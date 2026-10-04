import React, { useState, useCallback } from 'react';
import { Icons } from './Icons';

interface CopyButtonProps {
  readonly text: string;
  readonly label?: string;
  readonly className?: string;
}

export const CopyButton: React.FC<CopyButtonProps> = ({
  text,
  label = 'Copy ID',
  className = '',
}) => {
  const [copied, setCopied] = useState(false);

  const handleCopy = useCallback(async (e: React.MouseEvent) => {
    e.stopPropagation();
    try {
      if (navigator.clipboard && typeof navigator.clipboard.writeText === 'function') {
        await navigator.clipboard.writeText(text);
      } else {
        const textarea = document.createElement('textarea');
        textarea.value = text;
        textarea.style.position = 'fixed';
        textarea.style.opacity = '0';
        document.body.appendChild(textarea);
        textarea.select();
        document.execCommand('copy');
        document.body.removeChild(textarea);
      }
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Ignore clipboard write failure
    }
  }, [text]);

  return (
    <button
      type="button"
      onClick={handleCopy}
      className={`inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[11px] font-mono transition-colors hover:bg-stone-200/70 dark:hover:bg-stone-800 text-stone-500 hover:text-stone-800 dark:text-stone-400 dark:hover:text-stone-200 ${className}`}
      title={copied ? 'Copied to clipboard' : label}
      aria-label={label}
    >
      {copied ? (
        <>
          <Icons.Check className="w-3 h-3 text-emerald-600 dark:text-emerald-400" />
          <span className="text-[10px] text-emerald-600 dark:text-emerald-400">Copied</span>
        </>
      ) : (
        <>
          <Icons.Copy className="w-3 h-3 opacity-70" />
          <span className="sr-only">{label}</span>
        </>
      )}
    </button>
  );
};
