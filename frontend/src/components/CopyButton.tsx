import React, { useState, useCallback } from 'react';
import { Icons } from './Icons';

interface CopyButtonProps {
  readonly text: string;
  readonly label?: string;
  readonly className?: string;
}

export const CopyButton: React.FC<CopyButtonProps> = ({
  text,
  label = 'Copy',
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
      // Ignore copy error
    }
  }, [text]);

  return (
    <button
      type="button"
      onClick={handleCopy}
      className={`inline-flex items-center gap-1 rounded p-1 text-[11px] font-mono text-stone-400 hover:text-stone-900 dark:hover:text-stone-100 transition-colors ${className}`}
      title={copied ? 'Copied' : label}
      aria-label={label}
    >
      {copied ? (
        <Icons.Check className="w-3 h-3 text-emerald-600 dark:text-emerald-400" />
      ) : (
        <Icons.Copy className="w-3 h-3 opacity-60 hover:opacity-100" />
      )}
    </button>
  );
};
