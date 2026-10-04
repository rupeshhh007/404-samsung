import React, { useState, useEffect } from 'react';
import { Icon } from './Icon';

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

  useEffect(() => {
    if (!copied) return;
    const timer = setTimeout(() => {
      setCopied(false);
    }, 1200);
    return () => clearTimeout(timer);
  }, [copied]);

  const handleCopy = async (e: React.MouseEvent) => {
    e.stopPropagation();
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
    } catch {
      // Fallback if clipboard API is blocked
      const textarea = document.createElement('textarea');
      textarea.value = text;
      textarea.style.position = 'fixed';
      textarea.style.opacity = '0';
      document.body.appendChild(textarea);
      textarea.select();
      try {
        document.execCommand('copy');
        setCopied(true);
      } catch {
        // Ignore
      }
      document.body.removeChild(textarea);
    }
  };

  return (
    <button
      type="button"
      onClick={handleCopy}
      title={copied ? 'Copied' : label}
      aria-label={copied ? 'Copied to clipboard' : label}
      className={`inline-flex items-center justify-center p-1 text-bone-500 hover:text-bone-50 transition-colors rounded-none focus-visible:outline-2 focus-visible:outline-sig-active ${className}`}
    >
      <Icon name={copied ? 'check' : 'copy'} size={13} className={copied ? 'text-sig-verify' : ''} />
      <span className="sr-only" role="status">
        {copied ? 'Copied' : ''}
      </span>
    </button>
  );
};
