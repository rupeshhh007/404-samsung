import React, { useState, useMemo } from 'react';
import type { ProjectionEventMessage } from '../api/types';
import { Icons } from './Icons';
import { CopyButton } from './CopyButton';
import { shortenId, humanizeEventName } from '../utils/formatters';

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

function eventNodeStyle(eventType: string): { dotColor: string; textColor: string } {
  if (eventType.includes('Divergence')) {
    return { dotColor: 'bg-red-500 ring-red-500/20', textColor: 'text-red-600 dark:text-red-400' };
  }
  if (eventType.includes('Effect') || eventType.includes('World')) {
    return { dotColor: 'bg-emerald-500 ring-emerald-500/20', textColor: 'text-emerald-600 dark:text-emerald-400' };
  }
  if (eventType.includes('Speech') || eventType.includes('Emission')) {
    return { dotColor: 'bg-sky-500 ring-sky-500/20', textColor: 'text-sky-600 dark:text-sky-400' };
  }
  if (eventType.includes('Intent') || eventType.includes('Input')) {
    return { dotColor: 'bg-purple-500 ring-purple-500/20', textColor: 'text-purple-600 dark:text-purple-400' };
  }
  if (eventType.includes('Tool') || eventType.includes('Dispatch') || eventType.includes('Cancellation')) {
    return { dotColor: 'bg-amber-500 ring-amber-500/20', textColor: 'text-amber-600 dark:text-amber-400' };
  }
  return { dotColor: 'bg-stone-400 ring-stone-400/20', textColor: 'text-stone-700 dark:text-stone-300' };
}

export const TraceTimeline: React.FC<TraceTimelineProps> = ({
  events,
  loading,
  error,
}) => {
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
        humanizeEventName(e.event_type).toLowerCase().includes(q) ||
        e.trace.correlation_id.toLowerCase().includes(q) ||
        String(e.sequence).includes(q),
    );
  }, [ordered, filter]);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-stone-200/80 pb-3 dark:border-stone-800/80">
        <div className="flex items-center gap-2">
          <Icons.Terminal className="h-4 w-4 text-stone-500" />
          <h2 className="text-sm font-semibold tracking-wide text-stone-900 dark:text-stone-100 font-mono uppercase">
            Causal Timeline
          </h2>
        </div>

        <div className="flex items-center gap-2">
          {events.length > 0 && (
            <input
              type="text"
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              placeholder="Search event type, ID…"
              className="rounded-lg border border-stone-200 bg-stone-50/80 px-2.5 py-1 text-xs text-stone-800 placeholder:text-stone-400 focus:bg-white focus:outline-none dark:border-stone-800 dark:bg-stone-950/60 dark:text-stone-200 font-mono"
            />
          )}
          <span className="font-mono text-xs text-stone-500">
            {filtered.length} of {events.length}
          </span>
        </div>
      </div>

      {error && (
        <div className="rounded-lg border border-rose-300 bg-rose-50/80 p-3 text-xs text-rose-800 dark:border-rose-900 dark:bg-rose-950/40 dark:text-rose-200">
          {error}
        </div>
      )}

      {loading && ordered.length === 0 && (
        <p className="py-12 text-center text-xs text-stone-400 font-mono">
          Streaming retained events from server…
        </p>
      )}

      {!loading && !error && ordered.length === 0 && (
        <p className="py-12 text-center text-xs text-stone-400 font-mono">
          No retained events recorded for this session.
        </p>
      )}

      {filtered.length > 0 && (
        <div className="relative pl-6 before:absolute before:bottom-0 before:left-2 before:top-3 before:w-px before:bg-stone-200 dark:before:bg-stone-800">
          <ol className="space-y-6">
            {filtered.map((event) => {
              const style = eventNodeStyle(event.event_type);
              const affected = affectedLabels(event);
              const deltaJson = JSON.stringify(event.projection_delta, null, 2);

              return (
                <li key={`${event.session_id}-${event.sequence}`} className="relative group">
                  {/* Geometric node dot on vertical timeline */}
                  <span
                    className={`absolute -left-[21px] top-1 h-3 w-3 rounded-full ring-4 transition-all ${style.dotColor}`}
                    aria-hidden="true"
                  />

                  <div className="rounded-xl border border-stone-200/80 bg-white/70 p-3.5 shadow-sm transition-colors dark:border-stone-800/80 dark:bg-stone-900/60 hover:border-stone-300 dark:hover:border-stone-700">
                    <div className="flex flex-wrap items-baseline justify-between gap-2">
                      <div className="flex items-baseline gap-2">
                        <span className="text-sm font-semibold text-stone-900 dark:text-stone-100">
                          {humanizeEventName(event.event_type)}
                        </span>
                        <span className="font-mono text-[11px] text-stone-400 dark:text-stone-500">
                          ({event.event_type})
                        </span>
                      </div>
                      <span className="font-mono text-xs text-stone-500 bg-stone-100 px-2 py-0.5 rounded dark:bg-stone-800">
                        #{event.sequence}
                      </span>
                    </div>

                    <div className="mt-2 flex flex-wrap items-center gap-3 text-xs text-stone-500 dark:text-stone-400">
                      <div className="flex items-center gap-1 font-mono text-[11px]">
                        <span>corr:</span>
                        <span title={event.trace.correlation_id}>
                          {shortenId(event.trace.correlation_id, 6, 4)}
                        </span>
                        <CopyButton text={event.trace.correlation_id} label="Copy correlation ID" />
                      </div>

                      {affected.length > 0 && (
                        <span>· {affected.join(' · ')}</span>
                      )}
                    </div>

                    {/* Expandable sanitized projection delta */}
                    <details className="mt-3 group/delta">
                      <summary className="flex cursor-pointer select-none items-center gap-1 font-mono text-[11px] text-stone-400 hover:text-stone-800 dark:hover:text-stone-200 transition-colors list-none [&::-webkit-details-marker]:hidden">
                        <Icons.ChevronDown className="h-3 w-3 transition-transform group-open/delta:rotate-180 opacity-70" />
                        <span>[Projection Delta]</span>
                      </summary>

                      <div className="relative mt-2">
                        <div className="absolute right-2 top-2 z-10">
                          <CopyButton text={deltaJson} label="Copy Delta JSON" />
                        </div>
                        <pre className="max-h-60 overflow-auto rounded-lg bg-stone-50 p-3 font-mono text-[11px] leading-relaxed text-stone-700 dark:bg-stone-950 dark:text-stone-300 border border-stone-200/80 dark:border-stone-800/80">
                          {deltaJson}
                        </pre>
                      </div>
                    </details>
                  </div>
                </li>
              );
            })}
          </ol>
        </div>
      )}
    </div>
  );
};
