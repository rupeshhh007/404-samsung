import React from 'react';
import { motion } from 'motion/react';
import { Icon } from '../primitives/Icon';
import { Chip } from '../primitives/Chip';
import type { ClaimProjection } from '../../api/types';

interface LockedLineProps {
  readonly pendingClaim: ClaimProjection;
}

export const LockedLine: React.FC<LockedLineProps> = ({ pendingClaim }) => {
  return (
    <motion.div
      initial={{ opacity: 0, scale: 0.98 }}
      animate={{ opacity: 1, scale: 1 }}
      exit={{ opacity: 0, scale: 0.95 }}
      transition={{ duration: 0.3 }}
      className="flex gap-4 py-4 border-b border-ink-600/40 select-none"
    >
      {/* 72px Left Gutter */}
      <div className="w-[72px] flex-shrink-0 flex flex-col items-start font-mono text-[11px] pt-1.5">
        <span className="text-sig-pending font-bold tracking-wider flex items-center gap-1">
          <Icon name="lock-closed" size={11} />
          LOCK
        </span>
        <span className="text-bone-600 text-[10px]">…</span>
      </div>

      {/* Redaction / Words Locked Bar */}
      <div className="flex-1 max-w-xl space-y-2">
        <div
          className="relative p-3.5 bg-ink-800 border border-sig-pending/40 overflow-hidden"
          style={{
            backgroundImage:
              'repeating-linear-gradient(45deg, transparent, transparent 10px, rgba(255, 176, 32, 0.08) 10px, rgba(255, 176, 32, 0.08) 20px)',
          }}
        >
          <div className="flex items-center gap-2 text-sig-pending font-mono text-[11px] font-bold tracking-wider uppercase mb-1.5">
            <Icon name="lock-closed" size={14} />
            <span>WORDS LOCKED — NO SUPPORTING EVIDENCE YET</span>
          </div>

          <div className="flex flex-wrap items-center gap-2 font-mono text-xs text-bone-300">
            <span className="text-bone-500 text-[11px]">PREDICATE:</span>
            <span className="font-semibold text-bone-100">{pendingClaim.predicate}</span>
            <Chip variant="pending" className="h-5 text-[10px]">
              {pendingClaim.state}
            </Chip>
          </div>
        </div>

        <div className="font-mono text-[10px] text-bone-500 tracking-wide">
          TRUTHLOCK holds speech emission until external world confirms booking evidence.
        </div>
      </div>
    </motion.div>
  );
};
