import React from 'react';
import { Eyebrow } from '../primitives/Eyebrow';

export const PillarRow: React.FC = () => {
  return (
    <footer className="w-full border-t border-ink-600/60 pt-6 mt-8 grid grid-cols-1 md:grid-cols-3 gap-6 font-mono text-xs">
      <div className="space-y-1">
        <div className="flex items-center gap-2">
          <span className="w-1.5 h-1.5 bg-sig-spec" />
          <Eyebrow className="text-sig-spec font-bold text-[10px]">ANTICIPATE</Eyebrow>
        </div>
        <div className="font-sans font-medium text-bone-100 text-[13px]">
          Intent tracking
        </div>
        <p className="font-sans text-bone-500 text-[12px] leading-relaxed">
          Maintains desired state revisions across interruptions.
        </p>
      </div>

      <div className="space-y-1">
        <div className="flex items-center gap-2">
          <span className="w-1.5 h-1.5 bg-sig-adapt" />
          <Eyebrow className="text-sig-adapt font-bold text-[10px]">ADAPT</Eyebrow>
        </div>
        <div className="font-sans font-medium text-bone-100 text-[13px]">
          SAFEPOINT control
        </div>
        <p className="font-sans text-bone-500 text-[12px] leading-relaxed">
          Traps in-flight cancellations and reconciles late effects.
        </p>
      </div>

      <div className="space-y-1">
        <div className="flex items-center gap-2">
          <span className="w-1.5 h-1.5 bg-sig-verify" />
          <Eyebrow className="text-sig-verify font-bold text-[10px]">VERIFY</Eyebrow>
        </div>
        <div className="font-sans font-medium text-bone-100 text-[13px]">
          ClaimGraph + TRUTHLOCK
        </div>
        <p className="font-sans text-bone-500 text-[12px] leading-relaxed">
          Speaks only what external reality has verified.
        </p>
      </div>
    </footer>
  );
};
