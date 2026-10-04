import React from 'react';
import type { ProjectionEventMessage } from '../api/types';
import type { ProjectionStoreState } from '../state/store';
import { selectSessionSummary } from '../state/projections';
import { TraceTimeline } from '../components/TraceTimeline';
import { CopyButton } from '../components/CopyButton';
import { shortenId } from '../utils/formatters';

interface TracePageProps {
  readonly state: ProjectionStoreState;
  readonly events: readonly ProjectionEventMessage[];
  readonly loading: boolean;
  readonly error: string | null;
}

export const TracePage: React.FC<TracePageProps> = ({
  state,
  events,
  loading,
  error,
}) => {
  const summary = state.projection ? selectSessionSummary(state.projection) : null;
  const hasSession = state.sessionId !== null;

  return (
    <main id="main-content" className="mx-auto w-full max-w-4xl px-4 py-4 space-y-6">
      {/* Compact Bauhaus Engineering Header (One slim summary row, NOT 6 bloated cards) */}
      <section className="flex flex-wrap items-center justify-between gap-4 rounded-xl border border-stone-200/80 bg-white/70 px-4 py-3 dark:border-stone-800/80 dark:bg-stone-900/40 text-xs">
        <div className="flex items-center gap-3">
          <span className="font-mono text-[10px] uppercase tracking-wider text-stone-400">
            Session
          </span>
          {hasSession ? (
            <div className="flex items-center gap-1 font-mono text-stone-800 dark:text-stone-200">
              <span title={state.sessionId ?? ''}>{shortenId(state.sessionId, 8, 6)}</span>
              <CopyButton text={state.sessionId ?? ''} label="Copy Session ID" />
            </div>
          ) : (
            <span className="text-stone-400 italic">No session</span>
          )}

          <span className="text-stone-300 dark:text-stone-700">|</span>

          <span className="font-mono text-[10px] uppercase tracking-wider text-stone-400">
            Progress
          </span>
          <span className="font-mono text-stone-700 dark:text-stone-300">
            Seq #{state.lastAppliedSequence || 0}
          </span>
        </div>

        {summary && (
          <div className="flex flex-wrap items-center gap-2 font-mono text-[11px]">
            <span className="rounded bg-stone-100 px-2 py-0.5 text-stone-600 dark:bg-stone-800 dark:text-stone-400">
              Ops: {summary.operation_count}
            </span>
            <span className="rounded bg-stone-100 px-2 py-0.5 text-stone-600 dark:bg-stone-800 dark:text-stone-400">
              Effects: {summary.effect_count}
            </span>
            <span className="rounded bg-stone-100 px-2 py-0.5 text-stone-600 dark:bg-stone-800 dark:text-stone-400">
              Claims: {summary.claim_count}
            </span>
            <span className={`rounded px-2 py-0.5 ${
              summary.divergence_count > 0
                ? 'bg-red-100 text-red-700 dark:bg-red-950 dark:text-red-300 font-semibold'
                : 'bg-stone-100 text-stone-600 dark:bg-stone-800 dark:text-stone-400'
            }`}>
              Divergences: {summary.divergence_count}
            </span>
          </div>
        )}
      </section>

      {/* Causal Event Timeline */}
      <TraceTimeline events={events} loading={loading} error={error} />

      <footer className="text-center font-mono text-[11px] text-stone-400 dark:text-stone-600 pt-6">
        Canonical event journal · Sequence-pinned · Monotonic reducer causality
      </footer>
    </main>
  );
};
