"""Conservative tool-manifest normalization and registration for EXE-001.

The registry is a trust boundary only: it validates capability declarations and
retains normalized descriptors.  It never invokes tools or makes dispatch,
retry, cancellation, or compensation decisions.
"""

from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
import math
from typing import Any, Mapping, TypeVar

from interlock.domain.enums import (
    ActionType,
    CancellationPolicy,
    EffectClassification,
    SafePointName,
)
from interlock.domain.models import (
    CompensationPolicy,
    ConfirmationSemantics,
    IdempotencyPolicy,
    RetryPolicy,
    ToolDescriptor,
)


SUPPORTED_MANIFEST_VERSION = 1
DEFAULT_TOOL_TIMEOUT_MS = 5_000
MIN_TOOL_TIMEOUT_MS = 100
MAX_TOOL_TIMEOUT_MS = 60_000

_MANIFEST_FIELDS = frozenset(
    {
        "tool_name",
        "manifest_version",
        "argument_schema",
        "result_schema",
        "effect_classification",
        "action_type",
        "cancellation_policy",
        "safe_points",
        "timeout_ms",
        "retry_policy",
        "idempotency",
        "compensation",
        "confirmation_semantics",
    }
)

_RETRY_FIELDS = frozenset({"max_attempts", "retry_on"})
_IDEMPOTENCY_FIELDS = frozenset({"supported", "scope", "key_field"})
_COMPENSATION_FIELDS = frozenset(
    {"supported", "tool_name", "requires_authorization"}
)
_CONFIRMATION_FIELDS = frozenset(
    {"acknowledgement", "commit", "unknown", "authoritative_fields"}
)

_EnumT = TypeVar("_EnumT")


class ManifestRegistrationError(ValueError):
    """An untrusted manifest could not be normalized safely."""


