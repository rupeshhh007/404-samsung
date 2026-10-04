import type { ProjectionEventMessage } from '../api/types';

interface TraceTimelineProps {
  readonly events: readonly ProjectionEventMessage[];
  readonly loading: boolean;
  readonly error: string | null;
}

function affectedLabels(event: ProjectionEventMessage): readonly string[] {
  const changed = Object.keys(event.projection_delta.changed)
    .sort()
    .map((name) => `${name} changed`);
  const removed = Object.entries(event.projection_delta.removed)
    .sort(([left], [right]) => left.localeCompare(right))
    .flatMap(([name, ids]) => ids.map((id) => `${name}:${id} removed`));
  return [...changed, ...removed];
}

export function TraceTimeline({ events, loading, error }: TraceTimelineProps) {
  const ordered = [...events].sort((left, right) => left.sequence - right.sequence);

  return (
    <section className="panel" aria-labelledby="trace-heading">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">Trace</p>
          <h2 id="trace-heading">Ordered projection events</h2>
        </div>
        <span className="status-pill status-neutral">{events.length} retained</span>
      </div>

      {error && (
        <p className="error-message" role="alert">{error}</p>
      )}
      {loading && ordered.length === 0 && (
        <p className="empty-state" role="status">Loading retained event history…</p>
      )}
      {!loading && !error && ordered.length === 0 && (
        <div className="empty-state">
          No retained trace events are available. This does not prove that no events occurred.
        </div>
      )}

      {ordered.length > 0 && (
        <ol className="trace-list" aria-label="Event timeline">
          {ordered.map((event) => {
            const affected = affectedLabels(event);
            return (
              <li key={`${event.session_id}-${event.sequence}`} className="trace-entry">
                <div className="trace-marker" aria-hidden="true" />
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <h3 className="text-sm font-semibold text-stone-900 dark:text-stone-100">
                      {event.event_type}
                    </h3>
                    <span className="status-pill status-active">Sequence {event.sequence}</span>
                  </div>
                  <dl className="mt-2 grid gap-2 text-xs md:grid-cols-2">
                    <div>
                      <dt>Correlation</dt>
                      <dd className="mono-wrap">{event.trace.correlation_id}</dd>
                    </div>
                    <div>
                      <dt>Affected projections</dt>
                      <dd>{affected.length > 0 ? affected.join(' · ') : 'No projection fields changed'}</dd>
                    </div>
                  </dl>
                  <details className="mt-2">
                    <summary className="cursor-pointer text-xs font-medium text-sky-700 dark:text-sky-300">
                      Sanitized projection delta
                    </summary>
                    <pre className="trace-payload">{JSON.stringify(event.projection_delta, null, 2)}</pre>
                  </details>
                </div>
              </li>
            );
          })}
        </ol>
      )}
    </section>
  );
}
