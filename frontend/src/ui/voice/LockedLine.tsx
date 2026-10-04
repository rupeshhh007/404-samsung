import React from 'react';

export const LockedLine: React.FC = () => {
  return (
    <div className="py-3 text-xs text-bone-400 font-sans flex items-center gap-2 select-none">
      <span className="w-1.5 h-1.5 rounded-full bg-sig-pending animate-pulse" />
      <span>Waiting for external confirmation…</span>
    </div>
  );
};
