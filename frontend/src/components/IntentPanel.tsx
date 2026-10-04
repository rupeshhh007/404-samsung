import type { IntentProjection, IntentRevision, JsonObject } from '../api/types';

interface IntentPanelProps {
  readonly intent: IntentProjection | null;
  readonly revision: IntentRevision | null;
}

function displayObject(value: JsonObject): string {
  const entries = Object.entries(value);
  if (entries.length === 0) return 'No values projected';
  return entries
    .sort(([left], [right]) => left.localeCompare(right))
    .map(([key, item]) => `${key}: ${typeof item === 'object' ? JSON.stringify(item) : String(item)}`)
    .join(' · ');
}

export function IntentPanel({ intent, revision }: IntentPanelProps) {
  return (
    <section className="panel" aria-labelledby="intent-heading">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">Intent</p>
          <h2 id="intent-heading">Active goal and revision</h2>
        </div>
        {revision && <span className="status-pill status-active">{revision.maturity}</span>}
      </div>

      {!intent || !revision ? (
        <div className="empty-state">No active intent revision is projected.</div>
      ) : (
        <dl className="definition-grid">
          <div>
            <dt>Goal type</dt>
            <dd>{intent.goal_type}</dd>
          </div>
          <div>
            <dt>Authorization</dt>
            <dd>{revision.authorization}</dd>
          </div>
          <div>
            <dt>Revision</dt>
            <dd className="mono-wrap">{revision.revision_id}</dd>
          </div>
          <div>
            <dt>Values</dt>
            <dd className="break-words">{displayObject(revision.values)}</dd>
          </div>
        </dl>
      )}
    </section>
  );
}
