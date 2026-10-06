"""Deterministic logical-action, idempotency, and callback identity policy.

The helpers in this module are pure.  Callers provide reducer-owned index
snapshots explicitly; this module neither owns authoritative state nor invokes
providers.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from hashlib import sha256
import json
import math
from typing import Any, Mapping

from interlock.domain.events import ToolResultObserved


class IdempotencyErrorCode(str, Enum):
    """Stable EXE-002 idempotency boundary failures."""

    INVALID_IDENTITY_INPUT = "INVALID_IDENTITY_INPUT"
    IDEMPOTENCY_CONFLICT = "IDEMPOTENCY_CONFLICT"
    INVALID_CALLBACK = "INVALID_CALLBACK"


class IdempotencyError(ValueError):
    """A deterministic identity could not be constructed safely."""

    def __init__(self, code: IdempotencyErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code


class IdempotencyStatus(str, Enum):
    """Classification against a caller-provided idempotency snapshot."""

    NEW = "NEW"
    DUPLICATE = "DUPLICATE"


@dataclass(frozen=True, slots=True)
class IdempotencyDecision:
    """Pure same-key/same-arguments classification."""

    status: IdempotencyStatus
    idempotency_key: str
    argument_digest: str


class CallbackStatus(str, Enum):
    """Classification of a provider callback observation."""

    NEW = "NEW"
    DUPLICATE = "DUPLICATE"
    CONFLICT = "CONFLICT"


@dataclass(frozen=True, slots=True)
class CallbackDecision:
    """Pure callback classification without interpreting external truth."""

    status: CallbackStatus
    callback_dedupe_key: str
    observation_digest: str
    requires_verification: bool


def strict_json_copy(value: Any, *, field: str = "value") -> Any:
    """Return a detached strict-JSON value or fail closed.

    Exact built-in types are required so tuples, sets, custom containers,
    non-string keys, cycles, and non-finite numbers cannot silently acquire a
    process-specific identity.
    """

    try:
        return _strict_json(value, field, set())
    except IdempotencyError:
        raise
    except Exception as exc:  # defensive boundary for hostile containers
        raise IdempotencyError(
            IdempotencyErrorCode.INVALID_IDENTITY_INPUT,
            f"{field} could not be normalized safely",
        ) from exc


def canonical_json(value: Any) -> str:
    """Serialize strict JSON using the repository's canonical hash format."""

    normalized = strict_json_copy(value)
    return json.dumps(
        normalized,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def normalize_consequential_arguments(
    arguments: Mapping[str, Any],
    *,
    provider_key_field: str | None = None,
) -> dict[str, Any]:
    """Detach arguments and exclude a provider key from logical identity.

    Provider idempotency keys are derived from the logical action, so including
    that field in the logical-action hash would create circular identity.
    """

    if type(arguments) is not dict:
        raise IdempotencyError(
            IdempotencyErrorCode.INVALID_IDENTITY_INPUT,
            "arguments must be a strict JSON object",
        )
    normalized = strict_json_copy(arguments, field="arguments")
    if provider_key_field is not None:
        _nonempty_string(provider_key_field, "provider_key_field")
        normalized.pop(provider_key_field, None)
    return normalized


def consequential_argument_digest(arguments: Mapping[str, Any]) -> str:
    """Return the stable SHA-256 digest used by idempotency indexes."""

    if type(arguments) is not dict:
        raise IdempotencyError(
            IdempotencyErrorCode.INVALID_IDENTITY_INPUT,
            "consequential arguments must be a strict JSON object",
        )
    return _digest(arguments)


def derive_logical_action_id(
    *,
    tool_name: str,
    consequential_arguments: Mapping[str, Any],
    intent_goal_id: str,
) -> str:
    """Derive stable action identity from tool, arguments, and goal identity."""

    tool = _nonempty_string(tool_name, "tool_name")
    goal = _nonempty_string(intent_goal_id, "intent_goal_id")
    arguments = normalize_consequential_arguments(consequential_arguments)
    return _digest(
        {
            "tool_name": tool,
            "consequential_arguments": arguments,
            "intent_goal_id": goal,
        }
    )


def derive_idempotency_key(
    *,
    session_id: str,
    logical_action_id: str,
    manifest_version: int,
) -> str:
    """Derive a stable key scoped by the trusted tool manifest version."""

    session = _nonempty_string(session_id, "session_id")
    logical_action = _nonempty_string(logical_action_id, "logical_action_id")
    if (
        isinstance(manifest_version, bool)
        or not isinstance(manifest_version, int)
        or manifest_version < 1
    ):
        raise IdempotencyError(
            IdempotencyErrorCode.INVALID_IDENTITY_INPUT,
            "manifest_version must be a positive integer",
        )
    return _digest(
        {
            "session_id": session,
            "logical_action_id": logical_action,
            "manifest_version": manifest_version,
        }
    )


def classify_idempotency(
    *,
    idempotency_key: str,
    consequential_arguments: Mapping[str, Any],
    known_argument_digests: Mapping[str, str],
) -> IdempotencyDecision:
    """Classify a key against an explicit, non-authoritative index snapshot.

    The snapshot maps idempotency keys to digests from
    :func:`consequential_argument_digest`.  Same key/same arguments is a safe
    duplicate identity; same key/different arguments fails closed.
    """

    key = _nonempty_string(idempotency_key, "idempotency_key")
    if not isinstance(known_argument_digests, Mapping):
        raise IdempotencyError(
            IdempotencyErrorCode.INVALID_IDENTITY_INPUT,
            "known_argument_digests must be a mapping",
        )
    digest = consequential_argument_digest(consequential_arguments)
    existing = known_argument_digests.get(key)
    if existing is None:
        return IdempotencyDecision(IdempotencyStatus.NEW, key, digest)
    _require_digest(existing, "known argument digest")
    if existing != digest:
        raise IdempotencyError(
            IdempotencyErrorCode.IDEMPOTENCY_CONFLICT,
            "idempotency key is already associated with different arguments",
        )
    return IdempotencyDecision(IdempotencyStatus.DUPLICATE, key, digest)


def callback_observation_digest(observation: ToolResultObserved) -> str:
    """Digest one complete canonical callback observation."""

    callback = _require_callback(observation)
    return _digest(
        {
            "operation_id": callback.operation_id,
            "provider_request_id": callback.provider_request_id,
            "provider_effect_id": callback.provider_effect_id,
            "outcome": callback.outcome,
            "result": strict_json_copy(callback.result, field="callback.result"),
        }
    )


def classify_callback(
    observation: ToolResultObserved,
    *,
    callback_dedupe_key: str,
    known_observation_digests: Mapping[str, str],
) -> CallbackDecision:
    """Classify a callback as new, duplicate, or conflicting.

    Conflicting observations for one provider correlation identity never use
    arrival order as truth.  They request later verification by the owning
    runtime/effect layers.
    """

    if not isinstance(known_observation_digests, Mapping):
        raise IdempotencyError(
            IdempotencyErrorCode.INVALID_CALLBACK,
            "known_observation_digests must be a mapping",
        )
    dedupe_key = _nonempty_string(callback_dedupe_key, "callback_dedupe_key")
    observation_digest = callback_observation_digest(observation)
    existing = known_observation_digests.get(dedupe_key)
    if existing is None:
        return CallbackDecision(
            CallbackStatus.NEW,
            dedupe_key,
            observation_digest,
            False,
        )
    _require_digest(existing, "known callback digest")
    if existing == observation_digest:
        return CallbackDecision(
            CallbackStatus.DUPLICATE,
            dedupe_key,
            observation_digest,
            False,
        )
    return CallbackDecision(
        CallbackStatus.CONFLICT,
        dedupe_key,
        observation_digest,
        True,
    )


def _strict_json(value: Any, path: str, active: set[int]) -> Any:
    if value is None or type(value) in (str, bool, int):
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise IdempotencyError(
                IdempotencyErrorCode.INVALID_IDENTITY_INPUT,
                f"{path} contains a non-finite number",
            )
        return value
    if type(value) is list:
        identity = id(value)
        if identity in active:
            raise IdempotencyError(
                IdempotencyErrorCode.INVALID_IDENTITY_INPUT,
                f"{path} contains a cycle",
            )
        active.add(identity)
        try:
            return [
                _strict_json(item, f"{path}[{index}]", active)
                for index, item in enumerate(value)
            ]
        finally:
            active.remove(identity)
    if type(value) is dict:
        identity = id(value)
        if identity in active:
            raise IdempotencyError(
                IdempotencyErrorCode.INVALID_IDENTITY_INPUT,
                f"{path} contains a cycle",
            )
        active.add(identity)
        try:
            result: dict[str, Any] = {}
            for key, item in value.items():
                if type(key) is not str:
                    raise IdempotencyError(
                        IdempotencyErrorCode.INVALID_IDENTITY_INPUT,
                        f"{path} contains a non-string key",
                    )
                result[key] = _strict_json(item, f"{path}.{key}", active)
            return result
        finally:
            active.remove(identity)
    raise IdempotencyError(
        IdempotencyErrorCode.INVALID_IDENTITY_INPUT,
        f"{path} contains a non-JSON value",
    )


def _digest(value: Any) -> str:
    encoded = canonical_json(value).encode("utf-8")
    return f"sha256:{sha256(encoded).hexdigest()}"


def _nonempty_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise IdempotencyError(
            IdempotencyErrorCode.INVALID_IDENTITY_INPUT,
            f"{field} must be a non-empty string",
        )
    return value


def _require_digest(value: Any, field: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 71
        or not value.startswith("sha256:")
        or any(character not in "0123456789abcdef" for character in value[7:])
    ):
        raise IdempotencyError(
            IdempotencyErrorCode.INVALID_IDENTITY_INPUT,
            f"{field} must be a canonical SHA-256 digest",
        )
    return value


def _require_callback(observation: ToolResultObserved) -> ToolResultObserved:
    if not isinstance(observation, ToolResultObserved):
        raise IdempotencyError(
            IdempotencyErrorCode.INVALID_CALLBACK,
            "observation must be a ToolResultObserved payload",
        )
    return ToolResultObserved.model_validate(
        observation.model_dump(mode="python")
    )
