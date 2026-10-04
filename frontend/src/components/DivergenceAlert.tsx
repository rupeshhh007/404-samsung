import React from 'react';
import type {
  DivergenceProjection,
  EffectProjection,
  IntentProjection,
  IntentRevision,
  ReconciliationPlanProjection,
} from '../api/types';
import { Icons } from './Icons';
import { TechnicalDetails, type DetailItem } from './TechnicalDetails';
import { explainDivergence } from '../utils/formatters';

interface DivergenceAlertProps {
  readonly divergences: readonly DivergenceProjection[];
  readonly plans: readonly ReconciliationPlanProjection[];
  readonly intent?: IntentProjection | null;
  readonly revision?: IntentRevision | null;
  readonly effects?: readonly EffectProjection[];
}

export const DivergenceAlert: React.FC<DivergenceAlertProps> = ({
  divergences,
  plans,
  intent = null,
  revision = null,
  effects = [],
}) => {
  const ordered = [...divergences].sort((left, right) =>
    left.divergence_id.localeCompare(right.divergence_id),
  );

  // A. Calm Neutral State: No divergence detected
  if (ordered.length === 0) {
    return (
      <section
        className="rounded-xl border border-stone-200/80 bg-white/70 p-4 transition-colors dark:border-stone-800/80 dark:bg-stone-900/40"
        aria-labelledby="divergence-heading"
        aria-live="polite"
      >
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2.5">
            <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-emerald-50 text-emerald-600 dark:bg-emerald-950/40 dark:text-emerald-400">
              <Icons.ShieldCheck className="h-4 w-4" />
            </div>
            <div>
              <p className="eyebrow">Divergence Monitor</p>
              <h2 id="divergence-heading" className="text-sm font-medium text-stone-900 dark:text-stone-100">
                Reality Alignment
              </h2>
            </div>
          </div>
          <span className="status-pill border-stone-200 bg-stone-100/80 text-stone-600 dark:border-stone-800 dark:bg-stone-800/60 dark:text-stone-300">
            In sync · 0 divergences
          </span>
        </div>
        <p className="mt-2 text-xs leading-relaxed text-stone-500 dark:text-stone-400">
          User intent and confirmed external effects are aligned. No state divergence is currently projected.
        </p>
      </section>
    );
  }

  // B. Active Divergence Alert State: Real mismatch needing visibility
  return (
    <section
      className="rounded-xl border border-rose-300/90 bg-rose-50/70 p-4 shadow-sm transition-colors dark:border-rose-900/80 dark:bg-rose-950/30"
      aria-labelledby="divergence-heading"
      aria-live="assertive"
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2.5">
          <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-rose-100 text-rose-700 dark:bg-rose-900/60 dark:text-rose-300">
            <Icons.AlertTriangle className="h-4 w-4" />
          </div>
          <div>
            <p className="text-[10px] font-semibold uppercase tracking-wider text-rose-800 dark:text-rose-400">
              Attention Required
            </p>
            <h2 id="divergence-heading" className="text-sm font-semibold text-rose-950 dark:text-rose-100">
              Intent & Real-World Mismatch
            </h2>
          </div>
        </div>
        <span className="status-pill status-danger">
          {ordered.length} {ordered.length === 1 ? 'mismatch open' : 'mismatches open'}
        </span>
      </div>

      <div className="mt-3 space-y-3">
        {ordered.map((item) => {
          const plan = plans.find((candidate) => candidate.divergence_id === item.divergence_id);
          const explanation = explainDivergence(item, intent, revision, effects);

          const techItems: DetailItem[] = [
            { label: 'Divergence ID', value: item.divergence_id },
            { label: 'Mismatch Kind', value: item.kind, mono: false },
            { label: 'Desired Fingerprint', value: item.desired_fingerprint },
            {
              label: 'Observed Effects',
              value: item.observed_effect_ids.length > 0
                ? item.observed_effect_ids.join(', ')
                : 'None listed',
            },
            { label: 'Detected By Event', value: item.detected_by_event_id },
          ];

          return (
            <div
              key={item.divergence_id}
              className="rounded-lg border border-rose-200/90 bg-white/90 p-3.5 dark:border-rose-900/60 dark:bg-stone-900/90"
            >
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <span className="text-sm font-semibold text-stone-900 dark:text-stone-100">
                  {explanation.headline}
                </span>
                <span className="status-pill status-danger text-[11px]">
                  State: {item.state}
                </span>
              </div>

              {/* Natural language summary */}
              <p className="mt-2 text-xs leading-relaxed text-stone-700 dark:text-stone-300">
                {explanation.explanation}
              </p>

              {/* Visual Comparison Box */}
              <div className="mt-3 grid grid-cols-1 gap-2 rounded-lg bg-stone-50 p-2.5 dark:bg-stone-950/60 sm:grid-cols-2">
                <div className="flex flex-col">
                  <span className="text-[10px] font-medium uppercase tracking-wider text-stone-500 dark:text-stone-400">
                    User Goal
                  </span>
                  <span className="mt-0.5 text-xs font-medium text-stone-800 dark:text-stone-200">
                    {explanation.desiredSummary}
                  </span>
                </div>
                <div className="flex flex-col">
                  <span className="text-[10px] font-medium uppercase tracking-wider text-rose-700 dark:text-rose-400">
                    Observed Reality
                  </span>
                  <span className="mt-0.5 text-xs font-medium text-stone-800 dark:text-stone-200">
                    {explanation.observedSummary}
                  </span>
                </div>
              </div>

              {/* Reconciliation status note */}
              <div className="mt-2.5 flex items-center justify-between text-[11px] text-stone-500 dark:text-stone-400">
                <span>Reconciliation:</span>
                <span className="font-medium text-stone-700 dark:text-stone-300">
                  {plan ? `Plan state: ${plan.state}` : 'Awaiting manual confirmation (no automated override)'}
                </span>
              </div>

              {/* Progressive disclosure for raw IDs */}
              <TechnicalDetails title="View protocol identifiers" items={techItems} />
            </div>
          );
        })}
      </div>
    </section>
  );
};
