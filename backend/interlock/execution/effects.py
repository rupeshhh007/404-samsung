"""EXE-005: pure interpretation of provider observations into world facts.

The journal and reducer remain the only owners of authoritative state.  This
module returns detached candidates and derives projections from caller-owned
snapshots; it never invokes a provider or changes the supplied ledger.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from hashlib import sha256
from typing import Any, Mapping

from interlock.domain.enums import (
    ActionType,
    EffectClassification,
    EffectState,
    EventSource,
    EvidenceAuthority,
    EvidenceSource,
    ToolOutcome,
)
from interlock.domain.events import EvidenceRecorded, ToolResultObserved, WorldEffectObserved
from interlock.domain.models import EffectRecord, EvidenceRecord, EventEnvelope, OperationRecord
from interlock.execution.descriptors import ToolRegistry
from interlock.execution.idempotency import IdempotencyError, canonical_json, strict_json_copy
from interlock.execution.operations import OperationError, _validate_arguments
from interlock.runtime.journal import EventCandidate


class EffectInterpretationError(ValueError):
    """A provider fact cannot be safely interpreted under current authority."""


class WorldCertainty(str, Enum):
    CONFIRMED = "CONFIRMED"
    COMPENSATED = "COMPENSATED"
    UNRESOLVED = "UNRESOLVED"


@dataclass(frozen=True, slots=True, kw_only=True)
class VerificationScope:
    """Trusted context copied from VerifyOutcome and the verified write snapshot.

    The operation/action pair identifies the booking being verified, not the
    appointment.get execution. A missing physical target means operation-only
    verification; it cannot resolve a conflict in existing physical history.
    """

    verification_request_event_id: str
    operation_id: str
    logical_action_id: str
    provider_effect_id: str | None = None
    verification_of_effect_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PhysicalWorldView:
    provider_effect_id: str
    logical_action_ids: tuple[str, ...]
    certainty: WorldCertainty
    current_effect_id: str | None
    observation_ids: tuple[str, ...]
    duplicate_physical_effect: bool = False

    @property
    def logical_action_id(self) -> str | None:
        """Convenience for an unambiguous incident; never choose among actions."""

        return self.logical_action_ids[0] if len(self.logical_action_ids) == 1 else None


class EffectInterpreter:
    """Interpret accepted ToolResultObserved facts using trusted descriptors."""

    def __init__(self, *, registry: ToolRegistry) -> None:
        if not isinstance(registry, ToolRegistry):
            raise TypeError("registry must be a ToolRegistry")
        self._registry = registry

    def observe(
        self,
        source: EventEnvelope,
        *,
        operation: OperationRecord,
        known_effects: Mapping[str, EffectRecord],
        known_evidence: Mapping[str, EvidenceRecord],
        verification_scope: VerificationScope | None = None,
    ) -> tuple[EventCandidate, ...]:
        """Return evidence then a world observation, if external truth is proven.

        Stale local operation state never suppresses a confirmed provider fact.
        Its provider identity and the descriptor pinned at operation creation do.
        Both maps are reducer-owned snapshots from the same interpretation
        point. VerificationScope is trusted command context, never provider data.
        """

        if not isinstance(source, EventEnvelope) or source.event_type != "ToolResultObserved":
            raise EffectInterpretationError("expected accepted ToolResultObserved envelope")
        if source.source != EventSource.TOOL or not isinstance(operation, OperationRecord):
            raise EffectInterpretationError("provider source or operation snapshot is untrusted")
        try:
            observed = ToolResultObserved.model_validate(source.payload)
            result = strict_json_copy(observed.result, field="provider_result")
            if type(result) is not dict:
                raise ValueError("provider result must be an object")
            descriptor = self._registry.get(operation.tool_name)
            capability_hash = self._registry.capability_hash(operation.tool_name)
            _validate_arguments(result, descriptor.result_schema)
        except (KeyError, ValueError, TypeError, IdempotencyError, OperationError) as exc:
            raise EffectInterpretationError("provider observation or descriptor is invalid") from exc
        if (
            observed.operation_id != operation.operation_id
            or operation.descriptor_capability_hash != capability_hash
            or (operation.provider_request_id is not None
                and observed.provider_request_id != operation.provider_request_id)
            or (operation.provider_request_id is None
                and operation.dispatch_requested_event_id is None)
            or result.get("provider_request_id") != observed.provider_request_id
        ):
            raise EffectInterpretationError("observation conflicts with authorized operation")

        semantics = descriptor.confirmation_semantics
        status = result.get("status")
        if observed.outcome == ToolOutcome.ACKNOWLEDGED:
            if semantics.acknowledgement is None or status != semantics.acknowledgement:
                raise EffectInterpretationError("acknowledgement semantic is untrusted")
            return (self._evidence_candidate(source, observed, operation, result,
                                            EvidenceAuthority.NON_AUTHORITATIVE, "tool_acknowledgement"),)
        if observed.outcome == ToolOutcome.UNKNOWN:
            if semantics.unknown is not None and status != semantics.unknown:
                raise EffectInterpretationError("unknown semantic conflicts with descriptor")
            if operation.tool_name == "appointment.cancel":
                return self._uncertain_compensation(source, observed, operation, result,
                                                    known_effects, known_evidence,
                                                    EffectState.OUTCOME_UNKNOWN)
            return (self._evidence_candidate(source, observed, operation, result,
                                            EvidenceAuthority.NON_AUTHORITATIVE, "tool_outcome_unknown"),)
        if observed.outcome == ToolOutcome.FAILED:
            if status in {semantics.acknowledgement, semantics.commit, semantics.unknown}:
                raise EffectInterpretationError("failure contradicts confirmation semantics")
            if operation.tool_name == "appointment.cancel":
                return self._uncertain_compensation(source, observed, operation, result,
                                                    known_effects, known_evidence,
                                                    EffectState.FAILED)
            return (self._evidence_candidate(source, observed, operation, result,
                                            EvidenceAuthority.NON_AUTHORITATIVE, "tool_failure"),)
        if observed.outcome != ToolOutcome.SUCCEEDED or not semantics.commit or status != semantics.commit:
            raise EffectInterpretationError("success lacks trusted final confirmation")
        if any(not _nonempty(result.get(name)) for name in semantics.authoritative_fields):
            raise EffectInterpretationError("authoritative confirmation field is missing")

        if operation.tool_name == "appointment.book":
            return self._booking(source, observed, operation, result)
        if operation.tool_name == "appointment.get":
            return self._verification(source, observed, operation, result, known_effects,
                                      known_evidence, verification_scope, descriptor.action_type,
                                      descriptor.effect_classification)
        if operation.tool_name == "appointment.cancel":
            return self._compensation(source, observed, operation, result,
                                      known_effects, known_evidence)
        raise EffectInterpretationError("effect-producing tool has no canonical effect mapping")

    def _booking(self, source: EventEnvelope, observed: ToolResultObserved,
                 operation: OperationRecord, result: dict[str, Any]) -> tuple[EventCandidate, ...]:
        if result.get("phase") != "FINAL":
            raise EffectInterpretationError("booking confirmation is not final")
        _booking_identity(observed, result)
        for name in ("center_id", "requested_slot", "confirmed_slot"):
            if not _nonempty(result.get(name)):
                raise EffectInterpretationError("booking confirmation lacks physical facts")
        evidence = self._evidence_candidate(source, observed, operation, result,
                                            EvidenceAuthority.AUTHORITATIVE, "booking_confirmation")
        return evidence, self._effect_candidate(source, observed, operation, result,
                                                evidence, EffectState.COMMITTED)

    def _verification(
        self, source: EventEnvelope, observed: ToolResultObserved,
        operation: OperationRecord, result: dict[str, Any],
        known_effects: Mapping[str, EffectRecord],
        known_evidence: Mapping[str, EvidenceRecord], scope: VerificationScope | None,
        action_type: ActionType, effect_classification: EffectClassification,
    ) -> tuple[EventCandidate, ...]:
        if action_type != ActionType.READ_ONLY or effect_classification != EffectClassification.NONE:
            raise EffectInterpretationError("verification producer is not a trusted read")
        if (
            not isinstance(scope, VerificationScope)
            or not _nonempty(source.causation_id)
            or source.causation_id != scope.verification_request_event_id
            or not _nonempty(scope.operation_id)
            or not _nonempty(scope.logical_action_id)
        ):
            raise EffectInterpretationError("readback lacks reducer-issued verification scope")
        # A read may discover the first physical ID after a write timed out.
        # The nested provider identity is authoritative, never a local fallback.
        provider_id = result.get("provider_booking_id")
        if not _nonempty(provider_id) or (
            observed.provider_effect_id is not None and observed.provider_effect_id != provider_id
        ):
            raise EffectInterpretationError("provider effect and booking identities differ")
        observed = observed.model_copy(update={"provider_effect_id": provider_id})
        history = [effect for effect in known_effects.values()
                   if effect.provider_effect_id == provider_id
                   and effect.authority == EvidenceAuthority.AUTHORITATIVE]
        if scope.provider_effect_id is None:
            if scope.verification_of_effect_ids:
                raise EffectInterpretationError("operation-only verification cannot claim physical coverage")
            covered: list[str] = []
            mode = "OPERATION"
        else:
            if scope.provider_effect_id != provider_id:
                raise EffectInterpretationError("readback targets another physical effect")
            covered = sorted(effect.effect_id for effect in history)
            if not covered or tuple(covered) != scope.verification_of_effect_ids:
                raise EffectInterpretationError("readback does not cover current authoritative history")
            if any((sequence := _source_sequence(effect, known_evidence)) is None
                   or sequence >= source.sequence for effect in history):
                raise EffectInterpretationError("verification history has no earlier source context")
            mode = "PHYSICAL"
        if history:
            actions = _incident_actions(history, known_effects, known_evidence)
            if actions != (scope.logical_action_id,) or not any(
                effect.operation_id == scope.operation_id
                and effect.logical_action_id == scope.logical_action_id
                and effect.state == EffectState.COMMITTED for effect in history
            ):
                raise EffectInterpretationError("verification does not identify one booking lineage")
        if result.get("phase") != "FINAL" or any(
            not _nonempty(result.get(name))
            for name in ("center_id", "requested_slot", "confirmed_slot")
        ):
            raise EffectInterpretationError("verification does not prove a final booking")
        evidence = self._evidence_candidate(
            source, observed, operation, result, EvidenceAuthority.AUTHORITATIVE,
            "world_effect_verification",
            extra_provenance={
                "provider_effect_id": provider_id,
                "verification_mode": mode,
                "verification_request_event_id": scope.verification_request_event_id,
                "provider_request_id": observed.provider_request_id,
                "verification_of_effect_ids": covered,
                "verified_operation_id": scope.operation_id,
                "verified_logical_action_id": scope.logical_action_id,
            },
        )
        return evidence, self._effect_candidate(source, observed, operation, result,
                                                evidence, EffectState.COMMITTED,
                                                lineage=(scope.operation_id, scope.logical_action_id))

    def _compensation(
        self, source: EventEnvelope, observed: ToolResultObserved,
        operation: OperationRecord, result: dict[str, Any],
        known_effects: Mapping[str, EffectRecord],
        known_evidence: Mapping[str, EvidenceRecord],
    ) -> tuple[EventCandidate, ...]:
        if result.get("phase", "FINAL") != "FINAL":
            raise EffectInterpretationError("compensation confirmation is not final")
        target = self._target_commit(operation, result, known_effects, known_evidence)
        if observed.provider_effect_id != target.provider_effect_id:
            raise EffectInterpretationError("compensation provider effect identity differs")
        if not _nonempty(result.get("cancelled_at")):
            raise EffectInterpretationError("compensation lacks cancellation time")
        evidence = self._evidence_candidate(source, observed, operation, result,
                                            EvidenceAuthority.AUTHORITATIVE, "booking_compensation")
        return evidence, self._effect_candidate(
            source, observed, operation, result, evidence, EffectState.COMPENSATED,
            predecessor=target,
        )

    def _uncertain_compensation(
        self, source: EventEnvelope, observed: ToolResultObserved,
        operation: OperationRecord, result: dict[str, Any],
        known_effects: Mapping[str, EffectRecord],
        known_evidence: Mapping[str, EvidenceRecord],
        state: EffectState,
    ) -> tuple[EventCandidate, ...]:
        # The authorized request identifies an already-observed booking; this
        # never invents a new physical identity or claims cancellation success.
        target = self._target_commit(operation, operation.args, known_effects, known_evidence)
        if observed.provider_effect_id is not None and observed.provider_effect_id != target.provider_effect_id:
            raise EffectInterpretationError("uncertain compensation targets another physical effect")
        if result.get("provider_booking_id", target.provider_effect_id) != target.provider_effect_id:
            raise EffectInterpretationError("uncertain compensation result targets another booking")
        evidence = self._evidence_candidate(source, observed, operation, result,
                                            EvidenceAuthority.NON_AUTHORITATIVE,
                                            "booking_compensation_uncertain")
        return evidence, self._effect_candidate(
            source, observed, operation, result, evidence, state,
            predecessor=target, authority=EvidenceAuthority.NON_AUTHORITATIVE,
        )

    @staticmethod
    def _target_commit(operation: OperationRecord, result: Mapping[str, Any],
                       known_effects: Mapping[str, EffectRecord],
                       known_evidence: Mapping[str, EvidenceRecord]) -> EffectRecord:
        booking_id = result.get("provider_booking_id")
        center_id = result.get("center_id")
        if (
            not _nonempty(booking_id) or not _nonempty(center_id)
            or operation.args.get("provider_booking_id") != booking_id
            or operation.args.get("center_id") != center_id
        ):
            raise EffectInterpretationError("compensation target differs from authorized request")
        view = next((item for item in project_world(known_effects, known_evidence)
                     if item.provider_effect_id == booking_id), None)
        if view is None or view.certainty != WorldCertainty.CONFIRMED or view.current_effect_id is None:
            raise EffectInterpretationError("compensation requires a resolved current commit")
        target = known_effects[view.current_effect_id]
        if (
            target.state != EffectState.COMMITTED
            or target.authority != EvidenceAuthority.AUTHORITATIVE
            or target.effect_type != "appointment.booking"
            or target.provider_effect_id != booking_id
            or target.subject.get("provider_booking_id") != booking_id
            or target.subject.get("center_id") != center_id
            or view.logical_action_ids != (target.logical_action_id,)
        ):
            raise EffectInterpretationError("current committed target does not match booking lineage")
        return target

    @staticmethod
    def _evidence_candidate(
        source: EventEnvelope, observed: ToolResultObserved, operation: OperationRecord,
        result: dict[str, Any], authority: EvidenceAuthority, kind: str,
        extra_provenance: Mapping[str, Any] | None = None,
    ) -> EventCandidate:
        content_hash = _digest({"outcome": observed.outcome, "result": result,
                                "provider_effect_id": observed.provider_effect_id})
        provenance = {"event_id": source.event_id, "sequence": source.sequence,
                      "operation_id": operation.operation_id,
                      "tool_name": operation.tool_name,
                      "provider_request_id": observed.provider_request_id}
        if source.causation_id is not None:
            provenance["causation_id"] = source.causation_id
        if observed.provider_effect_id is not None:
            provenance["provider_effect_id"] = observed.provider_effect_id
        provenance.update(dict(extra_provenance or {}))
        evidence_id = _digest({"session_id": source.session_id, "event_id": source.event_id,
                               "kind": kind, "content_hash": content_hash,
                               "provenance": provenance})
        record = EvidenceRecord(
            evidence_id=evidence_id, source=EvidenceSource.TOOL, kind=kind,
            captured_at=source.occurred_at, content_ref=f"event:{source.event_id}",
            content_hash=content_hash, authority=authority,
            provenance=strict_json_copy(provenance, field="evidence_provenance"),
        )
        return _candidate(source, "EvidenceRecorded", EvidenceRecorded(evidence=record).model_dump(mode="json"),
                          evidence_id)

    @staticmethod
    def _effect_candidate(
        source: EventEnvelope, observed: ToolResultObserved, operation: OperationRecord,
        result: dict[str, Any], evidence: EventCandidate, state: EffectState,
        predecessor: EffectRecord | None = None,
        authority: EvidenceAuthority = EvidenceAuthority.AUTHORITATIVE,
        lineage: tuple[str, str] | None = None,
    ) -> EventCandidate:
        evidence_id = evidence.payload["evidence"]["evidence_id"]
        operation_id, logical_action_id = (
            (predecessor.operation_id, predecessor.logical_action_id) if predecessor else
            lineage if lineage is not None else (operation.operation_id, operation.logical_action_id)
        )
        if predecessor is None:
            subject = {"resource": "appointment", "provider_booking_id": observed.provider_effect_id,
                       "center_id": result["center_id"]}
            parameters = {"requested_slot": result["requested_slot"],
                          "confirmed_slot": result["confirmed_slot"]}
        else:
            # Compensation is a new observation of the same booking family.
            subject = dict(predecessor.subject)
            parameters = dict(predecessor.parameters)
            if state == EffectState.COMPENSATED:
                parameters["cancelled_at"] = result["cancelled_at"]
        identity = {"session_id": source.session_id, "source_event_id": source.event_id,
                    "provider_effect_id": predecessor.provider_effect_id if predecessor else observed.provider_effect_id,
                    "state": state.value,
                    "subject": subject, "parameters": parameters,
                    "operation_id": operation_id, "logical_action_id": logical_action_id,
                    "evidence_id": evidence_id,
                    "supersedes_effect_id": predecessor.effect_id if predecessor else None}
        effect = EffectRecord(
            effect_id=_digest(identity), logical_action_id=logical_action_id,
            operation_id=operation_id,
            provider_effect_id=predecessor.provider_effect_id if predecessor else observed.provider_effect_id,
            effect_type="appointment.booking", subject=subject, parameters=parameters,
            state=state, observed_at=source.occurred_at,
            authority=authority, evidence_ids=[evidence_id],
            supersedes_effect_id=predecessor.effect_id if predecessor else None,
        )
        return _candidate(source, "WorldEffectObserved",
                          WorldEffectObserved(effect=effect).model_dump(mode="json"), effect.effect_id,
                          causation_id=source.causation_id if operation.tool_name == "appointment.get" else source.event_id)


def project_world(
    effects: Mapping[str, EffectRecord], evidence: Mapping[str, EvidenceRecord],
) -> tuple[PhysicalWorldView, ...]:
    """Derive current physical certainty without changing append-only history."""

    groups: dict[str, list[EffectRecord]] = {}
    for effect in effects.values():
        groups.setdefault(effect.provider_effect_id, []).append(effect)
    incident_actions = {provider_id: _incident_actions(group, effects, evidence)
                        for provider_id, group in groups.items()}
    action_counts: dict[str, int] = {}
    for actions in incident_actions.values():
        for action in actions:
            action_counts[action] = action_counts.get(action, 0) + 1
    views: list[PhysicalWorldView] = []
    for provider_id, group in sorted(groups.items()):
        authoritative = [item for item in group if item.authority == EvidenceAuthority.AUTHORITATIVE]
        commits = [item for item in authoritative if item.state == EffectState.COMMITTED]
        compensations = [item for item in authoritative if item.state == EffectState.COMPENSATED]
        current: EffectRecord | None = None
        certainty = WorldCertainty.UNRESOLVED
        verifier = _latest_scoped_verification(authoritative, evidence, provider_id)
        if verifier is not None:
            proof = _trusted_verifier_proof(verifier, evidence)
            covered = set(proof.provenance["verification_of_effect_ids"])
            uncovered = [item for item in authoritative
                         if item.effect_id not in covered and item.effect_id != verifier.effect_id]
            if all(_agrees_with_verified_state(item, verifier, effects) for item in uncovered):
                current = verifier
                certainty = (WorldCertainty.COMPENSATED if verifier.state == EffectState.COMPENSATED
                             else WorldCertainty.CONFIRMED)
                later_compensations = [item for item in uncovered if item.state == EffectState.COMPENSATED]
                if later_compensations:
                    if len({_material(item) for item in later_compensations}) == 1:
                        current = _unique_observation(later_compensations)
                        certainty = WorldCertainty.COMPENSATED
                    else:
                        current = None
                        certainty = WorldCertainty.UNRESOLVED
        elif commits and len({_material(item) for item in commits}) == 1 and not any(
            item.state == EffectState.FAILED and item.supersedes_effect_id is None
            for item in authoritative
        ):
            # Agreement determines truth; it does not privilege one callback.
            # Multiple agreeing witnesses need a scoped readback before a
            # consumer can select one exact compensation predecessor.
            current = _unique_observation(commits)
            certainty = WorldCertainty.CONFIRMED
            if compensations:
                if all(_valid_compensation(item, effects) for item in compensations) and len(
                    {_material(item) for item in compensations}
                ) == 1:
                    current = _unique_observation(compensations)
                    certainty = WorldCertainty.COMPENSATED
                else:
                    current = None
                    certainty = WorldCertainty.UNRESOLVED
        actions = incident_actions[provider_id]
        views.append(PhysicalWorldView(
            provider_effect_id=provider_id, logical_action_ids=actions,
            certainty=certainty, current_effect_id=current.effect_id if current else None,
            observation_ids=tuple(sorted(effect.effect_id for effect in group)),
            duplicate_physical_effect=any(action_counts[action] > 1 for action in actions),
        ))
    return tuple(views)


def _material(effect: EffectRecord) -> tuple[str, str, str, str]:
    return (effect.state, effect.effect_type, canonical_json(effect.subject),
            canonical_json(effect.parameters))


def _source_sequence(effect: EffectRecord, evidence: Mapping[str, EvidenceRecord]) -> int | None:
    if any(evidence_id not in evidence for evidence_id in effect.evidence_ids):
        return None
    sequences = [proof.provenance.get("sequence") for evidence_id in effect.evidence_ids
                 if (proof := evidence.get(evidence_id)) is not None]
    if not sequences or any(type(sequence) is not int or sequence <= 0
                            or sequence != sequences[0] for sequence in sequences):
        return None
    sequence = sequences[0]
    return sequence


def _unique_observation(observations: list[EffectRecord]) -> EffectRecord | None:
    return observations[0] if len(observations) == 1 else None


def _trusted_verifier_proof(
    effect: EffectRecord, evidence: Mapping[str, EvidenceRecord],
) -> EvidenceRecord | None:
    """Validate the read producer separately from the booking operation lineage."""

    sequence = _source_sequence(effect, evidence)
    for evidence_id in effect.evidence_ids:
        proof = evidence.get(evidence_id)
        if proof is None:
            continue
        provenance = proof.provenance
        covered = provenance.get("verification_of_effect_ids")
        if (
            proof.source == EvidenceSource.TOOL
            and proof.authority == EvidenceAuthority.AUTHORITATIVE
            and proof.kind == "world_effect_verification"
            and provenance.get("tool_name") == "appointment.get"
            and _nonempty(provenance.get("operation_id"))
            and provenance.get("verified_operation_id") == effect.operation_id
            and provenance.get("verified_logical_action_id") == effect.logical_action_id
            and provenance.get("provider_effect_id") == effect.provider_effect_id
            and _nonempty(provenance.get("verification_request_event_id"))
            and provenance.get("verification_request_event_id") == provenance.get("causation_id")
            and _nonempty(provenance.get("provider_request_id"))
            and sequence is not None
            and provenance.get("sequence") == sequence
            and _nonempty(provenance.get("event_id"))
            and proof.content_ref == f"event:{provenance['event_id']}"
            and provenance.get("verification_mode") in ("OPERATION", "PHYSICAL")
            and isinstance(covered, list)
            and all(_nonempty(item) for item in covered)
            and covered == sorted(set(covered))
        ):
            return proof
    return None


def _incident_actions(
    group: list[EffectRecord], effects: Mapping[str, EffectRecord],
    evidence: Mapping[str, EvidenceRecord],
) -> tuple[str, ...]:
    """Follow booking history, never an observation ID or cancel/read action."""

    cached: dict[str, set[str]] = {}

    def actions(effect: EffectRecord, visiting: frozenset[str]) -> set[str]:
        if effect.effect_id in visiting or effect.authority != EvidenceAuthority.AUTHORITATIVE:
            return set()
        if effect.effect_id in cached:
            return cached[effect.effect_id]
        visiting = visiting | {effect.effect_id}
        if effect.supersedes_effect_id is not None:
            prior = effects.get(effect.supersedes_effect_id)
            if prior is not None and prior.provider_effect_id == effect.provider_effect_id:
                return actions(prior, visiting)
            return set()
        if effect.state != EffectState.COMMITTED:
            return set()
        proof = _trusted_verifier_proof(effect, evidence)
        if proof is not None and proof.provenance["verification_of_effect_ids"]:
            covered = [effects.get(key) for key in proof.provenance["verification_of_effect_ids"]]
            if all(item is not None and item.provider_effect_id == effect.provider_effect_id for item in covered):
                cached[effect.effect_id] = set().union(*(actions(item, visiting) for item in covered))
                return cached[effect.effect_id]
        cached[effect.effect_id] = {effect.logical_action_id}
        return cached[effect.effect_id]

    return tuple(sorted(set().union(*(actions(item, frozenset()) for item in group))))


def _latest_scoped_verification(
    authoritative: list[EffectRecord], evidence: Mapping[str, EvidenceRecord], provider_id: str,
) -> EffectRecord | None:
    valid: list[EffectRecord] = []
    for effect in authoritative:
        if effect.state not in (EffectState.COMMITTED, EffectState.COMPENSATED):
            continue
        sequence = _source_sequence(effect, evidence)
        proof = _trusted_verifier_proof(effect, evidence)
        if sequence is None or proof is None or proof.provenance["verification_mode"] != "PHYSICAL":
            continue
        prior = sorted(item.effect_id for item in authoritative
                       if (prior_sequence := _source_sequence(item, evidence)) is not None
                       and prior_sequence < sequence)
        if not prior or any(
            item.effect_id != effect.effect_id and _source_sequence(item, evidence) is None
            for item in authoritative
        ):
            continue
        if proof.provenance["provider_effect_id"] == provider_id and proof.provenance["verification_of_effect_ids"] == prior:
            valid.append(effect)
    # A verifier is decisive only if its causal coverage subsumes every other
    # qualified verifier. Neither a hash nor the last callback decides truth.
    decisive = [effect for effect in valid if all(
        other.effect_id == effect.effect_id or other.effect_id in
        _trusted_verifier_proof(effect, evidence).provenance["verification_of_effect_ids"]
        for other in valid
    )]
    return _unique_observation(decisive)


def _agrees_with_verified_state(
    observation: EffectRecord, verifier: EffectRecord, effects: Mapping[str, EffectRecord],
) -> bool:
    if observation.state == EffectState.FAILED:
        return observation.supersedes_effect_id is not None
    if observation.state == EffectState.COMMITTED:
        return _material(observation) == _material(verifier)
    if observation.state == EffectState.COMPENSATED:
        if not _valid_compensation(observation, effects):
            return False
        if verifier.state == EffectState.COMPENSATED:
            return _material(observation) == _material(verifier)
        return _material(effects[observation.supersedes_effect_id]) == _material(verifier)
    return observation.state == EffectState.OUTCOME_UNKNOWN


def _valid_compensation(effect: EffectRecord, effects: Mapping[str, EffectRecord]) -> bool:
    prior = effects.get(effect.supersedes_effect_id or "")
    return (
        prior is not None
        and prior.state == EffectState.COMMITTED
        and prior.authority == EvidenceAuthority.AUTHORITATIVE
        and prior.provider_effect_id == effect.provider_effect_id
        and prior.effect_type == effect.effect_type
        and prior.subject == effect.subject
        and {key: value for key, value in effect.parameters.items() if key != "cancelled_at"} == prior.parameters
    )


def _booking_identity(observed: ToolResultObserved, result: Mapping[str, Any]) -> None:
    if not _nonempty(observed.provider_effect_id) or result.get("provider_booking_id") != observed.provider_effect_id:
        raise EffectInterpretationError("provider effect and booking identities differ")


def _nonempty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _digest(value: Any) -> str:
    return "sha256:" + sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _candidate(source: EventEnvelope, event_type: str, payload: dict[str, Any],
               identity: str, *, causation_id: str | None = None) -> EventCandidate:
    return EventCandidate(
        event_type=event_type, session_id=source.session_id, source=EventSource.TOOL,
        payload=payload, occurred_at=source.occurred_at, logical_time=source.logical_time,
        correlation_id=source.correlation_id,
        causation_id=source.event_id if causation_id is None else causation_id,
        dedupe_key=f"effect-interpreter:{event_type}:{identity}",
    )
