import React from 'react';
import type {
  DivergenceProjection,
  EffectProjection,
  IntentProjection,
  IntentRevision,
  OperationProjection,
} from '../api/types';
import { TechnicalDetails, type DetailItem } from './TechnicalDetails';
import { explainDivergence } from '../utils/formatters';

interface RealityStripProps {
  readonly divergences: readonly DivergenceProjection[];
  readonly intent: IntentProjection | null;
  readonly revision: IntentRevision | null;
  readonly effects: readonly EffectProjection[];
  readonly operations: readonly OperationProjection[];
}

export const RealityStrip: React.FC<RealityStripProps> = ({
  divergences,
  intent,
  revision,
  effects,
  operations,
}) => {
  const hasDivergence = divergences.length > 0;
  const activeOp = operations[0];
  const hasCommittedEffect = effects.some((e) => e.state === 'COMMITTED');
  const isExecuting = activeOp && (activeOp.state === 'DISPATCHED' || activeOp.state === 'WAITING');

  // Case 1: Mismatch / Divergence Active (The Hero Bauhaus Object)
  if (hasDivergence) {
    const div = divergences[0];
    const explanation = explainDivergence(div, intent, revision, effects);

    const techItems: DetailItem[] = [
      { label: 'Divergence ID', value: div.divergence_id },
      { label: 'Classification', value: div.kind, mono: false },
      { label: 'Desired Fingerprint', value: div.desired_fingerprint },
      {
        label: 'Observed Effect IDs',
        value: div.observed_effect_ids.length > 0 ? div.observed_effect_ids.join(', ') : 'None',
      },
      { label: 'Detected By Event', value: div.detected_by_event_id },
    ];

    return (
      <section
        className="my-4 rounded-xl border border-red-500/40 bg-stone-950 p-5 text-stone-100 shadow-xl transition-all"
        aria-label="Reality Mismatch Alert"
      >
        {/* Top geometric label bar */}
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-stone-800 pb-3">
          <div className="flex items-center gap-2">
            <span className="h-2 w-2 rounded-full bg-red-500 animate-pulse" aria-hidden="true" />
            <span className="font-mono text-[11px] font-bold uppercase tracking-[0.2em] text-red-400">
              {explanation.headline}
            </span>
          </div>
          <span className="font-mono text-[10px] uppercase tracking-wider text-stone-400">
            Truth Conflict Detected
          </span>
        </div>

        {/* Bauhaus Asymmetric Comparison */}
        <div className="grid grid-cols-1 items-center gap-4 py-4 sm:grid-cols-7 text-center sm:text-left">
          <div className="sm:col-span-3">
            <p className="font-mono text-[10px] uppercase tracking-[0.16em] text-stone-400">
              Target Goal (User)
            </p>
            <p className="mt-1 font-mono text-2xl font-bold tracking-tight text-white">
              {explanation.desiredSlot}
            </p>
            <p className="text-[11px] text-stone-400 mt-0.5">
              Active committed intent
            </p>
          </div>

          <div className="sm:col-span-1 flex justify-center text-3xl font-light text-red-500 select-none">
            ≠
          </div>

          <div className="sm:col-span-3 sm:text-right">
            <p className="font-mono text-[10px] uppercase tracking-[0.16em] text-stone-400">
              Observed Reality (World)
            </p>
            <p className="mt-1 font-mono text-2xl font-bold tracking-tight text-red-400">
              {explanation.observedSlot}
            </p>
            <p className="text-[11px] text-stone-400 mt-0.5">
              Confirmed external booking
            </p>
          </div>
        </div>

        {/* Plain-English Explanation */}
        <div className="border-t border-stone-800/80 pt-3">
          <p className="text-xs leading-relaxed text-stone-300">
            {explanation.explanation}
          </p>
        </div>

        <TechnicalDetails title="Reasoning & Identifiers" items={techItems} className="mt-3 text-stone-400" />
      </section>
    );
  }

  // Case 2: Executing or In-Flight (Reality Unverified)
  if (isExecuting) {
    return (
      <div className="my-3 flex items-center justify-between rounded-lg border border-amber-500/20 bg-amber-500/5 px-3.5 py-2.5 text-xs text-stone-700 dark:text-stone-300 transition-colors">
        <div className="flex items-center gap-2">
          <span className="h-1.5 w-1.5 rounded-full bg-amber-500 animate-pulse" aria-hidden="true" />
          <span className="font-mono text-[10px] font-bold uppercase tracking-widest text-amber-600 dark:text-amber-400">
            REALITY UNVERIFIED
          </span>
          <span className="text-stone-500 dark:text-stone-400 hidden sm:inline">
            — Waiting for external confirmation from provider.
          </span>
        </div>
      </div>
    );
  }

  // Case 3: Committed & Aligned (Reality in Sync - Quiet, Positive, No Red)
  if (hasCommittedEffect) {
    return (
      <div className="my-3 flex items-center justify-between rounded-lg border border-emerald-500/20 bg-emerald-500/5 px-3.5 py-2.5 text-xs text-stone-700 dark:text-stone-300 transition-colors">
        <div className="flex items-center gap-2">
          <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" aria-hidden="true" />
          <span className="font-mono text-[10px] font-bold uppercase tracking-widest text-emerald-600 dark:text-emerald-400">
            REALITY IN SYNC
          </span>
          <span className="text-stone-500 dark:text-stone-400 hidden sm:inline">
            — Your requested state matches the currently observed world.
          </span>
        </div>
      </div>
    );
  }

  // Case 4: Completely fresh session with no actions yet -> clean negative space
  return null;
};
