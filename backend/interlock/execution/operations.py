"""Pure EXE-002 operation construction and callback-correlation policy.

The reducer remains the only authoritative operation-state writer.  This
module validates one planned operation and returns a detached canonical
``OperationRecord`` for the normal ``OperationCreated`` journal path.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
import re
from typing import Any, Collection, Mapping, Sequence

from interlock.domain.enums import (
    ActionType,
    CancellationState,
    EffectClassification,
    EffectState,
    OperationState,
)
from interlock.domain.events import OperationCreated, ToolResultObserved
from interlock.domain.models import (
    DependencyBinding,
    IntentRevision,
    OperationRecord,
    ToolDescriptor,
)
from interlock.execution.descriptors import ToolRegistry
from interlock.execution.idempotency import (
    CallbackDecision,
    IdempotencyError,
    IdempotencyErrorCode,
    classify_callback,
    classify_idempotency,
    derive_idempotency_key,
    derive_logical_action_id,
    normalize_consequential_arguments,
    strict_json_copy,
)
from interlock.intelligence.intent_graph import (
    DependencySnapshot,
    IntentGraphError,
    bind_dependencies,
    dependency_fingerprint,
)


class OperationErrorCode(str, Enum):
    """Stable EXE-002 operation boundary failures."""

    UNKNOWN_DESCRIPTOR = "UNKNOWN_DESCRIPTOR"
    INVALID_ARGUMENTS = "INVALID_ARGUMENTS"
    DUPLICATE_OPERATION_ID = "DUPLICATE_OPERATION_ID"
    INVALID_DEPENDENCY_BINDING = "INVALID_DEPENDENCY_BINDING"
    SPECULATION_FORBIDDEN = "SPECULATION_FORBIDDEN"
    IDEMPOTENCY_CONFLICT = "IDEMPOTENCY_CONFLICT"
    CALLBACK_CORRELATION_CONFLICT = "CALLBACK_CORRELATION_CONFLICT"
    INVALID_OPERATION_INPUT = "INVALID_OPERATION_INPUT"


class OperationError(ValueError):
    """A planned operation or callback failed deterministic validation."""

    def __init__(self, code: OperationErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code


class OperationManager:
    """Construct operations from trusted descriptors and immutable snapshots."""

    def __init__(self, registry: ToolRegistry) -> None:
        if not isinstance(registry, ToolRegistry):
            raise TypeError("registry must be a ToolRegistry")
        self._registry = registry

    def create_operation(
        self,
        *,
        operation_id: str,
        session_id: str,
        intent_goal_id: str,
        intent_revision: IntentRevision,
        bindings: Sequence[DependencyBinding | DependencySnapshot],
        tool_name: str,
        arguments: Mapping[str, Any],
        contract_version: str | int,
        speculative: bool = False,
        existing_operation_ids: Collection[str] = (),
        known_idempotency_digests: Mapping[str, str] | None = None,
    ) -> OperationRecord:
        """Validate and construct one canonical operation in CREATED state."""

        op_id = _nonempty_string(operation_id, "operation_id")
        session = _nonempty_string(session_id, "session_id")
        goal_id = _nonempty_string(intent_goal_id, "intent_goal_id")
        tool = _nonempty_string(tool_name, "tool_name")
        if not isinstance(speculative, bool):
            raise OperationError(
                OperationErrorCode.INVALID_OPERATION_INPUT,
                "speculative must be a boolean",
            )
        if isinstance(existing_operation_ids, (str, bytes)) or not isinstance(
            existing_operation_ids, Collection
        ):
            raise OperationError(
                OperationErrorCode.INVALID_OPERATION_INPUT,
                "existing_operation_ids must be a collection of IDs",
            )
        if any(not isinstance(item, str) for item in existing_operation_ids):
            raise OperationError(
                OperationErrorCode.INVALID_OPERATION_INPUT,
                "existing_operation_ids must contain only strings",
            )
        if op_id in existing_operation_ids:
            raise OperationError(
                OperationErrorCode.DUPLICATE_OPERATION_ID,
                "operation_id already exists",
            )
        if not isinstance(intent_revision, IntentRevision):
            raise OperationError(
                OperationErrorCode.INVALID_OPERATION_INPUT,
                "intent_revision must be an IntentRevision",
            )
        revision = IntentRevision.model_validate(
            intent_revision.model_dump(mode="python")
        )
        if revision.intent_id != goal_id:
            raise OperationError(
                OperationErrorCode.INVALID_OPERATION_INPUT,
                "intent_goal_id must match the revision's stable intent identity",
            )

        descriptor = self._descriptor(tool)
        self._validate_speculation(descriptor, speculative)
        domain_bindings = _validated_bindings(revision, bindings)
        fingerprint = dependency_fingerprint(domain_bindings)

        try:
            detached_arguments = strict_json_copy(arguments, field="arguments")
        except IdempotencyError as exc:
            raise OperationError(
                OperationErrorCode.INVALID_ARGUMENTS,
                "arguments must contain only strict JSON values",
            ) from exc
        if not isinstance(detached_arguments, dict):
            raise OperationError(
                OperationErrorCode.INVALID_ARGUMENTS,
                "arguments must be a JSON object",
            )

        provider_key_field = (
            descriptor.idempotency.key_field
            if descriptor.idempotency.supported
            else None
        )
        try:
            consequential_arguments = normalize_consequential_arguments(
                detached_arguments,
                provider_key_field=provider_key_field,
            )
            logical_action_id = derive_logical_action_id(
                tool_name=descriptor.tool_name,
                consequential_arguments=consequential_arguments,
                intent_goal_id=goal_id,
            )
            idempotency_key = derive_idempotency_key(
                session_id=session,
                logical_action_id=logical_action_id,
                contract_version=contract_version,
            )
        except IdempotencyError as exc:
            raise OperationError(
                OperationErrorCode.INVALID_ARGUMENTS,
                "operation identity inputs are invalid",
            ) from exc

        final_arguments = strict_json_copy(detached_arguments, field="arguments")
        if provider_key_field is not None:
            supplied_key = final_arguments.get(provider_key_field)
            if supplied_key is not None and supplied_key != idempotency_key:
                raise OperationError(
                    OperationErrorCode.IDEMPOTENCY_CONFLICT,
                    "caller-supplied provider idempotency key conflicts with derived identity",
                )
            final_arguments[provider_key_field] = idempotency_key

        _validate_arguments(final_arguments, descriptor.argument_schema)
        try:
            classify_idempotency(
                idempotency_key=idempotency_key,
                consequential_arguments=consequential_arguments,
                known_argument_digests=(
                    {}
                    if known_idempotency_digests is None
                    else known_idempotency_digests
                ),
            )
        except IdempotencyError as exc:
            code = (
                OperationErrorCode.IDEMPOTENCY_CONFLICT
                if exc.code == IdempotencyErrorCode.IDEMPOTENCY_CONFLICT
                else OperationErrorCode.INVALID_OPERATION_INPUT
            )
            raise OperationError(code, "idempotency snapshot rejected the operation") from exc

        return OperationRecord(
            operation_id=op_id,
            tool_name=descriptor.tool_name,
            args=final_arguments,
            intent_revision_id=revision.revision_id,
            bindings=[binding.model_copy(deep=True) for binding in domain_bindings],
            fingerprint=fingerprint,
            action_type=descriptor.action_type,
            cancellation_policy=descriptor.cancellation_policy,
            state=OperationState.CREATED,
            cancellation_state=CancellationState.NONE,
            effect_state=EffectState.NOT_STARTED,
            speculative=speculative,
            logical_action_id=logical_action_id,
            idempotency_key=idempotency_key,
        )

    @staticmethod
    def creation_event(operation: OperationRecord) -> OperationCreated:
        """Wrap a detached record in the canonical event payload model."""

        if not isinstance(operation, OperationRecord):
            raise TypeError("operation must be an OperationRecord")
        return OperationCreated(operation=operation.model_copy(deep=True))

    @staticmethod
    def classify_result(
        operation: OperationRecord,
        observation: ToolResultObserved,
        *,
        known_observation_digests: Mapping[str, str],
    ) -> CallbackDecision:
        """Validate correlation, then apply pure duplicate/conflict policy.

        Local terminal or superseded state is intentionally irrelevant: late
        provider observations remain admissible for the reducer/effect path.
        """

        if not isinstance(operation, OperationRecord):
            raise TypeError("operation must be an OperationRecord")
        if not isinstance(observation, ToolResultObserved):
            raise TypeError("observation must be a ToolResultObserved")
        if observation.operation_id != operation.operation_id:
            raise OperationError(
                OperationErrorCode.CALLBACK_CORRELATION_CONFLICT,
                "callback operation_id does not match the intended operation",
            )
        if operation.provider_request_id is None:
            raise OperationError(
                OperationErrorCode.CALLBACK_CORRELATION_CONFLICT,
                "operation has no established provider_request_id",
            )
        if observation.provider_request_id != operation.provider_request_id:
            raise OperationError(
                OperationErrorCode.CALLBACK_CORRELATION_CONFLICT,
                "callback provider_request_id does not match the operation",
            )
        try:
            return classify_callback(
                observation,
                known_observation_digests=known_observation_digests,
            )
        except IdempotencyError as exc:
            raise OperationError(
                OperationErrorCode.CALLBACK_CORRELATION_CONFLICT,
                "callback identity snapshot is invalid",
            ) from exc

    def _descriptor(self, tool_name: str) -> ToolDescriptor:
        try:
            return self._registry.get(tool_name)
        except (KeyError, ValueError) as exc:
            raise OperationError(
                OperationErrorCode.UNKNOWN_DESCRIPTOR,
                "tool is not registered",
            ) from exc

    @staticmethod
    def _validate_speculation(
        descriptor: ToolDescriptor,
        speculative: bool,
    ) -> None:
        if speculative and not (
            descriptor.action_type == ActionType.READ_ONLY
            and descriptor.effect_classification == EffectClassification.NONE
        ):
            raise OperationError(
                OperationErrorCode.SPECULATION_FORBIDDEN,
                "speculation requires a trusted READ_ONLY/NONE descriptor",
            )


def _validated_bindings(
    revision: IntentRevision,
    bindings: Sequence[DependencyBinding | DependencySnapshot],
) -> tuple[DependencyBinding, ...]:
    if isinstance(bindings, (str, bytes)) or not isinstance(bindings, Sequence):
        raise OperationError(
            OperationErrorCode.INVALID_DEPENDENCY_BINDING,
            "bindings must be a sequence",
        )
    if not bindings:
        raise OperationError(
            OperationErrorCode.INVALID_DEPENDENCY_BINDING,
            "at least one exact dependency binding is required",
        )
    supplied: list[DependencyBinding] = []
    for binding in bindings:
        if isinstance(binding, DependencySnapshot):
            supplied.append(binding.as_domain())
        elif isinstance(binding, DependencyBinding):
            supplied.append(binding.model_copy(deep=True))
        else:
            raise OperationError(
                OperationErrorCode.INVALID_DEPENDENCY_BINDING,
                "binding must be a DependencyBinding or DependencySnapshot",
            )
    try:
        supplied_fingerprint = dependency_fingerprint(supplied)
        expected = bind_dependencies(
            revision,
            (binding.path for binding in supplied),
            evidence_ids_by_path={
                binding.path: tuple(binding.evidence_ids) for binding in supplied
            },
        )
        if dependency_fingerprint(expected) != supplied_fingerprint:
            raise OperationError(
                OperationErrorCode.INVALID_DEPENDENCY_BINDING,
                "dependency bindings do not match the supplied intent revision",
            )
        return tuple(binding.as_domain() for binding in expected)
    except OperationError:
        raise
    except IntentGraphError as exc:
        raise OperationError(
            OperationErrorCode.INVALID_DEPENDENCY_BINDING,
            "dependency bindings are malformed or do not match the revision",
        ) from exc


_SCHEMA_ANNOTATIONS = frozenset({"$schema", "$id", "title", "description", "default"})
_SCHEMA_KEYWORDS = frozenset(
    {
        "type",
        "required",
        "properties",
        "additionalProperties",
        "items",
        "minLength",
        "maxLength",
        "enum",
        "const",
        "format",
        "minimum",
        "maximum",
        "minItems",
        "maxItems",
        "oneOf",
        "anyOf",
        "allOf",
    }
) | _SCHEMA_ANNOTATIONS


def _validate_arguments(arguments: dict[str, Any], schema: Mapping[str, Any]) -> None:
    try:
        _validate_supported_schema(schema, path="argument_schema")
        _validate_schema_value(arguments, schema, path="arguments")
    except OperationError:
        raise
    except Exception as exc:
        raise OperationError(
            OperationErrorCode.INVALID_ARGUMENTS,
            "arguments could not be validated safely",
        ) from exc


def _validate_supported_schema(schema: Any, *, path: str) -> None:
    """Fail closed on unsupported or malformed schema structure.

    This preflight is deliberately separate from value matching so a malformed
    ``oneOf``/``anyOf``/``allOf`` branch cannot be mistaken for an ordinary
    branch that simply did not match the runtime value.
    """

    if isinstance(schema, bool):
        return
    if not isinstance(schema, Mapping):
        raise _invalid_argument(path, "must be a schema object or boolean")
    unknown = sorted(set(schema) - _SCHEMA_KEYWORDS)
    if unknown:
        raise _invalid_argument(path, "uses unsupported descriptor schema semantics")

    declared = schema.get("type")
    if declared is not None:
        types = [declared] if isinstance(declared, str) else declared
        supported_types = {
            "null",
            "boolean",
            "object",
            "array",
            "number",
            "integer",
            "string",
        }
        if (
            not isinstance(types, list)
            or not types
            or any(item not in supported_types for item in types)
            or len(types) != len(set(types))
        ):
            raise _invalid_argument(path, "has an invalid type declaration")

    required = schema.get("required")
    if required is not None and (
        not isinstance(required, list)
        or any(not isinstance(item, str) or not item for item in required)
        or len(required) != len(set(required))
    ):
        raise _invalid_argument(path, "has an invalid required declaration")

    properties = schema.get("properties")
    if properties is not None:
        if not isinstance(properties, Mapping) or any(
            not isinstance(name, str) for name in properties
        ):
            raise _invalid_argument(path, "has an invalid properties declaration")
        for name, subschema in properties.items():
            _validate_supported_schema(
                subschema,
                path=f"{path}.properties.{name}",
            )

    for keyword in ("items", "additionalProperties"):
        if keyword in schema:
            _validate_supported_schema(
                schema[keyword],
                path=f"{path}.{keyword}",
            )

    for keyword in ("allOf", "anyOf", "oneOf"):
        if keyword not in schema:
            continue
        alternatives = schema[keyword]
        if not isinstance(alternatives, list) or not alternatives:
            raise _invalid_argument(path, f"has invalid {keyword} schema")
        for index, alternative in enumerate(alternatives):
            _validate_supported_schema(
                alternative,
                path=f"{path}.{keyword}[{index}]",
            )

    for keyword in ("minLength", "maxLength", "minItems", "maxItems"):
        if keyword in schema:
            _schema_int(schema[keyword], f"{path}.{keyword}")
    if (
        "minLength" in schema
        and "maxLength" in schema
        and schema["minLength"] > schema["maxLength"]
    ):
        raise _invalid_argument(path, "has inconsistent string bounds")
    if (
        "minItems" in schema
        and "maxItems" in schema
        and schema["minItems"] > schema["maxItems"]
    ):
        raise _invalid_argument(path, "has inconsistent array bounds")

    for keyword in ("minimum", "maximum"):
        if keyword in schema:
            _schema_number(schema[keyword], f"{path}.{keyword}")
    if (
        "minimum" in schema
        and "maximum" in schema
        and schema["minimum"] > schema["maximum"]
    ):
        raise _invalid_argument(path, "has inconsistent numeric bounds")

    if "format" in schema and schema["format"] != "date-time":
        raise _invalid_argument(path, "uses an unsupported string format")
    if "enum" in schema and (
        not isinstance(schema["enum"], list) or not schema["enum"]
    ):
        raise _invalid_argument(path, "has an invalid enum declaration")


def _validate_schema_value(value: Any, schema: Any, *, path: str) -> None:
    if schema is True:
        return
    if schema is False:
        raise _invalid_argument(path, "is forbidden by the descriptor schema")
    if not isinstance(schema, Mapping):
        raise _invalid_argument(path, "uses an invalid descriptor schema")
    unknown = sorted(set(schema) - _SCHEMA_KEYWORDS)
    if unknown:
        raise _invalid_argument(path, "uses unsupported descriptor schema semantics")

    for keyword in ("allOf", "anyOf", "oneOf"):
        if keyword not in schema:
            continue
        alternatives = schema[keyword]
        if not isinstance(alternatives, list) or not alternatives:
            raise _invalid_argument(path, f"has invalid {keyword} schema")
        matches = 0
        for alternative in alternatives:
            try:
                _validate_schema_value(value, alternative, path=path)
            except OperationError:
                continue
            matches += 1
        if keyword == "allOf" and matches != len(alternatives):
            raise _invalid_argument(path, "does not satisfy allOf")
        if keyword == "anyOf" and matches == 0:
            raise _invalid_argument(path, "does not satisfy anyOf")
        if keyword == "oneOf" and matches != 1:
            raise _invalid_argument(path, "does not satisfy exactly one oneOf branch")

    if "const" in schema and value != schema["const"]:
        raise _invalid_argument(path, "does not match const")
    if "enum" in schema:
        options = schema["enum"]
        if not isinstance(options, list) or not any(value == item for item in options):
            raise _invalid_argument(path, "is not an allowed enum value")

    declared = schema.get("type")
    if declared is not None:
        types = [declared] if isinstance(declared, str) else declared
        if not isinstance(types, list) or not types or any(
            not isinstance(item, str) for item in types
        ):
            raise _invalid_argument(path, "has invalid type schema")
        if not any(_matches_json_type(value, item) for item in types):
            raise _invalid_argument(path, "has the wrong JSON type")

    if type(value) is dict:
        required = schema.get("required", [])
        if not isinstance(required, list) or any(
            not isinstance(item, str) for item in required
        ):
            raise _invalid_argument(path, "has invalid required schema")
        missing = [item for item in required if item not in value]
        if missing:
            raise _invalid_argument(path, "is missing required properties")
        properties = schema.get("properties", {})
        if not isinstance(properties, Mapping):
            raise _invalid_argument(path, "has invalid properties schema")
        for key, item in value.items():
            if key in properties:
                _validate_schema_value(item, properties[key], path=f"{path}.{key}")
                continue
            additional = schema.get("additionalProperties", True)
            if additional is False:
                raise _invalid_argument(path, "contains an additional property")
            if isinstance(additional, Mapping) or isinstance(additional, bool):
                _validate_schema_value(item, additional, path=f"{path}.{key}")
            else:
                raise _invalid_argument(path, "has invalid additionalProperties schema")

    if type(value) is list:
        if "minItems" in schema and len(value) < _schema_int(schema["minItems"], path):
            raise _invalid_argument(path, "has too few items")
        if "maxItems" in schema and len(value) > _schema_int(schema["maxItems"], path):
            raise _invalid_argument(path, "has too many items")
        if "items" in schema:
            for index, item in enumerate(value):
                _validate_schema_value(item, schema["items"], path=f"{path}[{index}]")

    if type(value) is str:
        if "minLength" in schema and len(value) < _schema_int(schema["minLength"], path):
            raise _invalid_argument(path, "is shorter than minLength")
        if "maxLength" in schema and len(value) > _schema_int(schema["maxLength"], path):
            raise _invalid_argument(path, "is longer than maxLength")
        if "format" in schema:
            if schema["format"] != "date-time":
                raise _invalid_argument(path, "uses an unsupported string format")
            _validate_datetime(value, path)

    if type(value) in (int, float) and type(value) is not bool:
        if "minimum" in schema and value < _schema_number(schema["minimum"], path):
            raise _invalid_argument(path, "is below minimum")
        if "maximum" in schema and value > _schema_number(schema["maximum"], path):
            raise _invalid_argument(path, "is above maximum")


def _matches_json_type(value: Any, declared: str) -> bool:
    return {
        "null": value is None,
        "boolean": type(value) is bool,
        "object": type(value) is dict,
        "array": type(value) is list,
        "number": type(value) in (int, float),
        "integer": type(value) is int,
        "string": type(value) is str,
    }.get(declared, False)


def _schema_int(value: Any, path: str) -> int:
    if type(value) is not int or value < 0:
        raise _invalid_argument(path, "uses an invalid non-negative schema bound")
    return value


def _schema_number(value: Any, path: str) -> int | float:
    if type(value) not in (int, float):
        raise _invalid_argument(path, "uses an invalid numeric schema bound")
    return value


def _validate_datetime(value: str, path: str) -> None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise _invalid_argument(path, "is not an RFC 3339 date-time") from exc
    if parsed.tzinfo is None:
        raise _invalid_argument(path, "date-time must include an offset")


def _invalid_argument(path: str, reason: str) -> OperationError:
    return OperationError(
        OperationErrorCode.INVALID_ARGUMENTS,
        f"{path} {reason}",
    )


def _nonempty_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise OperationError(
            OperationErrorCode.INVALID_OPERATION_INPUT,
            f"{field} must be a non-empty string",
        )
    if re.search(r"[\x00-\x1f\x7f]", value):
        raise OperationError(
            OperationErrorCode.INVALID_OPERATION_INPUT,
            f"{field} must not contain control characters",
        )
    return value
