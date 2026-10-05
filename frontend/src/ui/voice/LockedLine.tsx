import React from 'react';

export const LockedLine: React.FC = () => {
  return (
    <div className="editorial-truthlock mb-8 flex items-center gap-2 select-none">
      <span className="h-1.5 w-1.5 rounded-full bg-[var(--console-muted)] animate-pulse" />
      <span>TRUTHLOCK · Awaiting authoritative evidence</span>
    </div>
  );
};
