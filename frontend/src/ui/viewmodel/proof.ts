import type {
  SpeechProjection,
  ClaimProjection,
  EvidenceProjection,
} from '../../api/types';

export interface ResolvedClaimInProof {
  readonly claimId: string;
  readonly claim: ClaimProjection | null;
  readonly predicate: string;
  readonly state: string;
  readonly evidenceRule: string | null;
}

export interface ResolvedEvidenceInProof {
  readonly evidenceId: string;
  readonly evidence: EvidenceProjection | null;
  readonly source: string;
  readonly authority: string;
  readonly kind: string;
  readonly capturedAt: string | null;
  readonly contentRef: string | null;
}

export interface SpeechProofViewModel {
  readonly speechId: string;
  readonly templateId: string;
  readonly actType: string;
  readonly state: string;
  readonly requestedCertainty: string;
  readonly approvedPolicyId: string | null;
  readonly approvedThroughSequence: number | null;
  readonly supersedesSpeechId: string | null;
  readonly claims: readonly ResolvedClaimInProof[];
  readonly evidence: readonly ResolvedEvidenceInProof[];
  readonly approvedClaimVersions: Readonly<Record<string, string>>;
}

export function buildSpeechProof(
  speech: SpeechProjection,
  allClaims: readonly ClaimProjection[],
  allEvidence: readonly EvidenceProjection[],
): SpeechProofViewModel {
  const claimMap = new Map<string, ClaimProjection>();
  allClaims.forEach((c) => claimMap.set(c.claim_id, c));

  const evidenceMap = new Map<string, EvidenceProjection>();
  allEvidence.forEach((e) => evidenceMap.set(e.evidence_id, e));

  const resolvedClaims: ResolvedClaimInProof[] = speech.claim_ids.map((cid) => {
    const claim = claimMap.get(cid) ?? null;
    return {
      claimId: cid,
      claim,
      predicate: claim ? claim.predicate : 'not in projection',
      state: claim ? claim.state : 'UNKNOWN',
      evidenceRule: claim ? claim.required_evidence_rule : null,
    };
  });

  // Resolve evidence linked to the speech's claims
  const evidenceIds = new Set<string>();
  speech.claim_ids.forEach((cid) => {
    const claim = claimMap.get(cid);
    if (claim) {
      claim.supporting_evidence_ids.forEach((eid) => evidenceIds.add(eid));
    }
  });

  const resolvedEvidence: ResolvedEvidenceInProof[] = Array.from(evidenceIds).map((eid) => {
    const ev = evidenceMap.get(eid) ?? null;
    return {
      evidenceId: eid,
      evidence: ev,
      source: ev ? ev.source : 'not in projection',
      authority: ev ? ev.authority : 'UNKNOWN',
      kind: ev ? ev.kind : 'UNKNOWN',
      capturedAt: ev ? ev.captured_at : null,
      contentRef: ev ? ev.content_ref : null,
    };
  });

  return {
    speechId: speech.speech_id,
    templateId: speech.template_id,
    actType: speech.act_type,
    state: speech.state,
    requestedCertainty: speech.requested_certainty,
    approvedPolicyId: speech.approved_policy_id,
    approvedThroughSequence: speech.approved_through_sequence,
    supersedesSpeechId: speech.supersedes_speech_id,
    claims: resolvedClaims,
    evidence: resolvedEvidence,
    approvedClaimVersions: speech.approved_claim_versions ?? {},
  };
}
