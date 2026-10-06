import React, { useState, useRef, useEffect } from 'react';
import { Chip } from '../primitives/Chip';

interface ProvenanceChipsProps {
  readonly isScriptedReplay?: boolean;
  readonly isScriptedContinuation?: boolean;
}

export const ProvenanceChips: React.FC<ProvenanceChipsProps> = ({
  isScriptedReplay = false,
  isScriptedContinuation = false,
}) => {
  const [activePopover, setActivePopover] = useState<string | null>(null);
  const popoverRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handleOutsideClick = (e: MouseEvent) => {
      if (popoverRef.current && !popoverRef.current.contains(e.target as Node)) {
        setActivePopover(null);
      }
    };
    if (activePopover) {
      document.addEventListener('click', handleOutsideClick);
    }
    return () => {
      document.removeEventListener('click', handleOutsideClick);
    };
  }, [activePopover]);

  const PROVENANCE_DEFINITIONS: Record<string, { label: string; desc: string }> = {
    runtime: {
      label: 'REAL RUNTIME',
      desc: 'The backend state engine, serial journal, and TRUTHLOCK assertion check are fully authoritative and running live.',
    },
    provider: {
      label: 'SIMULATED PROVIDER',
      desc: 'External tool side-effects (e.g. calendar API, booking backend) run with controlled fake latency to simulate network boundaries.',
    },
    timing: {
      label: 'SCRIPTED TIMING',
      desc: 'Tool execution delays are deterministically timed to exercise race conditions and late cancellation arrival.',
    },
  };

  return (
    <div className="relative inline-flex items-center gap-1.5" ref={popoverRef}>
      {/* Scripted Replay High-Contrast Chip */}
      {isScriptedReplay && (
        <Chip
          variant="slab"
          className="border-sig-pending bg-sig-pending text-ink-950 font-bold"
          title="Events driven by scripted storyboard replay"
        >
          {isScriptedContinuation
            ? 'SCRIPTED CONTINUATION · NOT A LIVE RUN'
            : 'SCRIPTED REPLAY'}
        </Chip>
      )}

      {/* 3 Compact Chips */}
      {Object.entries(PROVENANCE_DEFINITIONS).map(([key, def]) => (
        <button
          key={key}
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            setActivePopover((prev) => (prev === key ? null : key));
          }}
          className="focus-visible:outline-sig-active"
        >
          <Chip variant="neutral" className="hover:border-bone-500 cursor-pointer">
            {def.label}
          </Chip>
        </button>
      ))}

      {/* Popover */}
      {activePopover && PROVENANCE_DEFINITIONS[activePopover] && (
        <div
          role="tooltip"
          className="absolute top-8 right-0 z-50 w-72 p-3 bg-ink-850 border border-ink-600 slab-shadow text-xs text-bone-50 space-y-2 animate-fadeIn"
        >
          <div className="font-mono text-[10px] uppercase tracking-wider text-sig-active font-semibold">
            {PROVENANCE_DEFINITIONS[activePopover]?.label}
          </div>
          <p className="font-sans text-bone-300 leading-relaxed text-[11px]">
            {PROVENANCE_DEFINITIONS[activePopover]?.desc}
          </p>
          <div className="pt-1.5 border-t border-ink-600 font-mono text-[10px] text-bone-500">
            Interpreter: not reported by the API (documented default: deterministic fallback)
          </div>
        </div>
      )}
    </div>
  );
};