class ToolRegistry:
    """In-memory registry of normalized, defensively copied tool descriptors."""

    def __init__(self, *, default_timeout_ms: int = DEFAULT_TOOL_TIMEOUT_MS) -> None:
        self._default_timeout_ms = _bounded_timeout(
            default_timeout_ms,
            field="default_timeout_ms",
        )
        self._descriptors: dict[str, ToolDescriptor] = {}
        self._capability_hashes: dict[str, str] = {}

    def register(self, raw_manifest: Mapping[str, Any]) -> ToolDescriptor:
        """Normalize and register an untrusted manifest.

        Re-registering an equivalent manifest is idempotent.  A material
        capability change atomically replaces the prior registration and
        receives a different capability hash.
        """

        manifest = _copy_manifest(raw_manifest)
        _reject_unknown_fields(manifest, _MANIFEST_FIELDS, field="manifest")

        tool_name = _tool_name(manifest.get("tool_name"))
        manifest_version = _manifest_version(manifest.get("manifest_version", 1))
        argument_schema = _schema(manifest.get("argument_schema"), "argument_schema")
        result_schema = _schema(manifest.get("result_schema"), "result_schema")

        effect = _enum_or_conservative(
            manifest.get("effect_classification"),
            EffectClassification,
            EffectClassification.UNKNOWN,
            field="effect_classification",
        )
        action = _enum_or_conservative(
            manifest.get("action_type"),
            ActionType,
            ActionType.IRREVERSIBLE,
            field="action_type",
        )
        cancellation = _enum_or_conservative(
            manifest.get("cancellation_policy"),
            CancellationPolicy,
            CancellationPolicy.NONCANCELLABLE,
            field="cancellation_policy",
        )
        safe_points = _safe_points(manifest.get("safe_points"))
        if cancellation == CancellationPolicy.AT_SAFEPOINT and not safe_points:
            cancellation = CancellationPolicy.NONCANCELLABLE
        if cancellation != CancellationPolicy.AT_SAFEPOINT:
            safe_points = []

        descriptor = ToolDescriptor(
            tool_name=tool_name,
            manifest_version=manifest_version,
            argument_schema=argument_schema,
            result_schema=result_schema,
            effect_classification=effect,
            action_type=action,
            cancellation_policy=cancellation,
            safe_points=safe_points,
            timeout_ms=_bounded_timeout(
                manifest.get("timeout_ms", self._default_timeout_ms),
                field="timeout_ms",
            ),
            retry_policy=_retry_policy(manifest.get("retry_policy")),
            idempotency=_idempotency_policy(manifest.get("idempotency")),
            compensation=self._compensation_policy(
                manifest.get("compensation"),
                registering_tool=tool_name,
            ),
            confirmation_semantics=_confirmation_semantics(
                manifest.get("confirmation_semantics")
            ),
        )

        trusted = descriptor.model_copy(deep=True)
        fingerprint = _capability_fingerprint(trusted)
        self._descriptors[tool_name] = trusted
        self._capability_hashes[tool_name] = fingerprint
        return trusted.model_copy(deep=True)

    def get(self, tool_name: str) -> ToolDescriptor:
        """Return a defensive copy of a registered descriptor."""

        normalized_name = _tool_name(tool_name)
        try:
            descriptor = self._descriptors[normalized_name]
        except KeyError as exc:
            raise KeyError(f"Tool is not registered: {normalized_name}") from exc
        return descriptor.model_copy(deep=True)

    def capability_hash(self, tool_name: str) -> str:
        """Return the stable SHA-256 fingerprint for current capabilities."""

        normalized_name = _tool_name(tool_name)
        try:
            return self._capability_hashes[normalized_name]
        except KeyError as exc:
            raise KeyError(f"Tool is not registered: {normalized_name}") from exc

    def _compensation_policy(
        self,
        value: Any,
        *,
        registering_tool: str,
    ) -> CompensationPolicy:
        if value is None or not isinstance(value, Mapping):
            return CompensationPolicy(supported=False)

        policy = _plain_mapping(value, field="compensation")
        _reject_unknown_fields(
            policy,
            _COMPENSATION_FIELDS,
            field="compensation",
        )
        supported = _optional_bool(policy.get("supported", False), "compensation.supported")
        if not supported:
            return CompensationPolicy(supported=False)

        compensation_tool = _tool_name(policy.get("tool_name"))
        if compensation_tool == registering_tool:
            raise ManifestRegistrationError(
                "compensation.tool_name must not reference the registering tool"
            )
        if compensation_tool not in self._descriptors:
            raise ManifestRegistrationError(
                "compensation.tool_name must reference an already registered tool: "
                f"{compensation_tool}"
            )
        requires_authorization = _optional_bool(
            policy.get("requires_authorization", True),
            "compensation.requires_authorization",
        )
        return CompensationPolicy(
            supported=True,
            tool_name=compensation_tool,
            requires_authorization=requires_authorization,
        )


