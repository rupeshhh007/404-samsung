"""Pure INTEL-002 intent-revision proposals and selective dependency impact.

This module never commits a revision, changes a SessionState, or interprets an
external effect.  The reducer remains the sole authority for those decisions.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import math
from types import MappingProxyType
from typing import Any, Iterable, Mapping, Sequence

from interlock.domain.enums import Authorization, IntentMaturity
from interlock.domain.models import (
    DependencyBinding,
    IntentDelta,
    IntentNode,
    IntentRevision,
)


class IntentGraphError(ValueError):
    """A proposal or dependency could not be validated safely."""


_GOAL_REQUIRED_FIELDS = frozenset({"intent_id", "goal_type", "values"})


@dataclass(frozen=True, slots=True)
class GoalAddition:
    """Proposed new stable goal identity with detached initial values."""

    intent_id: str
    goal_type: str
    _payload_json: str

    @property
    def values(self) -> dict[str, Any]:
        return self.payload["values"]

    @property
    def payload(self) -> dict[str, Any]:
        return json.loads(self._payload_json)

    @property
    def node(self) -> IntentNode:
        # The reducer owns creation of the first revision and active pointer.
        return IntentNode(intent_id=self.intent_id, goal_type=self.goal_type)


@dataclass(frozen=True, slots=True)
class IntentGraphProposal:
    """Immutable proposal data; accessing the shared model yields a fresh copy."""

    target_intent_id: str
    parent_revision_id: str
    _revision_json: str
    bindings: tuple[DependencySnapshot, ...]
    added_goals: tuple[GoalAddition, ...]
    retracted_intent_ids: tuple[str, ...]
    changed_paths: tuple[str, ...]

    @property
    def proposed_revision(self) -> IntentRevision:
        return IntentRevision.model_validate(json.loads(self._revision_json))


@dataclass(frozen=True, slots=True)
class DependencySnapshot:
    """Immutable equivalent of a canonical DependencyBinding."""

    path: str
    value_hash: str
    evidence_ids: tuple[str, ...]

    def as_domain(self) -> DependencyBinding:
        return DependencyBinding(
            path=self.path,
            value_hash=self.value_hash,
            evidence_ids=list(self.evidence_ids),
        )


@dataclass(frozen=True, slots=True)
class WorkImpact:
    """Dependency freshness only; the owning layer decides result eligibility."""

    stale: bool
    prior_fingerprint: str
    current_fingerprint: str | None
    affected_paths: tuple[str, ...]

    @property
    def eligible_for_active_result(self) -> bool:
        """Dependency-fresh for consideration, not authorized to update state."""
        return not self.stale


class IntentGraph:
    """Defensive snapshot of caller-supplied goal identities and revisions."""

    def __init__(
        self,
        nodes: Mapping[str, IntentNode],
        revisions: Mapping[str, IntentRevision],
    ) -> None:
        node_json: dict[str, str] = {}
        revision_json: dict[str, str] = {}
        for intent_id, node in nodes.items():
            if not isinstance(node, IntentNode) or intent_id != node.intent_id:
                raise IntentGraphError("node key must match an IntentNode.intent_id")
            node_json[intent_id] = _canonical_json(node.model_dump(mode="python"))
        for revision_id, revision in revisions.items():
            if not isinstance(revision, IntentRevision) or revision_id != revision.revision_id:
                raise IntentGraphError("revision key must match an IntentRevision.revision_id")
            revision_json[revision_id] = _canonical_json(
                revision.model_dump(mode="python")
            )
        for intent_id, serialized in node_json.items():
            node = IntentNode.model_validate(json.loads(serialized))
            if len(node.revisions) != len(set(node.revisions)):
                raise IntentGraphError("node history contains duplicate revision IDs")
            for revision_id in node.revisions:
                history_item = revision_json.get(revision_id)
                if history_item is None or json.loads(history_item)["intent_id"] != intent_id:
                    raise IntentGraphError("node history must contain its own revisions")
            if node.active_revision_id is not None:
                active = revision_json.get(node.active_revision_id)
                if active is None or json.loads(active)["intent_id"] != intent_id:
                    raise IntentGraphError("active revision must belong to its IntentNode")
                if node.active_revision_id not in node.revisions:
                    raise IntentGraphError("active revision must occur in node history")
        for revision_id, serialized in revision_json.items():
            intent_id = json.loads(serialized)["intent_id"]
            if intent_id not in node_json or revision_id not in json.loads(
                node_json[intent_id]
            )["revisions"]:
                raise IntentGraphError("revision must occur in its IntentNode history")

        parents: dict[str, str | None] = {}
        for revision_id, serialized in revision_json.items():
            revision = json.loads(serialized)
            parent_id = revision["parent_revision_id"]
            if parent_id is not None:
                if parent_id == revision_id:
                    raise IntentGraphError("revision cannot parent itself")
                parent_data = revision_json.get(parent_id)
                if parent_data is None:
                    raise IntentGraphError("revision parent does not exist")
                if json.loads(parent_data)["intent_id"] != revision["intent_id"]:
                    raise IntentGraphError("revision parent belongs to another intent")
            parents[revision_id] = parent_id

        validated: set[str] = set()
        for revision_id in parents:
            trail: set[str] = set()
            current: str | None = revision_id
            while current is not None and current not in validated:
                if current in trail:
                    raise IntentGraphError("revision parent chain contains a cycle")
                trail.add(current)
                current = parents[current]
            validated.update(trail)
        for serialized in node_json.values():
            node = json.loads(serialized)
            history = node["revisions"]
            if not history:
                continue
            # The reducer appends committed revisions in root-to-tip order.
            if parents[history[0]] is not None or any(
                parents[child_id] != parent_id
                for parent_id, child_id in zip(history, history[1:])
            ):
                raise IntentGraphError("node history must be one ordered linear chain")
            if node["active_revision_id"] != history[-1]:
                raise IntentGraphError("active revision must be the chain tip")

        self._nodes = MappingProxyType(node_json)
        self._revisions = MappingProxyType(revision_json)
        self._parents = MappingProxyType(parents)

    def _require_snapshot_revision(self, revision: IntentRevision) -> None:
        if not isinstance(revision, IntentRevision):
            raise IntentGraphError("impact revision must be an IntentRevision")
        stored = self._revisions.get(revision.revision_id)
        if stored is None or stored != _canonical_json(revision.model_dump(mode="python")):
            raise IntentGraphError("impact revision is not in the validated graph")

    def apply_delta(
        self,
        delta: IntentDelta,
        *,
        revision_id: str,
        created_by_event_id: str,
        evidence_ids_by_path: Mapping[str, Sequence[str]] | None = None,
    ) -> IntentGraphProposal:
        """Propose one target revision and explicit goal additions/retractions."""

        if not isinstance(delta, IntentDelta):
            raise IntentGraphError("delta must be an IntentDelta")
        _nonempty_id(revision_id, "revision_id")
        _nonempty_id(created_by_event_id, "created_by_event_id")
        if revision_id in self._revisions or any(
            revision_id in json.loads(node)["revisions"]
            for node in self._nodes.values()
        ):
            raise IntentGraphError("revision_id already exists")

        node_data = self._nodes.get(delta.target_intent_id)
        if node_data is None:
            raise IntentGraphError("target_intent_id is not an existing IntentNode")
        node = IntentNode.model_validate(json.loads(node_data))
        if node.active_revision_id is None:
            raise IntentGraphError("target IntentNode has no active revision")
        parent = IntentRevision.model_validate(
            json.loads(self._revisions[node.active_revision_id])
        )
        if parent.intent_id != delta.target_intent_id:
            raise IntentGraphError("delta target does not match active revision")

        values = _json_object(parent.values, "parent.values")
        updated = _json_object(values, "parent.values")
        set_fields = _json_object(delta.set_fields, "delta.set_fields")
        set_paths = [_canonical_path(path) for path in set_fields]
        unset_paths = [_canonical_path(path) for path in delta.unset_fields]
        _reject_overlapping_paths(set_paths + unset_paths)

        changed: list[str] = []
        for path in sorted(set_paths):
            old_value = _resolve_optional(updated, path)
            _set_path(updated, path, set_fields[path])
            if old_value is _MISSING or _canonical_json(old_value) != _canonical_json(
                set_fields[path]
            ):
                changed.append(path)
        for path in sorted(unset_paths):
            if _resolve_optional(updated, path) is _MISSING:
                raise IntentGraphError(f"unset path does not exist: {path}")
            _unset_path(updated, path)
            changed.append(path)

        additions: list[GoalAddition] = []
        added_ids: set[str] = set()
        for raw_goal in delta.add_goals:
            goal = _json_object(raw_goal, "delta.add_goals entry")
            if set(goal) != _GOAL_REQUIRED_FIELDS:
                raise IntentGraphError(
                    "added goal must contain only intent_id, goal_type, values"
                )
            intent_id = _nonempty_id(goal["intent_id"], "added intent_id")
            goal_type = _nonempty_id(goal["goal_type"], "goal_type")
            if intent_id in self._nodes or intent_id in added_ids:
                raise IntentGraphError("added intent_id already exists or is duplicated")
            added_ids.add(intent_id)
            additions.append(
                GoalAddition(
                    intent_id=intent_id,
                    goal_type=goal_type,
                    _payload_json=_canonical_json(
                        {**goal, "values": _json_object(goal["values"], "added goal values")}
                    ),
                )
            )

        retractions: list[str] = []
        for intent_id in delta.retract_goals:
            _nonempty_id(intent_id, "retracted intent_id")
            if intent_id not in self._nodes or intent_id in retractions:
                raise IntentGraphError("retraction must name one existing IntentNode")
            retractions.append(intent_id)

        all_paths = _leaf_paths(updated)
        bindings = bind_dependencies(
            updated,
            all_paths,
            evidence_ids_by_path=evidence_ids_by_path,
        )
        binding_fingerprint = dependency_fingerprint(bindings)
        revision = IntentRevision(
            revision_id=revision_id,
            intent_id=delta.target_intent_id,
            parent_revision_id=parent.revision_id,
            values=updated,
            maturity=IntentMaturity.PROVISIONAL,
            authorization=Authorization.NOT_REQUESTED,
            created_by_event_id=created_by_event_id,
            dependency_fingerprint=binding_fingerprint,
        )
        return IntentGraphProposal(
            target_intent_id=delta.target_intent_id,
            parent_revision_id=parent.revision_id,
            _revision_json=_canonical_json(revision.model_dump(mode="python")),
            bindings=bindings,
            added_goals=tuple(additions),
            retracted_intent_ids=tuple(retractions),
            changed_paths=tuple(sorted(changed)),
        )


def bind_dependencies(
    revision_or_values: IntentRevision | Mapping[str, Any],
    paths: Iterable[str],
    *,
    evidence_ids_by_path: Mapping[str, Sequence[str]] | None = None,
) -> tuple[DependencySnapshot, ...]:
    """Bind only requested paths to canonical values and sorted evidence IDs."""

    values = (
        revision_or_values.values
        if isinstance(revision_or_values, IntentRevision)
        else revision_or_values
    )
    canonical_values = _json_object(values, "revision values")
    canonical_paths = sorted({_canonical_path(path) for path in paths})
    evidence = evidence_ids_by_path or {}
    if not isinstance(evidence, Mapping):
        raise IntentGraphError("evidence_ids_by_path must be a mapping")
    for path in evidence:
        if _canonical_path(path) not in canonical_paths:
            raise IntentGraphError("evidence supplied for an unbound path")
    bindings: list[DependencySnapshot] = []
    for path in canonical_paths:
        value = _resolve_optional(canonical_values, path)
        if value is _MISSING:
            raise IntentGraphError(f"dependency path does not exist: {path}")
        ids = evidence.get(path, ())
        if not isinstance(ids, (list, tuple)):
            raise IntentGraphError("evidence IDs must be a list or tuple")
        normalized_ids = tuple(sorted({_nonempty_id(item, "evidence ID") for item in ids}))
        bindings.append(
            DependencySnapshot(
                path=path,
                value_hash=_hash_dependency_value(value),
                evidence_ids=normalized_ids,
            )
        )
    return tuple(bindings)


def dependency_fingerprint(
    bindings: Sequence[DependencySnapshot | DependencyBinding],
) -> str:
    """Hash the canonical list of path/value-hash/evidence bindings."""

    normalized: dict[str, dict[str, Any]] = {}
    for binding in bindings:
        if not isinstance(binding, (DependencySnapshot, DependencyBinding)):
            raise IntentGraphError("invalid dependency binding")
        path = _canonical_path(binding.path)
        if path in normalized:
            raise IntentGraphError("duplicate dependency path")
        if (
            not isinstance(binding.value_hash, str)
            or len(binding.value_hash) != 71
            or not binding.value_hash.startswith("sha256:")
            or any(character not in "0123456789abcdef" for character in binding.value_hash[7:])
        ):
            raise IntentGraphError("binding value_hash must be SHA-256")
        ids = tuple(sorted({_nonempty_id(item, "evidence ID") for item in binding.evidence_ids}))
        normalized[path] = {
            "path": path,
            "value_hash": binding.value_hash,
            "evidence_ids": list(ids),
        }
    return _hash_json([normalized[path] for path in sorted(normalized)])


def paths_related(changed_path: str, dependency_path: str) -> bool:
    """Match exact, ancestor, or descendant dotted paths by components."""

    changed = _canonical_path(changed_path).split(".")
    dependency = _canonical_path(dependency_path).split(".")
    common = min(len(changed), len(dependency))
    return changed[:common] == dependency[:common]


def assess_impact(
    prior_revision: IntentRevision,
    proposed_revision: IntentRevision,
    recorded_bindings: Sequence[DependencySnapshot | DependencyBinding],
    *,
    graph: IntentGraph | None = None,
    recorded_fingerprint: str | None = None,
    evidence_ids_by_path: Mapping[str, Sequence[str]] | None = None,
) -> WorkImpact:
    """Compare dependencies; a graph validates older-to-current lineage.

    Without a graph, only the existing direct-parent proposal comparison is
    supported.  Neither mode authorizes a result or concludes an external effect.
    """

    if not recorded_bindings:
        raise IntentGraphError("work impact requires at least one dependency binding")
    if graph is None:
        if (
            proposed_revision.parent_revision_id != prior_revision.revision_id
            or proposed_revision.intent_id != prior_revision.intent_id
        ):
            raise IntentGraphError("revisions must be direct parent and child of one intent")
    else:
        if not isinstance(graph, IntentGraph):
            raise IntentGraphError("graph must be an IntentGraph")
        graph._require_snapshot_revision(prior_revision)
        graph._require_snapshot_revision(proposed_revision)
        if prior_revision.intent_id != proposed_revision.intent_id:
            raise IntentGraphError("impact revisions belong to different intents")
        node = json.loads(graph._nodes[proposed_revision.intent_id])
        if node["active_revision_id"] != proposed_revision.revision_id:
            raise IntentGraphError("current impact revision is not active")
        current_id: str | None = proposed_revision.revision_id
        while current_id is not None and current_id != prior_revision.revision_id:
            current_id = graph._parents[current_id]
        if current_id is None:
            raise IntentGraphError("source revision is not an ancestor of current")
    prior_bindings = bind_dependencies(
        prior_revision,
        (binding.path for binding in recorded_bindings),
        evidence_ids_by_path={
            binding.path: binding.evidence_ids for binding in recorded_bindings
        },
    )
    expected_prior = dependency_fingerprint(prior_bindings)
    actual_recorded = dependency_fingerprint(recorded_bindings)
    if actual_recorded != expected_prior:
        raise IntentGraphError("recorded bindings do not match prior revision")
    if recorded_fingerprint is not None and recorded_fingerprint != actual_recorded:
        raise IntentGraphError("recorded fingerprint does not match bindings")

    paths = tuple(binding.path for binding in prior_bindings)
    current_values = _json_object(proposed_revision.values, "proposed revision values")
    missing = tuple(
        path for path in paths if _resolve_optional(current_values, path) is _MISSING
    )
    current_evidence = (
        evidence_ids_by_path
        if evidence_ids_by_path is not None
        else {binding.path: binding.evidence_ids for binding in prior_bindings}
    )
    if not isinstance(current_evidence, Mapping):
        raise IntentGraphError("evidence_ids_by_path must be a mapping")
    if any(_canonical_path(path) not in paths for path in current_evidence):
        raise IntentGraphError("evidence supplied for an unbound path")
    present_paths = tuple(path for path in paths if path not in missing)
    current_bindings = bind_dependencies(
        current_values,
        present_paths,
        evidence_ids_by_path={
            path: current_evidence[path]
            for path in present_paths
            if path in current_evidence
        },
    )
    current_by_path = {binding.path: binding for binding in current_bindings}
    affected = tuple(
        previous.path
        for previous in prior_bindings
        if previous.path in missing or previous != current_by_path[previous.path]
    )
    if missing:
        return WorkImpact(True, actual_recorded, None, affected)
    current_fingerprint = dependency_fingerprint(current_bindings)
    return WorkImpact(
        stale=current_fingerprint != actual_recorded,
        prior_fingerprint=actual_recorded,
        current_fingerprint=current_fingerprint,
        affected_paths=affected,
    )


_MISSING = object()


def _nonempty_id(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise IntentGraphError(f"{field} must be a non-empty string")
    return value


def _canonical_path(path: Any) -> str:
    if not isinstance(path, str) or not path:
        raise IntentGraphError("dependency path must be a non-empty dotted string")
    parts = path.split(".")
    if any(not part or part != part.strip() or any(c.isspace() for c in part) for part in parts):
        raise IntentGraphError("dependency path is not canonical dotted form")
    return path


def _json_object(value: Any, field: str) -> dict[str, Any]:
    normalized = _strict_json(value, field, set())
    if not isinstance(normalized, dict):
        raise IntentGraphError(f"{field} must be a JSON object")
    return normalized


def _strict_json(value: Any, path: str, active: set[int]) -> Any:
    if value is None or type(value) in (str, bool, int):
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise IntentGraphError(f"{path} contains a non-finite number")
        return value
    if type(value) in (dict, list):
        identity = id(value)
        if identity in active:
            raise IntentGraphError(f"{path} contains a cycle")
        active.add(identity)
        try:
            if type(value) is list:
                return [
                    _strict_json(item, f"{path}[{index}]", active)
                    for index, item in enumerate(value)
                ]
            result: dict[str, Any] = {}
            for key, item in value.items():
                if type(key) is not str:
                    raise IntentGraphError(f"{path} contains a non-string key")
                result[key] = _strict_json(item, f"{path}.{key}", active)
            return result
        finally:
            active.remove(identity)
    raise IntentGraphError(f"{path} contains a non-JSON value")


def _canonical_json(value: Any) -> str:
    normalized = _strict_json(value, "value", set())
    return json.dumps(
        normalized,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _hash_json(value: Any) -> str:
    return f"sha256:{sha256(_canonical_json(value).encode('utf-8')).hexdigest()}"


def _hash_dependency_value(value: Any) -> str:
    """Hash unordered dependency arrays without changing stored JSON payloads."""

    normalized = _normalize_arrays_for_hash(_strict_json(value, "dependency value", set()))
    return _hash_json(normalized)


def _normalize_arrays_for_hash(value: Any) -> Any:
    if isinstance(value, list):
        elements = [_normalize_arrays_for_hash(item) for item in value]
        return sorted(elements, key=_canonical_json)
    if isinstance(value, dict):
        return {key: _normalize_arrays_for_hash(item) for key, item in value.items()}
    return value


def _resolve_optional(values: Mapping[str, Any], path: str) -> Any:
    current: Any = values
    for part in _canonical_path(path).split("."):
        if not isinstance(current, dict) or part not in current:
            return _MISSING
        current = current[part]
    return current


def _set_path(values: dict[str, Any], path: str, value: Any) -> None:
    parts = path.split(".")
    current = values
    for part in parts[:-1]:
        child = current.get(part, _MISSING)
        if not isinstance(child, dict):
            raise IntentGraphError(f"set path has no object parent: {path}")
        current = child
    current[parts[-1]] = value


def _unset_path(values: dict[str, Any], path: str) -> None:
    parts = path.split(".")
    current = values
    for part in parts[:-1]:
        current = current[part]
    del current[parts[-1]]


def _reject_overlapping_paths(paths: Sequence[str]) -> None:
    if len(paths) != len(set(paths)):
        raise IntentGraphError("set/unset paths must be unique")
    for index, path in enumerate(paths):
        if any(paths_related(path, other) for other in paths[index + 1 :]):
            raise IntentGraphError("overlapping set/unset paths are ambiguous")


def _leaf_paths(values: Mapping[str, Any], prefix: str = "") -> tuple[str, ...]:
    leaves: list[str] = []
    for key, value in values.items():
        path = f"{prefix}.{key}" if prefix else key
        _canonical_path(path)
        if isinstance(value, dict) and value:
            leaves.extend(_leaf_paths(value, path))
        else:
            leaves.append(path)
    return tuple(sorted(leaves))
