import type { DivergenceProjection, ReconciliationPlanProjection } from '../api/types';

interface DivergenceAlertProps {
  readonly divergences: readonly DivergenceProjection[];
  readonly plans: readonly ReconciliationPlanProjection[];
}

function divergenceTone(state: DivergenceProjection['state']): string {
  if (state === 'RESOLVED') return 'status-success';
  if (state === 'RECONCILING') return 'status-active';
  if (state === 'OPEN' || state === 'ESCALATED') return 'status-danger';
  return 'status-warning';
}

export function DivergenceAlert({ divergences, plans }: DivergenceAlertProps) {
  const ordered = [...divergences].sort((left, right) => left.divergence_id.localeCompare(right.divergence_id));

  return (
    <section className="divergence-banner" aria-labelledby="divergence-heading" aria-live="assertive">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <p className="eyebrow">Divergence monitor</p>
          <h2 id="divergence-heading" className="text-sm font-semibold">
            Intent and observed-world mismatches
          </h2>
        </div>
        <span className="status-pill status-neutral">{divergences.length} projected</span>
      </div>

      {ordered.length === 0 ? (
        <p className="mt-2 text-sm text-stone-600 dark:text-stone-300">
          No divergence is projected. This does not assert that the world is verified.
        </p>
      ) : (
        <ul className="mt-3 grid gap-2 lg:grid-cols-2">
          {ordered.map((item) => {
            const plan = plans.find((candidate) => candidate.divergence_id === item.divergence_id);
            return (
              <li key={item.divergence_id} className="data-card">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="font-medium">{item.kind}</span>
                  <span className={`status-pill ${divergenceTone(item.state)}`}>{item.state}</span>
                </div>
                <p className="mono-wrap mt-2 text-xs">Desired: {item.desired_fingerprint}</p>
                <p className="mono-wrap mt-1 text-xs">
                  Observed effects: {item.observed_effect_ids.length > 0 ? item.observed_effect_ids.join(', ') : 'None listed'}
                </p>
                <p className="mt-1 text-xs">
                  Reconciliation: {plan ? plan.state : 'No plan projected'}
                </p>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
