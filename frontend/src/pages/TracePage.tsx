import type { ProjectionEventMessage } from '../api/types';
import type { ProjectionStoreState } from '../state/store';
import { selectSessionSummary } from '../state/projections';
import { TraceTimeline } from '../components/TraceTimeline';
import { Icons } from '../components/Icons';
import { CopyButton } from '../components/CopyButton';
import { shortenId } from '../utils/formatters';

interface TracePageProps {
  readonly state: ProjectionStoreState;
  readonly events: readonly ProjectionEventMessage[];
  readonly loading: boolean;
  readonly error: string | null;
}

export function TracePage({ state, events, loading, error }: TracePageProps) {
  const summary = state.projection ? selectSessionSummary(state.projection) : null;

  return (
    <main id="main-content" className="mx-auto w-full max-w-7xl space-y-4 px-4 py-4">
      {/* Projection Summary Section */}
      <section className="panel" aria-labelledby="trace-summary-heading">
        <div className="panel-heading">
          <div className="flex items-center gap-2">
            <Icons.Terminal className="h-4 w-4 text-purple-600 dark:text-purple-400" />
            <div>
              <p className="eyebrow">Runtime Metrics</p>
              <h2 id="trace-summary-heading">Authoritative Projection Snapshot</h2>
            </div>
          </div>
          <span className="status-pill status-neutral font-mono">
            Sequence #{state.lastAppliedSequence || 0}
          </span>
        </div>

        {!summary ? (
          <div className="empty-state">
            No session projection loaded. Start a session to view live runtime state counters.
          </div>
        ) : (
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
            <div className="rounded-xl border border-stone-200/80 bg-stone-50/70 p-3 dark:border-stone-800/80 dark:bg-stone-950/40">
              <span className="text-[10px] font-semibold uppercase tracking-wider text-stone-400 dark:text-stone-500">
                Active Intent
              </span>
              <p className="mt-1 flex items-center gap-1 font-mono text-xs font-semibold text-stone-900 dark:text-stone-100">
                {summary.intent_id ? (
                  <>
                    <span title={summary.intent_id}>{shortenId(summary.intent_id, 4, 3)}</span>
                    <CopyButton text={summary.intent_id} label="Copy Intent ID" />
                  </>
                ) : (
                  'None'
                )}
              </p>
            </div>

            <div className="rounded-xl border border-stone-200/80 bg-stone-50/70 p-3 dark:border-stone-800/80 dark:bg-stone-950/40">
              <span className="text-[10px] font-semibold uppercase tracking-wider text-stone-400 dark:text-stone-500">
                Operations
              </span>
              <p className="mt-1 text-base font-semibold text-stone-900 dark:text-stone-100 font-mono">
                {summary.operation_count}
              </p>
            </div>

            <div className="rounded-xl border border-stone-200/80 bg-stone-50/70 p-3 dark:border-stone-800/80 dark:bg-stone-950/40">
              <span className="text-[10px] font-semibold uppercase tracking-wider text-stone-400 dark:text-stone-500">
                World Effects
              </span>
              <p className="mt-1 text-base font-semibold text-stone-900 dark:text-stone-100 font-mono">
                {summary.effect_count}
              </p>
            </div>

            <div className="rounded-xl border border-stone-200/80 bg-stone-50/70 p-3 dark:border-stone-800/80 dark:bg-stone-950/40">
              <span className="text-[10px] font-semibold uppercase tracking-wider text-stone-400 dark:text-stone-500">
                Truth Claims
              </span>
              <p className="mt-1 text-base font-semibold text-stone-900 dark:text-stone-100 font-mono">
                {summary.claim_count}
              </p>
            </div>

            <div className="rounded-xl border border-stone-200/80 bg-stone-50/70 p-3 dark:border-stone-800/80 dark:bg-stone-950/40">
              <span className="text-[10px] font-semibold uppercase tracking-wider text-stone-400 dark:text-stone-500">
                Speech Acts
              </span>
              <p className="mt-1 text-base font-semibold text-stone-900 dark:text-stone-100 font-mono">
                {summary.speech_count}
              </p>
            </div>

            <div className={`rounded-xl border p-3 ${
              summary.divergence_count > 0
                ? 'border-rose-300 bg-rose-50/70 dark:border-rose-900 dark:bg-rose-950/40'
                : 'border-stone-200/80 bg-stone-50/70 dark:border-stone-800/80 dark:bg-stone-950/40'
            }`}>
              <span className="text-[10px] font-semibold uppercase tracking-wider text-stone-400 dark:text-stone-500">
                Divergences
              </span>
              <p className={`mt-1 text-base font-semibold font-mono ${
                summary.divergence_count > 0
                  ? 'text-rose-700 dark:text-rose-300'
                  : 'text-stone-900 dark:text-stone-100'
              }`}>
                {summary.divergence_count}
              </p>
            </div>
          </div>
        )}
      </section>

      {/* Timeline Section */}
      <TraceTimeline events={events} loading={loading} error={error} />

      <p className="text-center text-xs text-stone-400 dark:text-stone-500">
        Deterministic audit timeline · Monotonic sequence order · Replayable event causal graph
      </p>
    </main>
  );
}
