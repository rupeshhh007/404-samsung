"""TRU-002: Canonical ClaimGraph evaluation policy.

Implements the ClaimEvaluator interface defined in:
- docs/contracts/INTERFACES.md (ClaimEvaluator.evaluate)
- docs/components/CLAIM_GRAPH.md
- docs/architecture/INVARIANTS.md (Invariant I9, FR-014)
- docs/architecture/STATE_MACHINES.md (Claim state transitions)

Key properties:
- Pure policy; deterministic; no I/O, no network, no wall-clock dependencies.
- Consumes authoritative physical world projections derived by EXE-005 (project_world).
- Does not mutate caller-owned models (SessionState, ClaimRecord, EffectRecord, EvidenceRecord).
- Generates canonical ClaimStateChanged events adhering to reducer state machines.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping, Sequence, Set, Tuple

from interlock.domain.enums import (
    ClaimState,
    EffectState,
    EvidenceAuthority,
    EvidenceSource,
    PlanStepKind,
    ToolOutcome,
)
from interlock.domain.events import ClaimStateChanged
from interlock.domain.models import (
    ClaimRecord,
    EffectRecord,
    EvidenceRecord,
)
from interlock.execution.effects import (
    PhysicalWorldView,
    WorldCertainty,
    project_world,
)

# Canonical Machine-Readable Evidence Rules (strictly declared, no fuzzy aliases)
RULE_APPOINTMENT_BOOKED = "appointment_booked"
RULE_APPOINTMENT_CANCELLED = "appointment_cancelled"
RULE_SLOT_AVAILABLE = "slot_available"
RULE_REQUEST_RECEIVED = "request_received"

CANONICAL_RULES: Set[str] = {
    RULE_APPOINTMENT_BOOKED,
    RULE_APPOINTMENT_CANCELLED,
    RULE_SLOT_AVAILABLE,
    RULE_REQUEST_RECEIVED,
}

# Canonical receipt evidence kinds and tool producers
CANONICAL_RECEIPT_KINDS: Set[str] = {
    "tool_acknowledgement",
}
CANONICAL_RECEIPT_PRODUCERS: Set[str] = {
    "appointment.book",
}
CANONICAL_TOOL_PRODUCERS: Set[str] = {
    "appointment.book",
    "appointment.cancel",
    "appointment.get",
}

# Canonical Legal Claim Transitions (STATE_MACHINES.md & reducer.py)
LEGAL_CLAIM_TRANSITIONS: Mapping[ClaimState, Set[ClaimState]] = {
    ClaimState.PROPOSED: {
        ClaimState.PENDING,
        ClaimState.STALE,
        ClaimState.SUPERSEDED,
    },
    ClaimState.PENDING: {
        ClaimState.CONFIRMED,
        ClaimState.CONTRADICTED,
        ClaimState.UNCERTAIN,
        ClaimState.STALE,
        ClaimState.SUPERSEDED,
    },
    ClaimState.UNCERTAIN: {
        ClaimState.CONFIRMED,
        ClaimState.CONTRADICTED,
        ClaimState.STALE,
        ClaimState.SUPERSEDED,
    },
    ClaimState.CONFIRMED: {
        ClaimState.STALE,
        ClaimState.SUPERSEDED,
    },
    ClaimState.CONTRADICTED: {
        ClaimState.STALE,
        ClaimState.SUPERSEDED,
    },
    ClaimState.STALE: {
        ClaimState.SUPERSEDED,
    },
    ClaimState.SUPERSEDED: set(),
}


def normalize_rule_name(rule: str) -> str:
    """Strictly validate rule against declared canonical identifiers.

    Arbitrary punctuation or fuzzy aliasing is not accepted.
    """
    if not isinstance(rule, str):
        return ""
    cleaned = rule.strip()
    if cleaned in CANONICAL_RULES:
        return cleaned
    return cleaned


def _match_slot(actual: Any, desired: Any) -> bool:
    """Exact slot matching without loose coercion.

    Supports:
    - Same-type exact equality for str
    - Same-type exact equality for datetime
    - Exact ISO-8601 string <-> datetime parsing if one is ISO string and other is datetime
    - ISO-8601 string <-> string normalization if both are strings
    All other type combinations fail closed.
    """
    if actual is None or desired is None:
        return False
    if type(actual) is type(desired) and actual == desired:
        return True

    if isinstance(actual, str) and isinstance(desired, str):
        try:
            return datetime.fromisoformat(actual.replace("Z", "+00:00")) == datetime.fromisoformat(desired.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            return False

    if isinstance(actual, datetime) and isinstance(desired, str):
        try:
            return actual == datetime.fromisoformat(desired.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            return False
    if isinstance(actual, str) and isinstance(desired, datetime):
        try:
            return datetime.fromisoformat(actual.replace("Z", "+00:00")) == desired
        except (ValueError, TypeError):
            return False

    return False


def _extract_claim_parameters(claim: ClaimRecord) -> dict[str, Any]:
    """Extract standard booking / appointment parameters from claim subject and object."""
    params: dict[str, Any] = {}

    if isinstance(claim.subject, dict):
        for key in (
            "center_id",
            "center",
            "slot",
            "requested_slot",
            "confirmed_slot",
            "provider_booking_id",
            "booking_id",
            "provider_request_id",
            "logical_action_id",
            "operation_id",
            "is_reconciliation",
            "plan_id",
        ):
            if key in claim.subject and claim.subject[key] is not None:
                params[key] = claim.subject[key]

    if isinstance(claim.object, dict):
        for key in (
            "center_id",
            "center",
            "slot",
            "requested_slot",
            "confirmed_slot",
            "provider_booking_id",
            "booking_id",
            "provider_request_id",
            "logical_action_id",
            "operation_id",
            "is_reconciliation",
            "plan_id",
        ):
            if key in claim.object and claim.object[key] is not None:
                params[key] = claim.object[key]

    if "center" in params and "center_id" not in params:
        params["center_id"] = params["center"]
    if "booking_id" in params and "provider_booking_id" not in params:
        params["provider_booking_id"] = params["booking_id"]
    if "slot" in params:
        if "requested_slot" not in params:
            params["requested_slot"] = params["slot"]
        if "confirmed_slot" not in params:
            params["confirmed_slot"] = params["slot"]

    return params


def _find_relevant_views(
    views: Sequence[PhysicalWorldView],
    effects: Mapping[str, EffectRecord],
    evidence: Mapping[str, EvidenceRecord],
    params: Mapping[str, Any],
) -> list[PhysicalWorldView]:
    """Identify physical views relevant to the claim parameters using hierarchical physical identity.

    Hierarchical selection:
    1. If provider_booking_id is supplied: select exact provider_effect_id. Do not discard
       because center or slot differ; proposition differences are compared later.
    2. Else if provider_request_id is supplied: scope to views containing effects created by that request.
    3. Else if logical_action_id is supplied: scope to that logical action.
    Fails closed (returns empty list) if identity is incomplete or only center_id is supplied.
    """
    target_booking_id = params.get("provider_booking_id")
    target_req_id = params.get("provider_request_id")
    target_action_id = params.get("logical_action_id")

    # 1. Exact physical booking identity
    if target_booking_id:
        return [view for view in views if view.provider_effect_id == target_booking_id]

    # 2. Scoped by provider_request_id lineage
    if target_req_id:
        matching_booking_ids: set[str] = set()
        for eff in effects.values():
            for eid in eff.evidence_ids:
                ev = evidence.get(eid)
                if ev and ev.provenance.get("provider_request_id") == target_req_id:
                    matching_booking_ids.add(eff.provider_effect_id)
        if matching_booking_ids:
            return [view for view in views if view.provider_effect_id in matching_booking_ids]

    # 3. Scoped logical action identity
    if target_action_id:
        return [view for view in views if target_action_id in view.logical_action_ids]

    # Incomplete identity fails closed: never match unrelated bookings by center alone
    return []


def _is_canonical_booking_evidence(
    ev: EvidenceRecord,
    eff: EffectRecord,
    expected_request_id: str | None = None,
    expected_operation_id: str | None = None,
) -> bool:
    """Validate supporting booking confirmation evidence according to canonical EXE-005 producer semantics."""
    if not isinstance(ev, EvidenceRecord):
        return False
    if ev.source != EvidenceSource.TOOL:
        return False
    if ev.authority != EvidenceAuthority.AUTHORITATIVE:
        return False
    if ev.kind != "booking_confirmation":
        return False

    prov = ev.provenance
    if prov.get("tool_name") != "appointment.book":
        return False
    if prov.get("provider_effect_id") != eff.provider_effect_id:
        return False
    if prov.get("operation_id") != eff.operation_id:
        return False
    if expected_operation_id is not None and eff.operation_id != expected_operation_id:
        return False
    if expected_operation_id is not None and prov.get("operation_id") != expected_operation_id:
        return False

    req_id = prov.get("provider_request_id")
    if not isinstance(req_id, str) or not req_id.strip():
        return False
    if expected_request_id is not None and req_id != expected_request_id:
        return False

    return True


def _find_historical_booking_write(
    view: PhysicalWorldView,
    effects: Mapping[str, EffectRecord],
    evidence: Mapping[str, EvidenceRecord],
    expected_request_id: str | None = None,
    expected_operation_id: str | None = None,
    *,
    expected_booking_id: str | None = None,
    expected_center: str | None = None,
    expected_slot: Any = None,
    **kwargs: Any,
) -> tuple[EffectRecord, EvidenceRecord] | None:
    """Locate the historical authoritative booking write lineage for a physical booking.

    Requires:
    - exact provider_booking_id
    - exact provider_request_id
    - exact operation_id when claim supplies one
    - exact center_id
    - exact requested_slot == desired slot
    - exact confirmed_slot == desired slot
    - effect_type == "appointment.booking"
    - authoritative COMMITTED historical effect
    - canonical booking_confirmation evidence
    - canonical producer tool ("appointment.book")
    - evidence provenance correlated to that exact historical effect/operation
    - arrival/iteration order independence (fails closed on conflicting ambiguous candidates)
    """
    req_id = expected_request_id or kwargs.get("provider_request_id")
    op_id = expected_operation_id or kwargs.get("operation_id")
    target_booking_id = expected_booking_id or kwargs.get("provider_booking_id") or view.provider_effect_id
    target_center = expected_center or kwargs.get("center_id")
    target_slot = expected_slot if expected_slot is not None else kwargs.get("slot")

    if not target_booking_id or not req_id or target_slot is None:
        return None

    candidate_eff_ids: set[str] = set()
    for obs_id in view.observation_ids:
        if obs_id != view.current_effect_id:
            candidate_eff_ids.add(obs_id)

    for eff_id, eff in effects.items():
        if eff_id != view.current_effect_id and eff.provider_effect_id == target_booking_id:
            candidate_eff_ids.add(eff_id)

    valid_candidates: list[tuple[EffectRecord, EvidenceRecord]] = []

    for eff_id in sorted(candidate_eff_ids):
        eff = effects.get(eff_id)
        if eff is None:
            continue

        if eff.effect_type != "appointment.booking":
            continue
        if eff.state != EffectState.COMMITTED:
            continue
        if eff.authority != EvidenceAuthority.AUTHORITATIVE:
            continue

        if eff.provider_effect_id != target_booking_id:
            continue

        eff_center = eff.subject.get("center_id") or eff.subject.get("center")
        if not eff_center:
            continue
        if target_center and eff_center != target_center:
            continue

        eff_req_slot = eff.parameters.get("requested_slot")
        eff_conf_slot = eff.parameters.get("confirmed_slot")
        if eff_req_slot is None or eff_conf_slot is None:
            continue
        if not _match_slot(eff_req_slot, target_slot):
            continue
        if not _match_slot(eff_conf_slot, target_slot):
            continue

        if op_id and eff.operation_id != op_id:
            continue

        for eid in sorted(eff.evidence_ids):
            ev = evidence.get(eid)
            if ev and _is_canonical_booking_evidence(
                ev, eff, req_id, op_id
            ):
                valid_candidates.append((eff, ev))

    if not valid_candidates:
        return None

    # Check for ambiguous / conflicting operation identity among candidates proving the proposition
    distinct_ops = {c_eff.operation_id for c_eff, _ in valid_candidates}
    distinct_reqs = {c_ev.provenance.get("provider_request_id") for _, c_ev in valid_candidates}
    if len(distinct_ops) > 1 or len(distinct_reqs) > 1:
        return None

    # Deterministic selection among equivalent candidates
    valid_candidates.sort(key=lambda pair: (pair[0].effect_id, pair[1].evidence_id))
    return valid_candidates[0]


def _is_canonical_cancellation_evidence(
    ev: EvidenceRecord,
    eff: EffectRecord,
    expected_operation_id: str | None = None,
    predecessor: EffectRecord | None = None,
) -> bool:
    """Validate supporting cancellation evidence according to canonical EXE-005 producer semantics."""
    if not isinstance(ev, EvidenceRecord):
        return False
    if ev.source != EvidenceSource.TOOL:
        return False
    if ev.authority != EvidenceAuthority.AUTHORITATIVE:
        return False

    prov = ev.provenance
    req_id = prov.get("provider_request_id")
    if not isinstance(req_id, str) or not req_id.strip():
        return False

    op_id = prov.get("operation_id")
    if not isinstance(op_id, str) or not op_id.strip():
        return False

    if ev.kind == "booking_compensation":
        if prov.get("tool_name") != "appointment.cancel":
            return False
        if prov.get("provider_effect_id") != eff.provider_effect_id:
            return False

        # Blocker #2: Validate cancel producer correlation separately from predecessor booking lineage.
        # Do not require cancel evidence operation_id to equal the compensated booking effect's original operation_id.
        if expected_operation_id is not None:
            pred_op = predecessor.operation_id if predecessor else eff.operation_id
            if (
                op_id != expected_operation_id
                and eff.operation_id != expected_operation_id
                and pred_op != expected_operation_id
            ):
                return False
        return True

    return False


def _transition_event(
    claim: ClaimRecord,
    target_state: ClaimState,
    evidence_ids: Sequence[str],
    reason: str,
    known_evidence: Mapping[str, EvidenceRecord],
) -> ClaimStateChanged | None:
    """Construct a canonical ClaimStateChanged event if legal, or fallback to STALE."""
    if target_state == claim.state:
        return None

    legal_targets = LEGAL_CLAIM_TRANSITIONS.get(claim.state, set())
    if target_state not in legal_targets:
        if claim.state == ClaimState.PROPOSED and ClaimState.PENDING in legal_targets:
            target_state = ClaimState.PENDING
            reason = f"Claim staged through PENDING before final verification: {reason}"
        elif ClaimState.STALE in legal_targets:
            target_state = ClaimState.STALE
            reason = (
                f"Transitioned to STALE because target {target_state} is illegal from {claim.state}: {reason}"
            )
        else:
            return None

    valid_eids = sorted({eid for eid in evidence_ids if eid in known_evidence})

    if target_state == ClaimState.CONFIRMED and not valid_eids:
        if ClaimState.PENDING in legal_targets:
            target_state = ClaimState.PENDING
            reason = "Missing supporting evidence required for CONFIRMED state"
        elif ClaimState.UNCERTAIN in legal_targets:
            target_state = ClaimState.UNCERTAIN
            reason = "Missing supporting evidence required for CONFIRMED state"
        else:
            return None

    return ClaimStateChanged(
        claim_id=claim.claim_id,
        **{"from": claim.state, "to": target_state},
        evidence_ids=valid_eids,
        reason=reason,
    )


def _evaluate_appointment_booked(
    claim: ClaimRecord,
    effects: Mapping[str, EffectRecord],
    evidence: Mapping[str, EvidenceRecord],
    views: Sequence[PhysicalWorldView],
    params: Mapping[str, Any],
) -> tuple[ClaimState, list[str], str]:
    # Reconciliation check (Blocker #3):
    is_reconciliation = bool(params.get("is_reconciliation", False) or "plan_id" in params)
    if is_reconciliation:
        desired_plan_id = params.get("plan_id")
        desired_div_id = params.get("divergence_id")
        desired_booking_id = params.get("provider_booking_id")
        desired_center = params.get("center_id")
        desired_slot = params.get("confirmed_slot") or params.get("requested_slot") or params.get("slot")

        matching_vf_evs: list[EvidenceRecord] = []
        for ev in evidence.values():
            if ev.source != EvidenceSource.TOOL or ev.authority != EvidenceAuthority.AUTHORITATIVE:
                continue
            prov = ev.provenance
            step_kind = prov.get("step_kind") or prov.get("plan_step_kind")
            step_id = str(prov.get("step_id", "")).lower()
            kind = ev.kind.lower()

            is_vf = (
                step_kind in ("VERIFY_FINAL", PlanStepKind.VERIFY_FINAL)
                or kind in ("reconciliation_verify_final", "reconciliation_verification")
                or "verify_final" in step_id
                or (prov.get("tool_name") == "appointment.get" and step_kind == "VERIFY_FINAL")
            )
            if not is_vf:
                continue

            # Check plan_id correlation
            ev_plan_id = prov.get("plan_id")
            if desired_plan_id is not None:
                if ev_plan_id != desired_plan_id:
                    continue
            elif ev_plan_id is not None:
                pass

            # Check divergence_id correlation
            ev_div_id = prov.get("divergence_id")
            if desired_div_id is not None and ev_div_id is not None and ev_div_id != desired_div_id:
                continue

            # Check resource / provider_effect_id correlation
            ev_booking_id = prov.get("provider_effect_id") or prov.get("provider_booking_id")
            if desired_booking_id is not None and ev_booking_id is not None and ev_booking_id != desired_booking_id:
                continue

            matching_vf_evs.append(ev)

        if not matching_vf_evs:
            return (
                ClaimState.PENDING,
                [],
                "Reconciliation booking awaiting exact matching authoritative VERIFY_FINAL evidence",
            )

        vf_ev = sorted(matching_vf_evs, key=lambda x: x.evidence_id)[0]

        # Check physical world projection via EXE-005
        relevant_views = _find_relevant_views(views, effects, evidence, params)
        if not relevant_views:
            vf_booking_id = vf_ev.provenance.get("provider_effect_id") or vf_ev.provenance.get("provider_booking_id")
            if vf_booking_id:
                relevant_views = [v for v in views if v.provider_effect_id == vf_booking_id]

        if not relevant_views:
            return (
                ClaimState.PENDING,
                [vf_ev.evidence_id],
                "Reconciliation booking awaiting physical world observation",
            )

        # Unresolved world guard (Probe 15)
        if any(view.certainty == WorldCertainty.UNRESOLVED for view in relevant_views):
            return (
                ClaimState.PENDING,
                [],
                "Current physical world projection is UNRESOLVED; cannot confirm reconciliation booking",
            )

        if any(view.duplicate_physical_effect for view in relevant_views):
            return (
                ClaimState.UNCERTAIN,
                [vf_ev.evidence_id],
                "Duplicate physical effects observed for reconciliation resource",
            )

        view = relevant_views[0]
        if view.certainty != WorldCertainty.CONFIRMED or not view.current_effect_id:
            return (
                ClaimState.PENDING,
                [vf_ev.evidence_id],
                "Reconciliation booking physical world projection is not confirmed",
            )

        eff = effects.get(view.current_effect_id)
        if not eff or eff.state != EffectState.COMMITTED or eff.authority != EvidenceAuthority.AUTHORITATIVE:
            return (
                ClaimState.PENDING,
                [vf_ev.evidence_id],
                "Reconciliation booking effect is not an authoritative committed effect",
            )

        vf_center = vf_ev.provenance.get("center_id") or vf_ev.provenance.get("center")
        if desired_center is not None and vf_center is not None and vf_center != desired_center:
            eids = sorted(set([vf_ev.evidence_id, *eff.evidence_ids]))
            return (
                ClaimState.CONTRADICTED,
                eids,
                f"Reconciliation VERIFY_FINAL center '{vf_center}' contradicts desired center '{desired_center}'",
            )

        vf_slot = vf_ev.provenance.get("confirmed_slot") or vf_ev.provenance.get("slot")
        if desired_slot is not None and vf_slot is not None and not _match_slot(vf_slot, desired_slot):
            eids = sorted(set([vf_ev.evidence_id, *eff.evidence_ids]))
            return (
                ClaimState.CONTRADICTED,
                eids,
                f"Reconciliation VERIFY_FINAL slot '{vf_slot}' contradicts desired slot '{desired_slot}'",
            )

        eff_center = eff.subject.get("center_id") or eff.subject.get("center")
        if desired_center is not None and eff_center != desired_center:
            eids = sorted(set([vf_ev.evidence_id, *eff.evidence_ids]))
            return (
                ClaimState.CONTRADICTED,
                eids,
                f"Reconciliation booking center '{eff_center}' contradicts desired center '{desired_center}'",
            )

        eff_slot = eff.parameters.get("confirmed_slot") or eff.parameters.get("requested_slot")
        if desired_slot is not None and not _match_slot(eff_slot, desired_slot):
            eids = sorted(set([vf_ev.evidence_id, *eff.evidence_ids]))
            return (
                ClaimState.CONTRADICTED,
                eids,
                f"Reconciliation booking slot '{eff_slot}' contradicts desired slot '{desired_slot}'",
            )

        confirm_eids = sorted(set([vf_ev.evidence_id, *eff.evidence_ids]))
        return (
            ClaimState.CONFIRMED,
            confirm_eids,
            f"Authoritative reconciliation booking confirmed for center '{eff_center}' / slot '{eff_slot}' (booking ID: '{eff.provider_effect_id}') via VERIFY_FINAL",
        )

    desired_slot = params.get("confirmed_slot") or params.get("requested_slot") or params.get("slot")
    desired_center = params.get("center_id")
    desired_req_id = params.get("provider_request_id")
    desired_booking_id = params.get("provider_booking_id")
    desired_op_id = params.get("operation_id")

    # Blocker #4: Required claim identity completeness check
    if not desired_booking_id and not desired_req_id:
        return (
            ClaimState.PENDING,
            [],
            "appointment_booked proposition lacks required booking identity or request lineage",
        )
    if not desired_center or desired_slot is None:
        return (
            ClaimState.PENDING,
            [],
            "appointment_booked proposition lacks required center or slot parameter",
        )

    relevant_views = _find_relevant_views(views, effects, evidence, params)

    if not relevant_views:
        return (
            ClaimState.PENDING,
            [],
            "Awaiting authoritative external booking observation",
        )

    # Invariant: duplicate physical effects fail closed
    if any(view.duplicate_physical_effect for view in relevant_views):
        all_eids: set[str] = set()
        for v in relevant_views:
            for obs_id in v.observation_ids:
                eff = effects.get(obs_id)
                if eff:
                    all_eids.update(eff.evidence_ids)
        return (
            ClaimState.UNCERTAIN,
            sorted(all_eids),
            "Duplicate physical effects observed for logical action; cannot safely confirm booking",
        )

    # Invariant: unresolved physical certainty cannot confirm
    if all(view.certainty == WorldCertainty.UNRESOLVED for view in relevant_views):
        all_eids = set()
        for v in relevant_views:
            for obs_id in v.observation_ids:
                eff = effects.get(obs_id)
                if eff and eff.authority == EvidenceAuthority.AUTHORITATIVE:
                    all_eids.update(eff.evidence_ids)
        return (
            ClaimState.UNCERTAIN,
            sorted(all_eids),
            "Current physical world projection is UNRESOLVED due to conflicting authoritative observations",
        )

    matching_confirms: list[tuple[PhysicalWorldView, EffectRecord, list[str], bool]] = []
    mismatched_confirms: list[tuple[PhysicalWorldView, EffectRecord, list[str]]] = []
    compensated_views: list[tuple[PhysicalWorldView, EffectRecord]] = []

    for view in relevant_views:
        if view.certainty == WorldCertainty.CONFIRMED and view.current_effect_id:
            eff = effects.get(view.current_effect_id)
            if (
                eff
                and eff.effect_type == "appointment.booking"
                and eff.state == EffectState.COMMITTED
                and eff.authority == EvidenceAuthority.AUTHORITATIVE
            ):
                # Validate provider_booking_id
                eff_booking_id = eff.provider_effect_id
                if not isinstance(eff_booking_id, str) or not eff_booking_id.strip():
                    continue
                if desired_booking_id and eff_booking_id != desired_booking_id:
                    continue

                # Validate center_id
                eff_center = eff.subject.get("center_id") or eff.subject.get("center")
                if not isinstance(eff_center, str) or not eff_center.strip():
                    continue

                # Validate slots
                eff_req_slot = eff.parameters.get("requested_slot")
                eff_conf_slot = eff.parameters.get("confirmed_slot")
                if eff_req_slot is None or eff_conf_slot is None:
                    continue

                center_ok = desired_center is None or eff_center == desired_center
                slot_ok = (
                    desired_slot is not None
                    and _match_slot(eff_conf_slot, desired_slot)
                    and _match_slot(eff_req_slot, desired_slot)
                )

                if not (center_ok and slot_ok):
                    valid_eids = [
                        eid for eid in eff.evidence_ids
                        if eid in evidence and evidence[eid].authority == EvidenceAuthority.AUTHORITATIVE
                    ]
                    mismatched_confirms.append((view, eff, valid_eids))
                    continue

                # Center and slot match the physical world view.
                # Now verify write request lineage and operation correlation.
                direct_booking_evs: list[EvidenceRecord] = []
                is_verification_resolved = False

                for eid in eff.evidence_ids:
                    ev = evidence.get(eid)
                    if ev is None:
                        continue
                    if ev.kind == "booking_confirmation":
                        if _is_canonical_booking_evidence(
                            ev, eff, desired_req_id, desired_op_id
                        ):
                            direct_booking_evs.append(ev)
                    elif ev.kind == "world_effect_verification":
                        prov = ev.provenance
                        if (
                            ev.source == EvidenceSource.TOOL
                            and ev.authority == EvidenceAuthority.AUTHORITATIVE
                            and prov.get("tool_name") == "appointment.get"
                            and prov.get("provider_effect_id") == eff.provider_effect_id
                        ):
                            is_verification_resolved = True

                if direct_booking_evs:
                    canonical_eids = [ev.evidence_id for ev in direct_booking_evs]
                    matching_confirms.append((view, eff, canonical_eids, False))
                elif is_verification_resolved:
                    hist = _find_historical_booking_write(
                        view,
                        effects,
                        evidence,
                        desired_req_id,
                        desired_op_id,
                        expected_booking_id=desired_booking_id or view.provider_effect_id,
                        expected_center=desired_center or eff_center,
                        expected_slot=desired_slot,
                    )
                    if hist is not None:
                        hist_eff, hist_ev = hist
                        verify_eids = [
                            eid
                            for eid in eff.evidence_ids
                            if eid in evidence
                            and evidence[eid].authority == EvidenceAuthority.AUTHORITATIVE
                        ]
                        canonical_eids = sorted({hist_ev.evidence_id, *verify_eids})
                        matching_confirms.append((view, eff, canonical_eids, False))
                    else:
                        matching_confirms.append((view, eff, [], True))

        elif view.certainty == WorldCertainty.COMPENSATED and view.current_effect_id:
            eff = effects.get(view.current_effect_id)
            if eff and eff.effect_type == "appointment.booking":
                compensated_views.append((view, eff))

    if matching_confirms:
        if len(matching_confirms) > 1:
            all_eids = set()
            for _, eff, eids, _ in matching_confirms:
                all_eids.update(eids)
            return (
                ClaimState.UNCERTAIN,
                sorted(all_eids),
                "Multiple matching physical bookings found; cannot disambiguate without provider booking ID",
            )

        view, eff, canonical_eids, missing_lineage = matching_confirms[0]

        if missing_lineage:
            return (
                ClaimState.PENDING,
                [],
                "original booking-request lineage for verification-resolved claim requires cross-owner contract confirmation",
            )

        if not desired_req_id:
            return (
                ClaimState.PENDING,
                [],
                "appointment_booked claim lacks required provider_request_id to prove original booking request identity",
            )

        eff_center = eff.subject.get("center_id") or eff.subject.get("center")
        eff_conf_slot = eff.parameters.get("confirmed_slot")
        return (
            ClaimState.CONFIRMED,
            sorted(set(canonical_eids)),
            f"Authoritative booking confirmed at center '{eff_center}' for slot '{eff_conf_slot}' (booking ID: '{eff.provider_effect_id}')",
        )

    if mismatched_confirms:
        view, eff, canonical_eids = mismatched_confirms[0]
        eff_center = eff.subject.get("center_id") or eff.subject.get("center")
        eff_conf_slot = eff.parameters.get("confirmed_slot")
        return (
            ClaimState.CONTRADICTED,
            sorted(set(canonical_eids)),
            f"Authoritative booking confirmed for center '{eff_center}' / slot '{eff_conf_slot}', contradicting desired proposition",
        )

    if compensated_views:
        view, eff = compensated_views[0]
        valid_evidence_ids = [
            eid
            for eid in eff.evidence_ids
            if eid in evidence and evidence[eid].authority == EvidenceAuthority.AUTHORITATIVE
        ]
        return (
            ClaimState.CONTRADICTED,
            sorted(set(valid_evidence_ids)),
            f"Appointment booking '{view.provider_effect_id}' has been compensated (cancelled)",
        )

    return (
        ClaimState.PENDING,
        [],
        "Awaiting authoritative external booking confirmation",
    )


def _evaluate_appointment_cancelled(
    claim: ClaimRecord,
    effects: Mapping[str, EffectRecord],
    evidence: Mapping[str, EvidenceRecord],
    views: Sequence[PhysicalWorldView],
    params: Mapping[str, Any],
) -> tuple[ClaimState, list[str], str]:
    desired_booking_id = params.get("provider_booking_id")
    desired_center = params.get("center_id")
    desired_slot = params.get("confirmed_slot") or params.get("slot")
    desired_op_id = params.get("operation_id")

    relevant_views = _find_relevant_views(views, effects, evidence, params)

    if not relevant_views:
        return (
            ClaimState.PENDING,
            [],
            "Awaiting authoritative external cancellation observation",
        )

    for view in relevant_views:
        if desired_booking_id and view.provider_effect_id != desired_booking_id:
            continue

        if view.certainty == WorldCertainty.COMPENSATED and view.current_effect_id:
            eff = effects.get(view.current_effect_id)
            if (
                eff
                and eff.effect_type == "appointment.booking"
                and eff.state == EffectState.COMPENSATED
                and eff.authority == EvidenceAuthority.AUTHORITATIVE
            ):
                # Blocker #2: Validate predecessor booking lineage
                if not eff.supersedes_effect_id or eff.supersedes_effect_id not in effects:
                    continue

                pred = effects[eff.supersedes_effect_id]
                if (
                    pred.state != EffectState.COMMITTED
                    or pred.authority != EvidenceAuthority.AUTHORITATIVE
                    or pred.effect_type != "appointment.booking"
                    or pred.provider_effect_id != eff.provider_effect_id
                ):
                    continue

                eff_center = eff.subject.get("center_id") or eff.subject.get("center")
                pred_center = pred.subject.get("center_id") or pred.subject.get("center")
                if desired_center and (eff_center != desired_center or pred_center != desired_center):
                    continue

                eff_slot = eff.parameters.get("confirmed_slot") or eff.parameters.get("requested_slot")
                pred_slot = pred.parameters.get("confirmed_slot") or pred.parameters.get("requested_slot")
                if desired_slot and (not _match_slot(eff_slot, desired_slot) or not _match_slot(pred_slot, desired_slot)):
                    continue

                valid_eids = [
                    eid
                    for eid in eff.evidence_ids
                    if eid in evidence
                    and _is_canonical_cancellation_evidence(evidence[eid], eff, desired_op_id, pred)
                ]
                if valid_eids:
                    return (
                        ClaimState.CONFIRMED,
                        sorted(set(valid_eids)),
                        f"Authoritative cancellation (compensation) confirmed for booking '{view.provider_effect_id}'",
                    )

        if view.certainty == WorldCertainty.CONFIRMED and view.current_effect_id:
            eff = effects.get(view.current_effect_id)
            if (
                eff
                and eff.effect_type == "appointment.booking"
                and eff.state == EffectState.COMMITTED
                and eff.authority == EvidenceAuthority.AUTHORITATIVE
            ):
                if desired_op_id and eff.operation_id != desired_op_id:
                    continue
                eff_center = eff.subject.get("center_id") or eff.subject.get("center")
                if desired_center and eff_center != desired_center:
                    continue

                eff_slot = eff.parameters.get("confirmed_slot") or eff.parameters.get("requested_slot")
                if desired_slot and not _match_slot(eff_slot, desired_slot):
                    continue

                valid_eids = [
                    eid
                    for eid in eff.evidence_ids
                    if eid in evidence and evidence[eid].authority == EvidenceAuthority.AUTHORITATIVE
                ]
                return (
                    ClaimState.CONTRADICTED,
                    sorted(set(valid_eids)),
                    f"Appointment booking '{view.provider_effect_id}' remains actively COMMITTED, contradicting cancellation",
                )

        if view.certainty == WorldCertainty.UNRESOLVED:
            matches_claim = False
            for obs_id in view.observation_ids:
                eff = effects.get(obs_id)
                if eff:
                    eff_center = eff.subject.get("center_id") or eff.subject.get("center")
                    eff_slot = eff.parameters.get("confirmed_slot") or eff.parameters.get("requested_slot")
                    center_match = desired_center is None or eff_center == desired_center
                    slot_match = desired_slot is None or _match_slot(eff_slot, desired_slot)
                    if center_match and slot_match:
                        matches_claim = True
                        break
            if not matches_claim:
                continue

            all_eids = set()
            for obs_id in view.observation_ids:
                eff = effects.get(obs_id)
                if eff and eff.authority == EvidenceAuthority.AUTHORITATIVE:
                    all_eids.update(eff.evidence_ids)
            return (
                ClaimState.UNCERTAIN,
                sorted(all_eids),
                "Physical world state is unresolved; cannot confirm cancellation",
            )

    return (
        ClaimState.PENDING,
        [],
        "Awaiting authoritative compensation confirmation proving cancellation",
    )


def _evaluate_slot_available(
    claim: ClaimRecord,
    evidence: Mapping[str, EvidenceRecord],
    params: Mapping[str, Any],
    as_of: datetime | None,
) -> tuple[ClaimState, list[str], str]:
    desired_slot = params.get("slot") or params.get("requested_slot")
    desired_center = params.get("center_id")

    matching_authoritative: list[EvidenceRecord] = []
    contradicting_authoritative: list[EvidenceRecord] = []

    for ev in evidence.values():
        if ev.source != EvidenceSource.TOOL or ev.authority != EvidenceAuthority.AUTHORITATIVE:
            continue

        kind = ev.kind.lower()
        if kind not in ("slot_available", "slot_availability", "availability"):
            continue

        prov = ev.provenance
        center = prov.get("center_id") or prov.get("center")
        if desired_center and center != desired_center:
            continue

        # 1. First scope evidence to exact center + exact slot
        slots = prov.get("available_slots") or prov.get("slots")
        is_avail = prov.get("available")
        ev_slot = prov.get("slot")

        slot_matches_positive = False
        slot_matches_negative = False

        if ev_slot is not None:
            if _match_slot(ev_slot, desired_slot):
                if is_avail is True:
                    slot_matches_positive = True
                elif is_avail is False:
                    slot_matches_negative = True
        elif slots is not None and isinstance(slots, (list, tuple)):
            if any(_match_slot(s, desired_slot) for s in slots):
                slot_matches_positive = True
            elif prov.get("exhaustive") is True:
                slot_matches_negative = True
        elif desired_slot is None:
            if is_avail is True:
                slot_matches_positive = True
            elif is_avail is False:
                slot_matches_negative = True

        if not slot_matches_positive and not slot_matches_negative:
            continue

        # 2. Determine whether that scoped evidence is deterministically fresh
        # Freshness applies symmetrically to BOTH positive and negative evidence.
        if ev.expires_at is None or as_of is None or ev.expires_at <= as_of:
            continue

        # 3. Only fresh authoritative evidence participates
        if slot_matches_positive:
            matching_authoritative.append(ev)
        if slot_matches_negative:
            contradicting_authoritative.append(ev)

    # Conflicting authoritative availability check
    if matching_authoritative and contradicting_authoritative:
        conflicting_eids = sorted({ev.evidence_id for ev in matching_authoritative + contradicting_authoritative})
        return (
            ClaimState.UNCERTAIN,
            conflicting_eids,
            f"Authoritative availability evidence contains conflicting propositions for center '{desired_center}' / slot '{desired_slot}'",
        )

    if matching_authoritative:
        matching_authoritative.sort(key=lambda x: x.evidence_id)
        return (
            ClaimState.CONFIRMED,
            [matching_authoritative[0].evidence_id],
            f"Fresh authoritative availability confirmed for center '{desired_center}' / slot '{desired_slot}'",
        )

    if contradicting_authoritative:
        contradicting_authoritative.sort(key=lambda x: x.evidence_id)
        return (
            ClaimState.CONTRADICTED,
            [contradicting_authoritative[0].evidence_id],
            f"Authoritative availability check proved slot '{desired_slot}' is unavailable at center '{desired_center}'",
        )

    return (
        ClaimState.PENDING,
        [],
        "Awaiting fresh authoritative availability evidence",
    )


def _evaluate_request_received(
    claim: ClaimRecord,
    evidence: Mapping[str, EvidenceRecord],
    params: Mapping[str, Any],
) -> tuple[ClaimState, list[str], str]:
    desired_req_id = params.get("provider_request_id")
    desired_op_id = params.get("operation_id")

    receipt_records: list[EvidenceRecord] = []

    for ev in evidence.values():
        if ev.source != EvidenceSource.TOOL:
            continue

        if ev.authority not in (EvidenceAuthority.AUTHORITATIVE, EvidenceAuthority.NON_AUTHORITATIVE):
            continue

        if ev.kind not in CANONICAL_RECEIPT_KINDS:
            continue

        prov = ev.provenance
        tool_name = prov.get("tool_name")
        if not isinstance(tool_name, str) or tool_name not in CANONICAL_RECEIPT_PRODUCERS:
            continue

        req_id = prov.get("provider_request_id")
        if not isinstance(req_id, str) or not req_id.strip():
            continue

        if desired_req_id and req_id != desired_req_id:
            continue

        op_id = prov.get("operation_id")
        if desired_op_id and op_id != desired_op_id:
            continue

        receipt_records.append(ev)

    if receipt_records:
        receipt_records.sort(key=lambda x: x.evidence_id)
        return (
            ClaimState.CONFIRMED,
            [receipt_records[0].evidence_id],
            f"Provider acknowledgement recorded for request '{desired_req_id or receipt_records[0].evidence_id}'",
        )

    return (
        ClaimState.PENDING,
        [],
        "Awaiting canonical provider request receipt evidence",
    )


def _evaluate_unknown_rule(
    claim: ClaimRecord,
    rule_name: str,
) -> tuple[ClaimState, list[str], str]:
    return (
        ClaimState.PENDING,
        [],
        f"Unsupported or unknown claim rule '{rule_name}'; fails closed without confirmation",
    )


class ClaimEvaluator:
    """Canonical ClaimGraph evaluation policy (TRU-002).

    Deterministic, pure policy evaluation of ClaimRecord propositions against
    authoritative physical world projections (EXE-005) and evidence records (TRU-001).
    """

    def evaluate(
        self,
        claim: ClaimRecord,
        *args: Any,
        effects: Mapping[str, EffectRecord] | Sequence[EffectRecord] | None = None,
        evidence: Mapping[str, EvidenceRecord] | Sequence[EvidenceRecord] | None = None,
        sequence: int | None = None,
        as_of: datetime | None = None,
        active_intent_revision_id: str | None = None,
        **kwargs: Any,
    ) -> tuple[ClaimStateChanged, ...]:
        """Evaluate a ClaimRecord against world effects and evidence snapshots.

        Returns a tuple containing at most one canonical ClaimStateChanged event if
        a legal state change is required, or an empty tuple if the claim is unchanged.
        """
        if not isinstance(claim, ClaimRecord):
            if isinstance(claim, dict):
                claim = ClaimRecord.model_validate(claim)
            else:
                raise TypeError(f"Expected ClaimRecord, got {type(claim).__name__}")

        pos_effects = effects
        pos_evidence = evidence
        pos_sequence = sequence

        for arg in args:
            if isinstance(arg, int) and pos_sequence is None:
                pos_sequence = arg
            elif isinstance(arg, datetime) and as_of is None:
                as_of = arg
            elif isinstance(arg, (dict, list, tuple)):
                sample = None
                if isinstance(arg, dict) and arg:
                    sample = next(iter(arg.values()))
                elif isinstance(arg, (list, tuple)) and arg:
                    sample = arg[0]

                if isinstance(sample, EffectRecord) and pos_effects is None:
                    pos_effects = arg
                elif isinstance(sample, EvidenceRecord) and pos_evidence is None:
                    pos_evidence = arg
                elif pos_effects is None and pos_evidence is not None:
                    pos_effects = arg
                elif pos_evidence is None and pos_effects is not None:
                    pos_evidence = arg
                elif pos_effects is None:
                    pos_effects = arg
                elif pos_evidence is None:
                    pos_evidence = arg

        if pos_effects is None and "known_effects" in kwargs:
            pos_effects = kwargs["known_effects"]
        if pos_evidence is None and "known_evidence" in kwargs:
            pos_evidence = kwargs["known_evidence"]

        effects_map: dict[str, EffectRecord] = {}
        if isinstance(pos_effects, Mapping):
            effects_map = {k: v for k, v in pos_effects.items() if isinstance(v, EffectRecord)}
        elif isinstance(pos_effects, Sequence):
            effects_map = {e.effect_id: e for e in pos_effects if isinstance(e, EffectRecord)}

        evidence_map: dict[str, EvidenceRecord] = {}
        if isinstance(pos_evidence, Mapping):
            evidence_map = {k: v for k, v in pos_evidence.items() if isinstance(v, EvidenceRecord)}
        elif isinstance(pos_evidence, Sequence):
            evidence_map = {e.evidence_id: e for e in pos_evidence if isinstance(e, EvidenceRecord)}

        # Intent revision supersession
        if (
            active_intent_revision_id is not None
            and claim.intent_revision_id != active_intent_revision_id
            and claim.state != ClaimState.SUPERSEDED
        ):
            event = _transition_event(
                claim,
                ClaimState.SUPERSEDED,
                [],
                f"Claim intent revision '{claim.intent_revision_id}' superseded by active revision '{active_intent_revision_id}'",
                evidence_map,
            )
            return (event,) if event is not None else ()

        rule_name = normalize_rule_name(claim.required_evidence_rule)
        params = _extract_claim_parameters(claim)

        # Authoritative physical world projection via EXE-005
        views = project_world(effects_map, evidence_map)

        if rule_name == RULE_APPOINTMENT_BOOKED:
            target_state, eids, reason = _evaluate_appointment_booked(
                claim, effects_map, evidence_map, views, params
            )
        elif rule_name == RULE_APPOINTMENT_CANCELLED:
            target_state, eids, reason = _evaluate_appointment_cancelled(
                claim, effects_map, evidence_map, views, params
            )
        elif rule_name == RULE_SLOT_AVAILABLE:
            target_state, eids, reason = _evaluate_slot_available(
                claim, evidence_map, params, as_of
            )
        elif rule_name == RULE_REQUEST_RECEIVED:
            target_state, eids, reason = _evaluate_request_received(
                claim, evidence_map, params
            )
        else:
            target_state, eids, reason = _evaluate_unknown_rule(claim, rule_name)

        # Blocker #1: PROPOSED claims must be staged through PENDING before final truth states
        if claim.state == ClaimState.PROPOSED:
            if target_state in {ClaimState.CONFIRMED, ClaimState.CONTRADICTED, ClaimState.UNCERTAIN}:
                staged_reason = f"Claim staged through PENDING before final verification: {reason}"
                target_state = ClaimState.PENDING
                reason = staged_reason

        event = _transition_event(claim, target_state, eids, reason, evidence_map)
        return (event,) if event is not None else ()

    def evaluate_all(
        self,
        claims: Sequence[ClaimRecord] | Mapping[str, ClaimRecord],
        *args: Any,
        **kwargs: Any,
    ) -> tuple[ClaimStateChanged, ...]:
        """Evaluate multiple claims and collect state-change events deterministically."""
        claim_list = list(claims.values()) if isinstance(claims, Mapping) else list(claims)
        events: list[ClaimStateChanged] = []
        for cl in sorted(claim_list, key=lambda c: c.claim_id):
            events.extend(self.evaluate(cl, *args, **kwargs))
        return tuple(events)


__all__ = [
    "ClaimEvaluator",
    "RULE_APPOINTMENT_BOOKED",
    "RULE_APPOINTMENT_CANCELLED",
    "RULE_SLOT_AVAILABLE",
    "RULE_REQUEST_RECEIVED",
    "normalize_rule_name",
    "LEGAL_CLAIM_TRANSITIONS",
    "CANONICAL_RECEIPT_KINDS",
    "CANONICAL_RECEIPT_PRODUCERS",
]
