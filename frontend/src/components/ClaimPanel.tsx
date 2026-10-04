import type { ClaimProjection, EvidenceProjection } from '../api/types';

interface ClaimPanelProps {
  readonly claims: readonly ClaimProjection[];
  readonly evidence: readonly EvidenceProjection[];
}

function claimTone(state: ClaimProjection['state']): string {
  if (state === 'CONFIRMED') return 'status-success';
  if (state === 'CONTRADICTED') return 'status-danger';
  if (state === 'PENDING' || state === 'UNCERTAIN' || state === 'STALE') return 'status-warning';
  return 'status-neutral';
}

export function ClaimPanel({ claims, evidence }: ClaimPanelProps) {
  const ordered = [...claims].sort((left, right) => left.claim_id.localeCompare(right.claim_id));

  return (
    <section className="panel" aria-labelledby="claim-heading">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">Claims</p>
          <h2 id="claim-heading">ClaimGraph projection</h2>
        </div>
        <span className="status-pill status-neutral">
          {claims.length} claims · {evidence.length} evidence
        </span>
      </div>

      {ordered.length === 0 ? (
        <div className="empty-state">No claims are projected. Absence is not confirmation.</div>
      ) : (
        <ul className="space-y-2">
          {ordered.map((claim) => (
            <li key={claim.claim_id} className="data-card">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="font-medium">{claim.predicate}</span>
                <span className={`status-pill ${claimTone(claim.state)}`}>{claim.state}</span>
              </div>
              <dl className="mt-2 grid grid-cols-1 gap-2 text-xs">
                <div><dt>Evidence rule</dt><dd>{claim.required_evidence_rule}</dd></div>
                <div>
                  <dt>Supporting evidence</dt>
                  <dd className="mono-wrap">
                    {claim.supporting_evidence_ids.length > 0
                      ? claim.supporting_evidence_ids.join(', ')
                      : 'None projected'}
                  </dd>
                </div>
                <div><dt>Updated by</dt><dd className="mono-wrap">{claim.updated_by_event_id}</dd></div>
              </dl>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
