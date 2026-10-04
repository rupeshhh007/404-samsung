import React from 'react';
import type { ClaimProjection, EvidenceProjection } from '../api/types';
import { Icons } from './Icons';
import { TechnicalDetails, type DetailItem } from './TechnicalDetails';
import {
  formatPredicate,
  formatClaimState,
} from '../utils/formatters';

interface ClaimPanelProps {
  readonly claims: readonly ClaimProjection[];
  readonly evidence: readonly EvidenceProjection[];
}

function toneClass(tone: string): string {
  if (tone === 'success') return 'status-success';
  if (tone === 'active') return 'status-active';
  if (tone === 'warning') return 'status-warning';
  if (tone === 'danger') return 'status-danger';
  return 'status-neutral';
}

export const ClaimPanel: React.FC<ClaimPanelProps> = ({ claims, evidence }) => {
  const ordered = [...claims].sort((left, right) =>
    left.claim_id.localeCompare(right.claim_id),
  );

  return (
    <section className="panel" aria-labelledby="claim-heading">
      <div className="panel-heading">
        <div className="flex items-center gap-2">
          <Icons.ShieldCheck className="h-4 w-4 text-sky-600 dark:text-sky-400" />
          <div>
            <p className="eyebrow">ClaimGraph</p>
            <h2 id="claim-heading">Truth Claims</h2>
          </div>
        </div>
        <span className="status-pill status-neutral">
          {claims.length} {claims.length === 1 ? 'claim' : 'claims'} · {evidence.length} evidence
        </span>
      </div>

      {ordered.length === 0 ? (
        <div className="empty-state">
          No truth claims recorded yet. Factual assertions are tracked and verified against evidence before speech is approved.
        </div>
      ) : (
        <div className="space-y-3">
          {ordered.map((claim) => {
            const stateInfo = formatClaimState(claim.state);
            const hasEvidence = claim.supporting_evidence_ids.length > 0;

            const techItems: DetailItem[] = [
              { label: 'Claim ID', value: claim.claim_id },
              { label: 'Predicate', value: claim.predicate },
              { label: 'Evidence Rule', value: claim.required_evidence_rule, mono: false },
              {
                label: 'Supporting Evidence',
                value: hasEvidence ? claim.supporting_evidence_ids.join(', ') : 'None',
              },
              { label: 'Updated By Event', value: claim.updated_by_event_id },
            ];

            return (
              <div
                key={claim.claim_id}
                className="rounded-lg border border-stone-200/80 bg-stone-50/60 p-3 text-sm transition-colors dark:border-stone-800/80 dark:bg-stone-950/40"
              >
                {/* Header: Human predicate + Claim state */}
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="flex items-center gap-1.5">
                    <span className="font-semibold text-stone-900 dark:text-stone-100">
                      {formatPredicate(claim.predicate)}
                    </span>
                  </div>
                  <span className={`status-pill ${toneClass(stateInfo.tone)}`}>
                    {stateInfo.label}
                  </span>
                </div>

                {/* Evidence status summary */}
                <div className="mt-2.5 flex items-center gap-2 text-xs text-stone-600 dark:text-stone-400">
                  {hasEvidence ? (
                    <>
                      <Icons.Check className="h-3.5 w-3.5 text-emerald-600 dark:text-emerald-400 shrink-0" />
                      <span>
                        Supported by {claim.supporting_evidence_ids.length} verified evidence record(s)
                      </span>
                    </>
                  ) : (
                    <>
                      <Icons.Clock className="h-3.5 w-3.5 text-amber-500 dark:text-amber-400 shrink-0" />
                      <span>
                        Awaiting provider proof ({claim.required_evidence_rule || 'evidence rule pending'})
                      </span>
                    </>
                  )}
                </div>

                {/* Progressive disclosure for technical identifiers */}
                <TechnicalDetails title="Claim evidence metadata" items={techItems} />
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
};
