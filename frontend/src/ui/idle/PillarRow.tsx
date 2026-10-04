import React from 'react';
import { Eyebrow } from '../primitives/Eyebrow';

export const PillarRow: React.FC = () => {
  return (
    <footer className="w-full border-t border-ink-600/80 pt-6 mt-12 grid grid-cols-1 md:grid-cols-3 gap-6 font-mono text-xs">
      <div className="space-y-1.5">
        <div className="flex items-center gap-2">
          <span className="w-1.5 h-1.5 bg-sig-spec" />
          <Eyebrow className="text-sig-spec font-bold">ANTICIPATE</Eyebrow>
        </div>
        <div className="font-semibold text-bone-50 text-[11px] tracking-wide">
          BranchCache & Speculative Plan
        </div>
        <p className="font-sans text-bone-500 text-[12px] leading-relaxed">
          Executes provisional branches before latency resolves; promotes or discards with zero state contamination.
        </p>
      </div>

      <div className="space-y-1.5">
        <div className="flex items-center gap-2">
          <span className="w-1.5 h-1.5 bg-sig-adapt" />
          <Eyebrow className="text-sig-adapt font-bold">ADAPT</Eyebrow>
        </div>
        <div className="font-semibold text-bone-50 text-[11px] tracking-wide">
          SAFEPOINT & Atomic Recovery
        </div>
        <p className="font-sans text-bone-500 text-[12px] leading-relaxed">
          Catches mid-flight user interruptions and late side effects, reconciling the physical world back to intent.
        </p>
      </div>

      <div className="space-y-1.5">
        <div className="flex items-center gap-2">
          <span className="w-1.5 h-1.5 bg-sig-verify" />
          <Eyebrow className="text-sig-verify font-bold">VERIFY</Eyebrow>
        </div>
        <div className="font-semibold text-bone-50 text-[11px] tracking-wide">
          ClaimGraph & TRUTHLOCK
        </div>
        <p className="font-sans text-bone-500 text-[12px] leading-relaxed">
          Speaks only what external reality has mathematically proven; keeps spoken words locked until evidence arrives.
        </p>
      </div>
    </footer>
  );
};
