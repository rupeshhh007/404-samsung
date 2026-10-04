import React from 'react';
import type { Stage } from '../viewmodel/stage';

interface SuggestionChipsProps {
  readonly stage: Stage;
  readonly onSelect: (text: string) => void;
  readonly hasInterruptableFlight?: boolean;
}

export const SuggestionChips: React.FC<SuggestionChipsProps> = ({
  stage,
  onSelect,
  hasInterruptableFlight = false,
}) => {
  // If ready or no intent yet -> Suggest "Book 11:00."
  if (stage === 'READY' || stage === 'NO_SESSION') {
    return (
      <div className="flex items-center gap-2 mb-2 select-none">
        <span className="font-mono text-[10px] text-bone-500 uppercase tracking-wider">
          TRY:
        </span>
        <button
          type="button"
          onClick={() => onSelect('Book 11:00.')}
          className="px-2.5 py-1 font-mono text-[11px] bg-ink-850 hover:bg-ink-800 border border-ink-600 hover:border-bone-500 text-bone-300 hover:text-bone-50 transition-colors uppercase"
        >
          Book 11:00.
        </button>
      </div>
    );
  }

  // If in flight and can be interrupted -> Key demo move! "Actually, make it 12:00."
  if (stage === 'EXECUTING' || hasInterruptableFlight) {
    return (
      <div className="flex items-center gap-2 mb-2 select-none">
        <span className="font-mono text-[10px] text-sig-active font-bold uppercase tracking-wider">
          INTERRUPT NOW:
        </span>
        <button
          type="button"
          onClick={() => onSelect('Actually, make it 12:00.')}
          className="relative px-3 py-1 font-mono text-[11px] font-bold bg-sig-active/15 border border-sig-active text-sig-active hover:bg-sig-active/25 transition-all uppercase flex items-center gap-1.5"
        >
          <span className="relative flex h-2 w-2">
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-sig-active opacity-75" />
            <span className="relative inline-flex rounded-full h-2 w-2 bg-sig-active" />
          </span>
          <span>Actually, make it 12:00.</span>
        </button>
      </div>
    );
  }

  return null;
};
