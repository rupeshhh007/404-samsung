import React from 'react';
import { motion } from 'motion/react';
import type { UserTranscriptItem } from '../viewmodel/transcript';

interface UserLineProps {
  readonly item: UserTranscriptItem;
  readonly onRetry?: (text: string) => void;
}

export const UserLine: React.FC<UserLineProps> = ({ item, onRetry }) => {
  const isPending = item.sequence === null && !item.failed;

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.18, ease: 'easeOut' }}
      className="flex flex-col py-3 border-b border-ink-800/50 text-bone-100 group"
    >
      <div className="flex items-center justify-between pb-1 text-[11px] font-mono text-bone-500">
        <span className="font-semibold text-bone-400">YOU</span>
        {item.sequence !== null && (
          <span className="text-[10px] text-bone-600">#{item.sequence}</span>
        )}
      </div>

      <div className="font-sans font-medium text-[15px] sm:text-[16px] text-bone-100 leading-snug break-words">
        {item.text}
        {isPending && (
          <span className="ml-2 font-mono text-[10px] text-sig-pending animate-pulse">
            …sending
          </span>
        )}
      </div>

      {item.failed && (
        <div className="flex items-center gap-2 pt-1 font-mono text-[10px] text-sig-alarm">
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
    </motion.div>
  );
};
