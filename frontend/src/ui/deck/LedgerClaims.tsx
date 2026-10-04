import React, { useState } from 'react';
import { Chip } from '../primitives/Chip';
import { Icon } from '../primitives/Icon';
import { resolveClaimsAndEvidence } from '../viewmodel/ledger';
import { shortenId } from '../../utils/formatters';
import type { ClaimProjection, EvidenceProjection } from '../../api/types';

interface LedgerClaimsProps {
  readonly claims: readonly ClaimProjection[];
  readonly evidence: readonly EvidenceProjection[];
}

export const LedgerClaims: React.FC<LedgerClaimsProps> = ({
  claims,
  evidence,
}) => {
  const [highlightId, setHighlightId] = useState<string | null>(null);

  const { claims: claimList, unlinkedEvidence } = resolveClaimsAndEvidence(
    claims,
    evidence,
  );

  if (claims.length === 0 && evidence.length === 0) {
    return (
      <div className="p-4 bg-ink-850 border border-ink-600 font-mono text-xs text-bone-500 text-center">
        No claims are projected. Absence is not confirmation.
      </div>
    );
  }

  return (
    <div className="space-y-4 font-mono text-xs">
      {/* Claims List */}
      <div className="space-y-3">
        {claimList.map(({ claim, evidence: claimEvidence, lockIcon, lockColor }) => {
          const isHighlighted = highlightId === claim.claim_id;

          return (
            <div
              key={claim.claim_id}
              onMouseEnter={() => setHighlightId(claim.claim_id)}
              onMouseLeave={() => setHighlightId(null)}
              className={`p-3 bg-ink-850 border transition-all ${
                isHighlighted
                  ? 'border-sig-active ring-1 ring-sig-active/30'
                  : 'border-ink-600'
              } space-y-2`}
            >
              {/* Claim Header */}
              <div className="flex items-center justify-between gap-2">
                <div className="flex items-center gap-2">
                  <Icon name={lockIcon} size={14} className={`text-sig-${lockColor}`} />
                  <span className="font-bold text-bone-50">{claim.predicate}</span>
                </div>
                <Chip variant={lockColor} className="h-5 text-[9px]">
                  {claim.state}
                </Chip>
              </div>

              {/* Required Rule */}
              {claim.required_evidence_rule && (
                <div className="text-[10px] text-bone-500">
                  <span className="text-bone-600">RULE: </span>
                  {claim.required_evidence_rule}
                </div>
              )}

              {/* Supporting Evidence Chips */}
              <div className="pt-1.5 border-t border-ink-600/40">
                <div className="text-[9px] uppercase tracking-wider text-bone-600 mb-1">
                  SUPPORTING EVIDENCE ({claimEvidence.length})
                </div>
                {claimEvidence.length === 0 ? (
                  <span className="text-[10px] text-bone-600 italic">None attached yet</span>
                ) : (
                  <div className="flex flex-wrap gap-1.5">
                    {claimEvidence.map((ev) => (
                      <Chip
                        key={ev.evidence_id}
                        variant={ev.authority === 'AUTHORITATIVE' ? 'verify' : 'neutral'}
                        className="h-5 text-[9px]"
                        title={ev.evidence_id}
                      >
                        {ev.source}: {shortenId(ev.evidence_id, 4, 3)}
                      </Chip>
                    ))}
                  </div>
                )}
              </div>
            </div>
          );
        })}
      </div>

      {/* Unlinked Evidence Subsection */}
      {unlinkedEvidence.length > 0 && (
        <div className="pt-2 border-t border-ink-600 space-y-2">
          <div className="text-[10px] uppercase tracking-widest text-bone-500 font-bold">
            UNLINKED PHYSICAL EVIDENCE ({unlinkedEvidence.length})
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
            {unlinkedEvidence.map((ev) => (
              <div
                key={ev.evidence_id}
                className="p-2 bg-ink-900 border border-ink-600 text-[10px] space-y-1"
              >
                <div className="flex items-center justify-between">
                  <span className="font-bold text-bone-100">{ev.source}</span>
                  <Chip
                    variant={ev.authority === 'AUTHORITATIVE' ? 'verify' : 'neutral'}
                    className="h-4 text-[8px]"
                  >
                    {ev.authority}
                  </Chip>
                </div>
                <div className="text-bone-500 truncate" title={ev.content_ref}>
                  REF: {ev.content_ref}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
};
