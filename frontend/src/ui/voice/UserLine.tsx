import React from 'react';
import type { UserTranscriptItem } from '../viewmodel/transcript';

interface UserLineProps {
  readonly item: UserTranscriptItem;
  readonly onRetry?: (text: string) => void;
}

export const UserLine: React.FC<UserLineProps> = ({ item, onRetry }) => {
  const isPending = item.sequence === null && !item.failed;

  return (
    <div
      className="editorial-user flex flex-col"
    >
      <div className="editorial-user-label flex items-center justify-between">
        <span>You asked</span>
        {item.sequence !== null && (
          <span className="opacity-60">#{item.sequence}</span>
        )}
      </div>

      <div className="editorial-user-text break-words">
        {item.text}
        {isPending && (
          <span className="ml-2 font-mono text-[10px] text-[var(--console-muted)] animate-pulse">
            …sending
          </span>
        )}
      </div>

      {item.failed && (
        <div className="flex items-center gap-2 pt-2 font-mono text-[10px] text-[var(--console-muted)]">
          <span>✕ Not Accepted</span>
          {onRetry && (
            <button
              type="button"
              onClick={() => onRetry(item.text)}
              className="underline hover:text-bone-50 ml-1"
            >
              Retry
            </button>
          )}
        </div>
      )}
    </div>
  );
};
