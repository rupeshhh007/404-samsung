import { useState, useMemo } from 'react';
import type { ProjectionEventMessage } from '../api/types';
import { Icons } from './Icons';
import { CopyButton } from './CopyButton';
import { shortenId } from '../utils/formatters';

interface TraceTimelineProps {
  readonly events: readonly ProjectionEventMessage[];
  readonly loading: boolean;
  readonly error: string | null;
}

function affectedLabels(event: ProjectionEventMessage): readonly string[] {
  const changed = Object.keys(event.projection_delta.changed)
    .sort()
    .map((name) => `${name} updated`);
  const removed = Object.entries(event.projection_delta.removed)
    .sort(([left], [right]) => left.localeCompare(right))
    .flatMap(([name, ids]) => ids.map((id) => `${name}:${shortenId(id, 4, 3)} removed`));
  return [...changed, ...removed];
}

function eventTypeTone(eventType: string): { badgeClass: string; dotClass: string } {
  if (eventType.includes('Divergence')) {
    return {
      badgeClass: 'border-rose-300 bg-rose-50 text-rose-800 dark:border-rose-900 dark:bg-rose-950 dark:text-rose-300',
      dotClass: 'bg-rose-500 ring-rose-100 dark:ring-rose-950',
    };
  }
  if (eventType.includes('Effect') || eventType.includes('World')) {
    return {
      badgeClass: 'border-emerald-300 bg-emerald-50 text-emerald-800 dark:border-emerald-900 dark:bg-emerald-950 dark:text-emerald-300',
      dotClass: 'bg-emerald-500 ring-emerald-100 dark:ring-emerald-950',
    };
  }
  if (eventType.includes('Speech') || eventType.includes('Emission')) {
    return {
      badgeClass: 'border-sky-300 bg-sky-50 text-sky-800 dark:border-sky-900 dark:bg-sky-950 dark:text-sky-300',
      dotClass: 'bg-sky-500 ring-sky-100 dark:ring-sky-950',
    };
  }
  if (eventType.includes('Intent') || eventType.includes('Input')) {
    return {
      badgeClass: 'border-purple-300 bg-purple-50 text-purple-800 dark:border-purple-900 dark:bg-purple-950 dark:text-purple-300',
      dotClass: 'bg-purple-500 ring-purple-100 dark:ring-purple-950',
    };
  }
  if (eventType.includes('Tool') || eventType.includes('Dispatch') || eventType.includes('Operation')) {
    return {
      badgeClass: 'border-amber-300 bg-amber-50 text-amber-800 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-300',
      dotClass: 'bg-amber-500 ring-amber-100 dark:ring-amber-950',
    };
  }
  return {
    badgeClass: 'border-stone-300 bg-stone-100 text-stone-700 dark:border-stone-800 dark:bg-stone-800 dark:text-stone-300',
    dotClass: 'bg-stone-500 ring-stone-100 dark:ring-stone-900',
  };
}

export function TraceTimeline({ events, loading, error }: TraceTimelineProps) {
  const [filter, setFilter] = useState('');

  const ordered = useMemo(
    () => [...events].sort((left, right) => left.sequence - right.sequence),
    [events],
  );

  const filtered = useMemo(() => {
    const q = filter.trim().toLowerCase();
    if (!q) return ordered;
    return ordered.filter(
      (e) =>
        e.event_type.toLowerCase().includes(q) ||
        e.trace.correlation_id.toLowerCase().includes(q) ||
        String(e.sequence).includes(q),
    );
  }, [ordered, filter]);

  return (
    <section className="panel" aria-labelledby="trace-heading">
      <div className="panel-heading">
        <div className="flex items-center gap-2">
          <Icons.Terminal className="h-4 w-4 text-sky-600 dark:text-sky-400" />
          <div>
            <p className="eyebrow">Audit Log</p>
            <h2 id="trace-heading">Deterministic Event Timeline</h2>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {events.length > 0 && (
            <input
              type="text"
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              placeholder="Filter events…"
              className="rounded-lg border border-stone-200 bg-stone-50 px-2.5 py-1 text-xs text-stone-800 placeholder:text-stone-400 dark:border-stone-800 dark:bg-stone-950 dark:text-stone-200"
            />
          )}
          <span className="status-pill status-neutral">
            {events.length} {events.length === 1 ? 'event' : 'events'}
          </span>
        </div>
      </div>

      {error && <p className="error-message" role="alert">{error}</p>}

      {loading && ordered.length === 0 && (
        <p className="empty-state" role="status">
          Loading retained event history from runtime…
        </p>
      )}

      {!loading && !error && ordered.length === 0 && (
        <div className="empty-state">
          No retained events available. Events stream continuously once a session starts.
        </div>
      )}

      {ordered.length > 0 && filtered.length === 0 && (
        <div className="empty-state">
          No events match filter "{filter}".
        </div>
      )}

      {filtered.length > 0 && (
        <ol className="trace-list" aria-label="Event timeline">
          {filtered.map((event) => {
            const affected = affectedLabels(event);
            const tone = eventTypeTone(event.event_type);
            const deltaJson = JSON.stringify(event.projection_delta, null, 2);

            return (
              <li
                key={`${event.session_id}-${event.sequence}`}
                className="trace-entry hover:border-stone-300 dark:hover:border-stone-700 transition-colors"
              >
                <div
                  className={`mt-1.5 h-2.5 w-2.5 shrink-0 rounded-full ring-4 ${tone.dotClass}`}
                  aria-hidden="true"
                />
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="flex items-center gap-2">
                      <span className={`rounded-full border px-2 py-0.5 text-xs font-semibold font-mono ${tone.badgeClass}`}>
                        {event.event_type}
                      </span>
                    </div>
                    <span className="rounded bg-stone-100 px-2 py-0.5 text-[11px] font-mono text-stone-600 dark:bg-stone-800 dark:text-stone-400">
                      Seq #{event.sequence}
                    </span>
                  </div>

                  <dl className="mt-2.5 grid gap-2 text-xs md:grid-cols-2">
                    <div className="flex items-center gap-1.5 min-w-0">
                      <dt className="text-stone-400 dark:text-stone-500 font-medium">
                        Correlation:
                      </dt>
                      <dd className="font-mono text-stone-700 dark:text-stone-300 truncate">
                        {shortenId(event.trace.correlation_id, 8, 6)}
                      </dd>
                      <CopyButton text={event.trace.correlation_id} label="Copy Correlation ID" />
                    </div>

                    <div>
                      <dt className="text-stone-400 dark:text-stone-500 font-medium">
                        Affected projections:
                      </dt>
                      <dd className="text-stone-700 dark:text-stone-300">
                        {affected.length > 0 ? affected.join(' · ') : 'None'}
                      </dd>
                    </div>
                  </dl>

                  <details className="mt-2.5 group">
                    <summary className="flex cursor-pointer select-none items-center gap-1 text-xs font-medium text-sky-700 hover:text-sky-800 dark:text-sky-400 dark:hover:text-sky-300">
                      <Icons.ChevronDown className="h-3 w-3 transition-transform group-open:rotate-180" />
                      <span>Sanitized projection delta</span>
                    </summary>
                    <div className="relative mt-2">
                      <div className="absolute right-2 top-2 z-10">
                        <CopyButton text={deltaJson} label="Copy JSON Payload" />
                      </div>
                      <pre className="trace-payload">{deltaJson}</pre>
                    </div>
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
