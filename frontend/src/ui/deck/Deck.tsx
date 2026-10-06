import React from 'react';
import { IntentRealityHero } from './IntentRealityHero';
import { CurrentActionStrip } from './CurrentActionStrip';
import type { Stage } from '../viewmodel/stage';
import type { SessionProjection } from '../../api/types';

interface DeckProps {
  readonly stage: Stage;
  readonly gapPx: number;
  readonly projection: SessionProjection | null;
  readonly onOpenBlackBox?: () => void;
}

export const Deck: React.FC<DeckProps> = ({
  stage,
  gapPx,
  projection,
  onOpenBlackBox,
}) => {
  return (
    <section
      aria-label="INTERLOCK Intent vs Reality"
      className="flex flex-col h-full justify-between space-y-4 select-none p-2"
    >
      <div className="space-y-4">
        {/* Region 3: Compact Current Action Strip */}
        <CurrentActionStrip projection={projection} />

        {/* Region 2: Bauhaus Intent vs Reality Hero */}
        <IntentRealityHero
          stage={stage}
          gapPx={gapPx}
          projection={projection}
          onOpenBlackBox={onOpenBlackBox}
        />
      </div>

      {/* Quiet Footnote */}
      <div className="pt-4 border-t border-ink-800/60 flex items-center justify-between text-xs font-mono text-bone-600">
        <span>INTERLOCK CONSISTENCY RUNTIME</span>
        {onOpenBlackBox && (
          <button
            type="button"
            onClick={onOpenBlackBox}
            className="text-bone-500 hover:text-bone-300 transition-colors"
          >
            Engineering Telemetry in Black Box →
          </button>
        )}
      </div>
    </section>
  );
};
