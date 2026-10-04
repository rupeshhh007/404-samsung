import React from 'react';
import { motion } from 'motion/react';
import { Icon } from '../primitives/Icon';
import type { UserTranscriptItem } from '../viewmodel/transcript';

interface UserLineProps {
  readonly item: UserTranscriptItem;
  readonly onRetry?: (text: string) => void;
}

export const UserLine: React.FC<UserLineProps> = ({ item, onRetry }) => {
  const isPending = item.sequence === null && !item.failed;

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.24, ease: [0.22, 1, 0.36, 1] }}
      className="flex gap-4 py-3 border-b border-ink-600/40 text-bone-50 group"
    >
      {/* 72px Left Gutter */}
      <div className="w-[72px] flex-shrink-0 flex flex-col items-start font-mono text-[11px] pt-1 select-none">
        <span className="text-bone-500 font-bold tracking-wider">YOU</span>
        <span className="text-bone-600 text-[10px]">
          {item.sequence !== null ? `#${item.sequence}` : isPending ? '…' : '—'}
        </span>
      </div>

      {/* Message Content */}
      <div className="flex-1 min-w-0 space-y-1">
        <div className="font-display font-medium text-[clamp(16px,1.15vw,20px)] leading-snug break-words">
          {item.text}
          {isPending && (
            <span className="ml-2 font-mono text-[10px] text-sig-pending tracking-widest uppercase animate-pulse">
              …journaling
            </span>
          )}
        </div>

        {item.failed && (
          <div className="flex items-center gap-2 pt-1">
            <span className="font-mono text-[10px] text-sig-alarm uppercase tracking-wider flex items-center gap-1">
              <Icon name="cross" size={12} />
              Not Accepted
            </span>
            {onRetry && (
              <button
                type="button"
                onClick={() => onRetry(item.text)}
                className="font-mono text-[10px] text-bone-300 hover:text-bone-50 underline focus-visible:outline-sig-active"
              >
                Retry
              </button>
            )}
          </div>
        )}
      </div>
    </motion.div>
  );
};
