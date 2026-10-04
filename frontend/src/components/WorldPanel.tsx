import React from 'react';
import type { EffectProjection } from '../api/types';
import { Icons } from './Icons';
import { TechnicalDetails, type DetailItem } from './TechnicalDetails';
import {
  formatEffectType,
  formatEffectState,
  formatSlot,
  formatTimestamp,
} from '../utils/formatters';

interface WorldPanelProps {
  readonly effects: readonly EffectProjection[];
}

function toneClass(tone: string): string {
  if (tone === 'success') return 'status-success';
  if (tone === 'active') return 'status-active';
  if (tone === 'warning') return 'status-warning';
  if (tone === 'danger') return 'status-danger';
  return 'status-neutral';
}

export const WorldPanel: React.FC<WorldPanelProps> = ({ effects }) => {
  const ordered = [...effects].sort((left, right) =>
    left.effect_id.localeCompare(right.effect_id),
  );

  return (
    <section className="panel" aria-labelledby="world-heading">
      <div className="panel-heading">
        <div className="flex items-center gap-2">
          <Icons.Globe className="h-4 w-4 text-emerald-600 dark:text-emerald-400" />
          <div>
            <p className="eyebrow">External Reality</p>
            <h2 id="world-heading">Observed World</h2>
          </div>
        </div>
        <span className="status-pill status-neutral">
          {effects.length} {effects.length === 1 ? 'effect recorded' : 'effects recorded'}
        </span>
      </div>

      {ordered.length === 0 ? (
        <div className="empty-state">
          No external effects observed yet. Physical provider commits appear here once verified.
        </div>
      ) : (
        <div className="space-y-3">
          {ordered.map((effect) => {
            const stateInfo = formatEffectState(effect.state);
            const slotVal =
              effect.parameters?.confirmed_slot ??
              effect.parameters?.requested_slot ??
              effect.parameters?.slot ??
              null;
            const slotFormatted = slotVal ? formatSlot(slotVal) : null;

            const techItems: DetailItem[] = [
              { label: 'Provider Effect ID', value: effect.provider_effect_id },
              { label: 'Operation ID', value: effect.operation_id },
              { label: 'Authority', value: effect.authority, mono: false },
              { label: 'Internal Effect ID', value: effect.effect_id },
              { label: 'Superseded Effect', value: effect.supersedes_effect_id ?? 'None' },
            ];

            return (
              <div
                key={effect.effect_id}
                className="rounded-lg border border-stone-200/80 bg-stone-50/60 p-3 text-sm transition-colors dark:border-stone-800/80 dark:bg-stone-950/40"
              >
                {/* Header: Human-readable effect type + state */}
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="flex items-center gap-1.5">
                    <span className="font-semibold text-stone-900 dark:text-stone-100">
                      {formatEffectType(effect.effect_type)}
                    </span>
                    <span className="rounded-full bg-emerald-100/70 px-2 py-0.5 text-[10px] font-medium text-emerald-800 dark:bg-emerald-950/60 dark:text-emerald-300">
                      {effect.authority === 'AUTHORITATIVE' ? 'Authoritative' : effect.authority}
                    </span>
                  </div>
                  <span className={`status-pill ${toneClass(stateInfo.tone)}`}>
                    {stateInfo.label}
                  </span>
                </div>

                {/* Key observation summary */}
                <div className="mt-2.5 grid grid-cols-2 gap-2 text-xs">
                  {slotFormatted && (
                    <div className="flex flex-col">
                      <span className="text-[10px] uppercase tracking-wider text-stone-400 dark:text-stone-500">
                        Confirmed Slot
                      </span>
                      <span className="mt-0.5 font-medium text-stone-900 dark:text-stone-100">
                        {slotFormatted}
                      </span>
                    </div>
                  )}
                  <div className="flex flex-col">
                    <span className="text-[10px] uppercase tracking-wider text-stone-400 dark:text-stone-500">
                      Observed At
                    </span>
                    <span className="mt-0.5 font-medium text-stone-700 dark:text-stone-300">
                      {formatTimestamp(effect.observed_at)}
                    </span>
                  </div>
                </div>

                {effect.supersedes_effect_id && (
                  <p className="mt-2 text-xs text-amber-700 dark:text-amber-300">
                    Supersedes prior confirmed observation
                  </p>
                )}

                {/* Progressive disclosure for technical identifiers */}
                <TechnicalDetails title="Provider metadata" items={techItems} />
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
};
