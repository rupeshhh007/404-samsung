import type { EffectProjection } from '../api/types';

interface WorldPanelProps {
  readonly effects: readonly EffectProjection[];
}

function effectTone(state: EffectProjection['state']): string {
  if (state === 'COMMITTED' || state === 'COMPENSATED') return 'status-success';
  if (state === 'OUTCOME_UNKNOWN' || state === 'IN_FLIGHT') return 'status-warning';
  if (state === 'FAILED') return 'status-danger';
  return 'status-neutral';
}

export function WorldPanel({ effects }: WorldPanelProps) {
  const ordered = [...effects].sort((left, right) => left.effect_id.localeCompare(right.effect_id));

  return (
    <section className="panel" aria-labelledby="world-heading">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">World</p>
          <h2 id="world-heading">Observed effects</h2>
        </div>
        <span className="status-pill status-neutral">{effects.length} observations</span>
      </div>

      {ordered.length === 0 ? (
        <div className="empty-state">No world-effect observation is available.</div>
      ) : (
        <ul className="space-y-2">
          {ordered.map((effect) => (
            <li key={effect.effect_id} className="data-card">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="font-medium">{effect.effect_type}</span>
                <span className={`status-pill ${effectTone(effect.state)}`}>{effect.state}</span>
              </div>
              <dl className="mt-2 grid grid-cols-1 gap-2 text-xs sm:grid-cols-2">
                <div><dt>Authority</dt><dd>{effect.authority}</dd></div>
                <div><dt>Observed at</dt><dd>{effect.observed_at || 'Not available'}</dd></div>
                <div><dt>Provider effect</dt><dd className="mono-wrap">{effect.provider_effect_id}</dd></div>
                <div><dt>Operation</dt><dd className="mono-wrap">{effect.operation_id}</dd></div>
              </dl>
              {effect.supersedes_effect_id && (
                <p className="mono-wrap mt-2 text-xs text-stone-500 dark:text-stone-400">
                  Supersedes {effect.supersedes_effect_id}
                </p>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