def _copy_manifest(raw_manifest: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(raw_manifest, Mapping):
        raise ManifestRegistrationError("manifest must be a mapping")
    try:
        copied = deepcopy(dict(raw_manifest))
    except Exception as exc:
        raise ManifestRegistrationError("manifest could not be copied safely") from exc
    if any(not isinstance(key, str) for key in copied):
        raise ManifestRegistrationError("manifest keys must be strings")
    return copied


def _tool_name(value: Any) -> str:
    if not isinstance(value, str):
        raise ManifestRegistrationError("tool_name must be a non-empty string")
    normalized = value.strip()
    has_control_character = any(
        ord(character) < 32 or ord(character) == 127 for character in normalized
    )
    if not normalized or has_control_character:
        raise ManifestRegistrationError(
            "tool_name must be a non-empty string without control characters"
        )
    return normalized


def _manifest_version(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ManifestRegistrationError("manifest_version must be integer 1")
    if value != SUPPORTED_MANIFEST_VERSION:
        raise ManifestRegistrationError(
            f"unsupported manifest_version {value}; expected {SUPPORTED_MANIFEST_VERSION}"
        )
    return value


def _bounded_timeout(value: Any, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ManifestRegistrationError(f"{field} must be an integer")
    return min(MAX_TOOL_TIMEOUT_MS, max(MIN_TOOL_TIMEOUT_MS, value))


def _enum_or_conservative(
    value: Any,
    enum_type: type[_EnumT],
    conservative: _EnumT,
    *,
    field: str,
) -> _EnumT:
    if value is None:
        return conservative
    if isinstance(value, enum_type):
        return value
    if not isinstance(value, str):
        raise ManifestRegistrationError(f"{field} must be a string when provided")
    try:
        return enum_type(value)  # type: ignore[call-arg,return-value]
    except ValueError:
        return conservative


def _safe_points(value: Any) -> list[SafePointName]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ManifestRegistrationError("safe_points must be a list")
    normalized: list[SafePointName] = []
    for item in value:
        if isinstance(item, SafePointName):
            safe_point = item
        elif isinstance(item, str):
            try:
                safe_point = SafePointName(item)
            except ValueError:
                continue
        else:
            raise ManifestRegistrationError("safe_points entries must be strings")
        if safe_point not in normalized:
            normalized.append(safe_point)
    return normalized


def _retry_policy(value: Any) -> RetryPolicy:
    if value is None or not isinstance(value, Mapping):
        return RetryPolicy(max_attempts=1, retry_on=[])
    policy = _plain_mapping(value, field="retry_policy")
    _reject_unknown_fields(policy, _RETRY_FIELDS, field="retry_policy")
    max_attempts = policy.get("max_attempts", 1)
    if isinstance(max_attempts, bool) or not isinstance(max_attempts, int) or max_attempts < 0:
        raise ManifestRegistrationError("retry_policy.max_attempts must be a non-negative integer")
    retry_on = _string_list(policy.get("retry_on", []), "retry_policy.retry_on")
    return RetryPolicy(max_attempts=max_attempts, retry_on=retry_on)


def _idempotency_policy(value: Any) -> IdempotencyPolicy:
    if value is None or not isinstance(value, Mapping):
        return IdempotencyPolicy(supported=False)
    policy = _plain_mapping(value, field="idempotency")
    _reject_unknown_fields(policy, _IDEMPOTENCY_FIELDS, field="idempotency")
    supported = _optional_bool(policy.get("supported", False), "idempotency.supported")
    if not supported:
        return IdempotencyPolicy(supported=False)
    return IdempotencyPolicy(
        supported=True,
        scope=_nonempty_string(policy.get("scope"), "idempotency.scope"),
        key_field=_nonempty_string(policy.get("key_field"), "idempotency.key_field"),
    )


def _confirmation_semantics(value: Any) -> ConfirmationSemantics:
    if value is None or not isinstance(value, Mapping):
        return ConfirmationSemantics()
    semantics = _plain_mapping(value, field="confirmation_semantics")
    _reject_unknown_fields(
        semantics,
        _CONFIRMATION_FIELDS,
        field="confirmation_semantics",
    )
    acknowledgement = _optional_nonempty_string(
        semantics.get("acknowledgement"),
        "confirmation_semantics.acknowledgement",
    )
    commit = _optional_nonempty_string(
        semantics.get("commit"),
        "confirmation_semantics.commit",
    )
    unknown = _optional_nonempty_string(
        semantics.get("unknown"),
        "confirmation_semantics.unknown",
    )
    tokens = [
        token
        for token in (acknowledgement, commit, unknown)
        if token is not None
    ]
    if len(tokens) != len(set(tokens)):
        raise ManifestRegistrationError(
            "confirmation acknowledgement, commit, and unknown tokens must be distinct"
        )
    return ConfirmationSemantics(
        acknowledgement=acknowledgement,
        commit=commit,
        unknown=unknown,
        authoritative_fields=_string_list(
            semantics.get("authoritative_fields", []),
            "confirmation_semantics.authoritative_fields",
        ),
    )


def _schema(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ManifestRegistrationError(f"{field} must be a schema mapping")
    schema = _plain_mapping(value, field=field)
    if not schema:
        raise ManifestRegistrationError(f"{field} must not be an empty permissive schema")
    _validate_json_value(schema, path=field, active=set())
    _validate_schema_keywords(schema, path=field)
    return schema


def _validate_schema_keywords(schema: Mapping[str, Any], *, path: str) -> None:
    type_value = schema.get("type")
    valid_types = {"null", "boolean", "object", "array", "number", "integer", "string"}
    if type_value is not None:
        if isinstance(type_value, str):
            declared = [type_value]
        elif isinstance(type_value, list):
            declared = type_value
        else:
            raise ManifestRegistrationError(
                f"{path}.type must be a string or non-empty list of strings"
            )
        if not declared or any(
            not isinstance(item, str) or item not in valid_types for item in declared
        ):
            raise ManifestRegistrationError(f"{path}.type contains an unsupported JSON type")
        if len(declared) != len(set(declared)):
            raise ManifestRegistrationError(f"{path}.type must not contain duplicates")

    if "required" in schema:
        required = schema["required"]
        if not isinstance(required, list) or any(
            not isinstance(item, str) or not item for item in required
        ):
            raise ManifestRegistrationError(f"{path}.required must be a list of non-empty strings")
        if len(required) != len(set(required)):
            raise ManifestRegistrationError(f"{path}.required must not contain duplicates")

    properties = schema.get("properties")
    if properties is not None:
        if not isinstance(properties, Mapping):
            raise ManifestRegistrationError(f"{path}.properties must be a mapping")
        for name, subschema in properties.items():
            _validate_subschema(subschema, path=f"{path}.properties.{name}")

    for keyword in ("oneOf", "anyOf", "allOf"):
        alternatives = schema.get(keyword)
        if alternatives is None:
            continue
        if not isinstance(alternatives, list) or not alternatives:
            raise ManifestRegistrationError(f"{path}.{keyword} must be a non-empty list")
        for index, subschema in enumerate(alternatives):
            _validate_subschema(subschema, path=f"{path}.{keyword}[{index}]")

    for keyword in ("items", "additionalProperties", "not", "if", "then", "else"):
        subschema = schema.get(keyword)
        if subschema is not None:
            _validate_subschema(subschema, path=f"{path}.{keyword}")


def _validate_subschema(value: Any, *, path: str) -> None:
    if isinstance(value, bool):
        return
    if not isinstance(value, Mapping):
        raise ManifestRegistrationError(f"{path} must be a schema mapping or boolean")
    _validate_schema_keywords(value, path=path)


def _validate_json_value(value: Any, *, path: str, active: set[int]) -> None:
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ManifestRegistrationError(f"{path} contains a non-finite number")
        return
    if isinstance(value, Mapping):
        identity = id(value)
        if identity in active:
            raise ManifestRegistrationError(f"{path} contains a cycle")
        active.add(identity)
        try:
            for key, item in value.items():
                if not isinstance(key, str):
                    raise ManifestRegistrationError(f"{path} contains a non-string key")
                _validate_json_value(item, path=f"{path}.{key}", active=active)
        finally:
            active.remove(identity)
        return
    if isinstance(value, list):
        identity = id(value)
        if identity in active:
            raise ManifestRegistrationError(f"{path} contains a cycle")
        active.add(identity)
        try:
            for index, item in enumerate(value):
                _validate_json_value(item, path=f"{path}[{index}]", active=active)
        finally:
            active.remove(identity)
        return
    raise ManifestRegistrationError(f"{path} contains a non-JSON value")


def _capability_fingerprint(descriptor: ToolDescriptor) -> str:
    canonical = json.dumps(
        descriptor.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return f"sha256:{sha256(canonical).hexdigest()}"


def _plain_mapping(value: Mapping[str, Any], *, field: str) -> dict[str, Any]:
    result = dict(value)
    if any(not isinstance(key, str) for key in result):
        raise ManifestRegistrationError(f"{field} keys must be strings")
    return result


def _reject_unknown_fields(
    value: Mapping[str, Any],
    allowed: frozenset[str],
    *,
    field: str,
) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise ManifestRegistrationError(f"{field} contains unknown fields: {', '.join(unknown)}")


def _optional_bool(value: Any, field: str) -> bool:
    if not isinstance(value, bool):
        raise ManifestRegistrationError(f"{field} must be a boolean")
    return value


def _nonempty_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ManifestRegistrationError(f"{field} must be a non-empty string")
    return value.strip()


def _optional_nonempty_string(value: Any, field: str) -> str | None:
    if value is None:
        return None
    return _nonempty_string(value, field)


def _string_list(value: Any, field: str) -> list[str]:
    if not isinstance(value, list):
        raise ManifestRegistrationError(f"{field} must be a list")
    normalized: list[str] = []
    for item in value:
        normalized_item = _nonempty_string(item, field)
        if normalized_item not in normalized:
            normalized.append(normalized_item)
    return normalized
