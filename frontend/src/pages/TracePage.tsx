import type { ProjectionEventMessage } from '../api/types';
import type { ProjectionStoreState } from '../state/store';
import { selectSessionSummary } from '../state/projections';
import { TraceTimeline } from '../components/TraceTimeline';

interface TracePageProps {
  readonly state: ProjectionStoreState;
  readonly events: readonly ProjectionEventMessage[];
  readonly loading: boolean;
  readonly error: string | null;
}

export function TracePage({ state, events, loading, error }: TracePageProps) {
  const summary = state.projection ? selectSessionSummary(state.projection) : null;

  return (
    <main id="main-content" className="mx-auto w-full max-w-7xl space-y-4 px-4 py-5">
      <section className="panel" aria-labelledby="trace-summary-heading">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">Projection summary</p>
            <h2 id="trace-summary-heading">Current authoritative view</h2>
          </div>
          <span className="status-pill status-neutral">
            Through sequence {state.lastAppliedSequence || '—'}
          </span>
        </div>
        {!summary ? (
          <div className="empty-state">No session projection is available.</div>
        ) : (
          <dl className="summary-grid">
            <div><dt>Intent</dt><dd className="mono-wrap">{summary.intent_id ?? 'None active'}</dd></div>
            <div><dt>Operations</dt><dd>{summary.operation_count}</dd></div>
            <div><dt>Effects</dt><dd>{summary.effect_count}</dd></div>
            <div><dt>Claims</dt><dd>{summary.claim_count}</dd></div>
            <div><dt>Speech</dt><dd>{summary.speech_count}</dd></div>
            <div><dt>Divergences</dt><dd>{summary.divergence_count}</dd></div>
          </dl>
        )}
      </section>

      <TraceTimeline events={events} loading={loading} error={error} />

      <p className="text-xs text-stone-500 dark:text-stone-400">
        The canonical event contract exposes sequence, event type, correlation ID, and sanitized projection delta.
        Logical time and causation are not exposed to this frontend view.
      </p>
    </main>
  );
}
