import React from 'react';
import type { SessionProjection } from '../../api/types';

interface CurrentActionStripProps {
  readonly projection: SessionProjection | null;
}

export const CurrentActionStrip: React.FC<CurrentActionStripProps> = ({ projection }) => {
  const operations = projection?.operations ?? [];
  const activeOp = operations[operations.length - 1] ?? null;

  let text = 'System ready';
  let colorClass = 'text-bone-400';
  let dotClass = 'bg-bone-500';

  if (activeOp) {
    if (activeOp.cancellation_state === 'TOO_LATE') {
      text = 'Cancellation was too late';
      colorClass = 'text-sig-alarm';
      dotClass = 'bg-sig-alarm';
    } else if (activeOp.cancellation_state === 'REQUESTED') {
      text = 'Cancellation requested';
      colorClass = 'text-sig-pending animate-pulse';
      dotClass = 'bg-sig-pending';
    } else if (activeOp.state === 'CANCELLED') {
      text = 'Cancelled at safepoint';
      colorClass = 'text-sig-verify';
      dotClass = 'bg-sig-verify';
    } else if (
      activeOp.state === 'DISPATCHED' ||
      activeOp.state === 'WAITING' ||
      activeOp.state === 'PREPARING' ||
      activeOp.state === 'READY'
    ) {
      text = 'Booking appointment · Executing';
      colorClass = 'text-sig-active animate-pulse';
      dotClass = 'bg-sig-active';
    } else if (activeOp.state === 'SUCCEEDED') {
      text = 'Booking appointment · Completed';
      colorClass = 'text-sig-verify';
      dotClass = 'bg-sig-verify';
    } else if (activeOp.state === 'FAILED' || activeOp.state === 'TIMED_OUT') {
      text = 'Booking appointment · Failed';
      colorClass = 'text-sig-alarm';
      dotClass = 'bg-sig-alarm';
    }
  }

  return (
    <div className="flex items-center gap-2 px-3 py-1.5 bg-ink-900 border border-ink-700/60 font-mono text-xs select-none">
      <span className={`w-2 h-2 rounded-full ${dotClass} flex-shrink-0`} aria-hidden="true" />
      <span className="text-[11px] text-bone-500 uppercase tracking-wider font-semibold">
        CURRENT ACTION:
      </span>
      <span className={`font-medium ${colorClass} tracking-wide`}>
        {text}
      </span>
    </div>
  );
};
