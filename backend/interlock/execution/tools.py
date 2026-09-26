"""Generic EXE-004 tool execution boundary.

``ToolRuntime`` consumes reducer-issued commands and returns detached
``EventCandidate`` facts for the command dispatcher to journal.  It owns only
ephemeral provider mechanics: authoritative operation and effect state remain
reducer-owned.

The provider protocol in this module intentionally points inward.  Later
adapter and fake-provider tickets implement it; this module never imports an
adapter or contains tool-name-specific behavior.
"""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from dataclasses import dataclass, field
from enum import Enum
from hashlib import sha256
import inspect
import re
from typing import Any, Awaitable, Mapping, Protocol, TypeVar

from interlock.domain.enums import (
    ActionType,
    CancellationAckScope,
    CancellationPolicy,
    CancellationState,
    EffectClassification,
    EventSource,
    OperationState,
    SafePointName,
    ToolOutcome,
)
from interlock.domain.events import ToolResultObserved
from interlock.domain.models import OperationRecord, ToolDescriptor
from interlock.execution.descriptors import ToolRegistry
from interlock.execution.idempotency import (
    CallbackStatus,
    IdempotencyError,
    canonical_json,
    strict_json_copy,
)
from interlock.execution.operations import (
    OperationError,
    OperationManager,
    _validate_arguments,
)
from interlock.runtime.commands import (
    BaseCommand,
    DispatchTool,
    PrepareOperation,
    RequestToolCancellation,
)
from interlock.runtime.dispatcher import DispatchContext
from interlock.runtime.journal import EventCandidate


_SHA256_PATTERN = re.compile(r"sha256:[0-9a-f]{64}")
_SAFE_REASON_PATTERN = re.compile(r"[A-Z][A-Z0-9_:-]{0,127}")
_T = TypeVar("_T")


class ToolRuntimeErrorCode(str, Enum):
    """Sanitized, stable failures at the EXE-004 boundary."""

    INVALID_COMMAND = "INVALID_COMMAND"
    UNKNOWN_OPERATION = "UNKNOWN_OPERATION"
    INVALID_OPERATION_SNAPSHOT = "INVALID_OPERATION_SNAPSHOT"
    UNKNOWN_DESCRIPTOR = "UNKNOWN_DESCRIPTOR"
    CAPABILITY_UNAVAILABLE = "CAPABILITY_UNAVAILABLE"
    DESCRIPTOR_CHANGED = "DESCRIPTOR_CHANGED"
    DISPATCH_NOT_AUTHORIZED = "DISPATCH_NOT_AUTHORIZED"
    INVALID_ARGUMENTS = "INVALID_ARGUMENTS"
    SPECULATION_FORBIDDEN = "SPECULATION_FORBIDDEN"
    IDEMPOTENCY_CONFLICT = "IDEMPOTENCY_CONFLICT"
    PROVIDER_PROTOCOL_ERROR = "PROVIDER_PROTOCOL_ERROR"
    CALLBACK_CONFLICT = "CALLBACK_CONFLICT"


class ToolRuntimeError(ValueError):
    """A tool command failed before a trustworthy fact could be emitted."""

    def __init__(self, code: ToolRuntimeErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code


class ProviderCancellationStatus(str, Enum):
    """Truthful normalized outcomes from provider cancellation transport."""

    REQUEST_ACCEPTED = "REQUEST_ACCEPTED"
    CANCEL_ACCEPTED = "CANCEL_ACCEPTED"
    REJECTED = "REJECTED"
    TOO_LATE = "TOO_LATE"


@dataclass(frozen=True, slots=True)
class ToolInvocation:
    """Immutable provider input derived only from trusted runtime snapshots."""

    operation_id: str
    dispatch_requested_event_id: str
    tool_name: str
    descriptor_capability_hash: str
    arguments: dict[str, Any]
    logical_action_id: str
    idempotency_key: str
    timeout_ms: int
    deadline_ms: int | None
    cancellation_token: str
    speculative: bool
    attempt: int

    def __post_init__(self) -> None:
        for name in (
            "operation_id",
            "dispatch_requested_event_id",
            "tool_name",
            "descriptor_capability_hash",
            "logical_action_id",
            "idempotency_key",
            "cancellation_token",
        ):
            _require_nonempty(getattr(self, name), name)
        if type(self.arguments) is not dict:
            raise TypeError("arguments must be a detached strict JSON object")
        if type(self.timeout_ms) is not int or self.timeout_ms < 1:
            raise ValueError("timeout_ms must be a positive integer")
        if self.deadline_ms is not None and (
            type(self.deadline_ms) is not int or self.deadline_ms < 0
        ):
            raise ValueError("deadline_ms must be a non-negative integer or None")
        if type(self.speculative) is not bool:
            raise TypeError("speculative must be a boolean")
        if type(self.attempt) is not int or self.attempt < 1:
            raise ValueError("attempt must be a positive integer")


@dataclass(frozen=True, slots=True)
class ProviderObservation:
    """One normalized provider acknowledgement or terminal observation."""

    provider_request_id: str
    callback_dedupe_key: str
    outcome: ToolOutcome
    result: dict[str, Any]
    provider_effect_id: str | None = None
    retry_category: str | None = None

    def __post_init__(self) -> None:
        _require_nonempty(self.provider_request_id, "provider_request_id")
        _require_nonempty(self.callback_dedupe_key, "callback_dedupe_key")
        if not isinstance(self.outcome, ToolOutcome):
            try:
                object.__setattr__(self, "outcome", ToolOutcome(self.outcome))
            except (TypeError, ValueError) as exc:
                raise TypeError("outcome must be a ToolOutcome") from exc
        if type(self.result) is not dict:
            raise TypeError("result must be a strict JSON object")
        if self.provider_effect_id is not None:
            _require_nonempty(self.provider_effect_id, "provider_effect_id")
        if self.retry_category is not None:
            _require_nonempty(self.retry_category, "retry_category")


@dataclass(frozen=True, slots=True)
class ProviderResponse:
    """A provider boundary acceptance with an optional immediate observation."""

    provider_request_id: str
    observation: ProviderObservation | None = None

    def __post_init__(self) -> None:
        _require_nonempty(self.provider_request_id, "provider_request_id")
        if (
            self.observation is not None
            and self.observation.provider_request_id != self.provider_request_id
        ):
            raise ValueError("observation provider_request_id must match response")


@dataclass(frozen=True, slots=True)
class ProviderCancellationRequest:
    """Detached request to cancel one established provider request."""

    operation_id: str
    provider_request_id: str
    reason: str | None = None

    def __post_init__(self) -> None:
        _require_nonempty(self.operation_id, "operation_id")
        _require_nonempty(self.provider_request_id, "provider_request_id")
        if self.reason is not None:
            _require_nonempty(self.reason, "reason")


@dataclass(frozen=True, slots=True)
class ProviderCancellationResult:
    """Typed provider statement about a cancellation request."""

    status: ProviderCancellationStatus
    reason: str

    def __post_init__(self) -> None:
        if not isinstance(self.status, ProviderCancellationStatus):
            try:
                object.__setattr__(
                    self,
                    "status",
                    ProviderCancellationStatus(self.status),
                )
            except (TypeError, ValueError) as exc:
                raise TypeError("status must be a ProviderCancellationStatus") from exc
        _require_nonempty(self.reason, "reason")


class ToolProviderTransport(Protocol):
    """Private inward protocol implemented later by adapters and fakes."""

    async def invoke(self, invocation: ToolInvocation) -> ProviderResponse:
        """Cross the provider boundary and return normalized acceptance data."""

    async def cancel(
        self,
        request: ProviderCancellationRequest,
    ) -> ProviderCancellationResult:
        """Attempt provider cancellation without asserting effect truth."""


class OperationSnapshotResolver(Protocol):
    """Injected read-only access to a detached reducer-owned operation snapshot."""

    def __call__(
        self,
        session_id: str,
        operation_id: str,
    ) -> OperationRecord | None:
        """Return the current detached operation, or ``None`` when unknown."""


class TimeoutRunner(Protocol):
    """Private injectable timeout boundary used by live and deterministic wiring."""

    async def __call__(self, awaitable: Awaitable[_T], timeout_ms: int) -> _T:
        """Await work for at most ``timeout_ms`` milliseconds."""


class ToolTransportError(Exception):
    """Sanitized transport failure with explicit provider-boundary knowledge."""

    def __init__(
        self,
        category: str,
        *,
        after_dispatch: bool,
        provider_request_id: str | None = None,
    ) -> None:
        super().__init__("tool transport failed")
        self.category = _require_nonempty(category, "category")
        if type(after_dispatch) is not bool:
            raise TypeError("after_dispatch must be a boolean")
        self.after_dispatch = after_dispatch
        if provider_request_id is not None:
            _require_nonempty(provider_request_id, "provider_request_id")
        self.provider_request_id = provider_request_id


@dataclass(slots=True)
class _InvocationState:
    operation_id: str
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    provider_ready: asyncio.Event = field(default_factory=asyncio.Event)
    provider_call_started: bool = False
    boundary_crossed: bool = False
    provider_request_id: str | None = None
    local_cancelled: bool = False
    cancel_requested: bool = False
    active_task: asyncio.Task[Any] | None = None
    terminal_local: bool = False
    callback_digests: OrderedDict[str, str] = field(default_factory=OrderedDict)


class ToolRuntime:
    """Generic provider executor with reducer and journal authority excluded."""

    def __init__(
        self,
        *,
        registry: ToolRegistry,
        operation_resolver: OperationSnapshotResolver,
        transport: ToolProviderTransport,
        timeout_runner: TimeoutRunner | None = None,
        retained_operation_limit: int = 1024,
        callback_dedupe_limit: int = 256,
    ) -> None:
        if not isinstance(registry, ToolRegistry):
            raise TypeError("registry must be a ToolRegistry")
        if not callable(operation_resolver):
            raise TypeError("operation_resolver must be callable")
        if not callable(getattr(transport, "invoke", None)) or not callable(
            getattr(transport, "cancel", None)
        ):
            raise TypeError("transport must implement invoke and cancel")
        if timeout_runner is not None and not callable(timeout_runner):
            raise TypeError("timeout_runner must be callable")
        if type(retained_operation_limit) is not int or retained_operation_limit < 1:
            raise ValueError("retained_operation_limit must be at least 1")
        if type(callback_dedupe_limit) is not int or callback_dedupe_limit < 1:
            raise ValueError("callback_dedupe_limit must be at least 1")
        self._registry = registry
        self._operation_resolver = operation_resolver
        self._transport = transport
        self._timeout_runner = timeout_runner or _asyncio_timeout
        self._retained_operation_limit = retained_operation_limit
        self._callback_dedupe_limit = callback_dedupe_limit
        self._states: OrderedDict[tuple[str, str], _InvocationState] = OrderedDict()
        self._states_lock = asyncio.Lock()

    async def handle_prepare_operation(
        self,
        command: BaseCommand,
        context: DispatchContext,
    ) -> tuple[EventCandidate, EventCandidate]:
        """Validate and deterministically prepare one reducer-created operation."""

        if not isinstance(command, PrepareOperation):
            raise ToolRuntimeError(
                ToolRuntimeErrorCode.INVALID_COMMAND,
                "expected PrepareOperation",
            )
        operation = self._resolve(command.session_id, command.operation_id)
        if operation.state != OperationState.CREATED:
            raise ToolRuntimeError(
                ToolRuntimeErrorCode.INVALID_OPERATION_SNAPSHOT,
                "operation is not eligible for preparation",
            )
        descriptor, _ = self._trusted_descriptor(operation)
        self._snapshot_descriptor_gates(operation, descriptor)
        arguments = self._validated_arguments(operation, descriptor)
        prepared_hash = _digest(arguments)
        started = self._candidate(
            command,
            context,
            event_type="OperationPreparationStarted",
            payload={"operation_id": operation.operation_id},
            dedupe_key=f"tool-runtime:prepare-started:{operation.operation_id}",
            source=EventSource.SYSTEM,
        )
        prepared = self._candidate(
            command,
            context,
            event_type="OperationPrepared",
            payload={
                "operation_id": operation.operation_id,
                "prepared_args_hash": prepared_hash,
                "safe_point": SafePointName.BEFORE_PROVIDER_DISPATCH.value,
            },
            dedupe_key=f"tool-runtime:prepared:{operation.operation_id}:{prepared_hash}",
            source=EventSource.SYSTEM,
        )
        return started, prepared

    async def handle_dispatch_tool(
        self,
        command: BaseCommand,
        context: DispatchContext,
    ) -> tuple[EventCandidate, ...]:
        """Execute only a reducer-authorized ``DispatchTool`` command."""

        if not isinstance(command, DispatchTool):
            raise ToolRuntimeError(
                ToolRuntimeErrorCode.INVALID_COMMAND,
                "expected DispatchTool",
            )
        operation = self._resolve(command.session_id, command.operation_id)
        descriptor, capability_hash = self._dispatch_gates(operation)
        arguments = self._validated_arguments(operation, descriptor)
        state = await self._state(command.session_id, operation.operation_id)
        execution_identity = _execution_identity(operation, arguments)

        async with state.lock:
            if state.local_cancelled:
                return ()
            if state.provider_call_started:
                raise ToolRuntimeError(
                    ToolRuntimeErrorCode.DISPATCH_NOT_AUTHORIZED,
                    "operation already has a provider invocation",
                )
            state.provider_call_started = True
            state.active_task = asyncio.current_task()
            state.terminal_local = False

        candidates: list[EventCandidate] = []
        deferred_failure_candidate: EventCandidate | None = None
        established_provider_id: str | None = state.provider_request_id
        max_attempts = descriptor.retry_policy.max_attempts
        if max_attempts < 1:
            await self._finish_attempt(state)
            raise ToolRuntimeError(
                ToolRuntimeErrorCode.PROVIDER_PROTOCOL_ERROR,
                "descriptor permits no provider attempts",
            )

        for attempt in range(1, max_attempts + 1):
            if attempt > 1:
                # Let already queued cancellation work run before resolving again.
                await asyncio.sleep(0)
            # No await may separate this final trusted capability check from
            # construction of the provider call below.  Retries recheck too.
            try:
                operation = self._resolve(command.session_id, command.operation_id)
                if _execution_identity(operation, operation.args) != execution_identity:
                    raise ToolRuntimeError(
                        ToolRuntimeErrorCode.IDEMPOTENCY_CONFLICT,
                        "immutable execution identity changed during invocation",
                    )
                cancellation_interrupts = (
                    operation.cancellation_state == CancellationState.REQUESTED
                    and operation.cancellation_policy != CancellationPolicy.NONCANCELLABLE
                )
                if (
                    operation.state != OperationState.DISPATCHED
                    or cancellation_interrupts
                    or state.cancel_requested
                ):
                    async with state.lock:
                        state.cancel_requested |= cancellation_interrupts
                        if state.cancel_requested and not state.boundary_crossed:
                            state.local_cancelled = (
                                state.provider_request_id is None
                                and operation.provider_request_id is None
                            )
                        await self._finish_attempt_locked(state)
                    return tuple(candidates)
                descriptor, capability_hash = self._dispatch_gates(operation)
                arguments = self._validated_arguments(operation, descriptor)
                invocation = ToolInvocation(
                    operation_id=operation.operation_id,
                    dispatch_requested_event_id=(
                        operation.dispatch_requested_event_id or ""
                    ),
                    tool_name=operation.tool_name,
                    descriptor_capability_hash=capability_hash,
                    arguments=strict_json_copy(arguments, field="arguments"),
                    logical_action_id=operation.logical_action_id,
                    idempotency_key=operation.idempotency_key,
                    timeout_ms=descriptor.timeout_ms,
                    deadline_ms=(
                        None
                        if context.logical_time is None
                        else context.logical_time + descriptor.timeout_ms
                    ),
                    cancellation_token=_digest(
                        {
                            "operation_id": operation.operation_id,
                            "dispatch_requested_event_id": (
                                operation.dispatch_requested_event_id
                            ),
                        }
                    ),
                    speculative=operation.speculative,
                    attempt=attempt,
                )
            except Exception:
                await self._finish_attempt(state)
                raise
            try:
                response = await self._timeout_runner(
                    self._transport.invoke(invocation),
                    descriptor.timeout_ms,
                )
                response = _require_response(response)
            except ToolTransportError as error:
                await self._record_transport_error(state, error)
                if self._may_retry_transport_error(
                    operation,
                    descriptor,
                    error,
                    attempt,
                ):
                    continue
                await self._finish_attempt(state)
                if error.after_dispatch:
                    return (
                        self._timeout_candidate(
                            command,
                            context,
                            operation.operation_id,
                            after_dispatch=True,
                            identity=f"attempt-{attempt}:{error.category}",
                        ),
                    )
                if error.category == "TIMEOUT":
                    return (
                        self._timeout_candidate(
                            command,
                            context,
                            operation.operation_id,
                            after_dispatch=False,
                            identity=f"attempt-{attempt}:timeout",
                        ),
                    )
                if deferred_failure_candidate is not None:
                    candidates.append(deferred_failure_candidate)
                    return tuple(candidates)
                raise ToolRuntimeError(
                    ToolRuntimeErrorCode.PROVIDER_PROTOCOL_ERROR,
                    "provider failed before dispatch",
                ) from error
            except asyncio.TimeoutError:
                async with state.lock:
                    state.boundary_crossed = True
                    state.provider_ready.set()
                await self._finish_attempt(state)
                return (
                    self._timeout_candidate(
                        command,
                        context,
                        operation.operation_id,
                        after_dispatch=True,
                        identity=f"attempt-{attempt}:timeout",
                    ),
                )
            except asyncio.CancelledError:
                async with state.lock:
                    crossed = state.provider_call_started
                    state.boundary_crossed |= crossed
                    state.provider_ready.set()
                await self._finish_attempt(state)
                if crossed:
                    return (
                        self._timeout_candidate(
                            command,
                            context,
                            operation.operation_id,
                            after_dispatch=True,
                            identity=f"attempt-{attempt}:cancelled-ambiguous",
                        ),
                    )
                raise
            except Exception:
                async with state.lock:
                    state.boundary_crossed = True
                    state.provider_ready.set()
                await self._finish_attempt(state)
                return (
                    self._timeout_candidate(
                        command,
                        context,
                        operation.operation_id,
                        after_dispatch=True,
                        identity=f"attempt-{attempt}:protocol-error",
                    ),
                )

            provider_id = response.provider_request_id
            async with state.lock:
                state.boundary_crossed = True
                if any(
                    established is not None and established != provider_id
                    for established in (
                        established_provider_id,
                        state.provider_request_id,
                        operation.provider_request_id,
                    )
                ):
                    state.provider_ready.set()
                    await self._finish_attempt_locked(state)
                    return (
                        self._timeout_candidate(
                            command,
                            context,
                            operation.operation_id,
                            after_dispatch=True,
                            identity=f"attempt-{attempt}:provider-id-conflict",
                        ),
                    )
                established_provider_id = provider_id
                state.provider_request_id = provider_id
                state.provider_ready.set()

            if not any(c.event_type == "ToolDispatchAccepted" for c in candidates):
                candidates.append(
                    self._candidate(
                        command,
                        context,
                        event_type="ToolDispatchAccepted",
                        payload={
                            "operation_id": operation.operation_id,
                            "provider_request_id": provider_id,
                        },
                        dedupe_key=(
                            "tool-runtime:dispatch-accepted:"
                            f"{operation.operation_id}:{provider_id}"
                        ),
                    )
                )

            if response.observation is None:
                await self._finish_attempt(state)
                return tuple(candidates)

            result_candidate = await self._normalize_observation(
                command=command,
                context=context,
                operation=operation,
                descriptor=descriptor,
                observation=response.observation,
                state=state,
            )
            if (
                response.observation.outcome == ToolOutcome.FAILED
                and result_candidate is not None
                and result_candidate.event_type == "ToolResultObserved"
                and response.observation.retry_category is not None
                and self._may_retry_observation(
                    operation,
                    descriptor,
                    response.observation.retry_category,
                    attempt,
                )
            ):
                deferred_failure_candidate = result_candidate
                continue
            if result_candidate is not None:
                candidates.append(result_candidate)
            await self._finish_attempt(state)
            return tuple(candidates)

        await self._finish_attempt(state)
        return tuple(candidates)

    async def handle_request_tool_cancellation(
        self,
        command: BaseCommand,
        context: DispatchContext,
    ) -> EventCandidate | None:
        """Attempt cancellation and report only an actually observed outcome."""

        if not isinstance(command, RequestToolCancellation):
            raise ToolRuntimeError(
                ToolRuntimeErrorCode.INVALID_COMMAND,
                "expected RequestToolCancellation",
            )
        operation = self._resolve(command.session_id, command.operation_id)
        descriptor, _ = self._trusted_descriptor(operation)
        self._snapshot_descriptor_gates(operation, descriptor)
        if operation.cancellation_state != CancellationState.REQUESTED:
            raise ToolRuntimeError(
                ToolRuntimeErrorCode.DISPATCH_NOT_AUTHORIZED,
                "cancellation command has no reducer-accepted request",
            )

        if descriptor.cancellation_policy == CancellationPolicy.NONCANCELLABLE:
            return self._cancellation_candidate(
                command,
                context,
                event_type="CancellationRejected",
                payload={
                    "operation_id": operation.operation_id,
                    "reason": "NONCANCELLABLE",
                },
                identity="noncancellable",
            )

        state = await self._existing_state(
            command.session_id,
            operation.operation_id,
        )
        provider_id = operation.provider_request_id
        if state is None:
            if provider_id is not None:
                return await self._cancel_provider_request(
                    command,
                    context,
                    operation,
                    descriptor,
                    provider_id,
                )
            if not _authoritative_pre_dispatch(operation):
                # Ephemeral history may have been lost after provider dispatch.
                # Absence of local state proves nothing, so preserve REQUESTED.
                return None
            state = await self._state(command.session_id, operation.operation_id)

        async with state.lock:
            state.cancel_requested = True
            provider_id = operation.provider_request_id or state.provider_request_id
            if provider_id is None and (
                state.local_cancelled or (
                    not state.provider_call_started
                    and _authoritative_pre_dispatch(operation)
                )
            ):
                state.local_cancelled = True
                state.terminal_local = True
                state.provider_ready.set()
                return self._cancellation_candidate(
                    command,
                    context,
                    event_type="CancellationAcknowledged",
                    payload={
                        "operation_id": operation.operation_id,
                        "scope": CancellationAckScope.LOCAL_TASK.value,
                    },
                    identity="local-task",
                )

        if provider_id is None:
            await state.provider_ready.wait()
            async with state.lock:
                provider_id = state.provider_request_id or operation.provider_request_id
                if provider_id is None and state.local_cancelled:
                    return self._cancellation_candidate(
                        command,
                        context,
                        event_type="CancellationAcknowledged",
                        payload={
                            "operation_id": operation.operation_id,
                            "scope": CancellationAckScope.LOCAL_TASK.value,
                        },
                        identity="local-task",
                    )
        if provider_id is None:
            # The provider has not supplied enough evidence to claim rejection,
            # lateness, or acceptance.  Preserve REQUESTED without a new fact.
            return None

        return await self._cancel_provider_request(
            command,
            context,
            operation,
            descriptor,
            provider_id,
        )

    async def _cancel_provider_request(
        self,
        command: RequestToolCancellation,
        context: DispatchContext,
        operation: OperationRecord,
        descriptor: ToolDescriptor,
        provider_id: str,
    ) -> EventCandidate | None:
        """Cancel one established provider request without inferring its effect."""

        request = ProviderCancellationRequest(
            operation_id=operation.operation_id,
            provider_request_id=provider_id,
            reason=command.reason,
        )
        try:
            result = await self._timeout_runner(
                self._transport.cancel(request),
                descriptor.timeout_ms,
            )
        except Exception:
            # An unavailable cancellation outcome proves neither rejection nor
            # lateness.  Leave the reducer's REQUESTED fact intact.
            return None
        if not isinstance(result, ProviderCancellationResult):
            return None
        if result.status == ProviderCancellationStatus.REQUEST_ACCEPTED:
            return self._cancellation_candidate(
                command,
                context,
                event_type="CancellationAcknowledged",
                payload={
                    "operation_id": operation.operation_id,
                    "scope": CancellationAckScope.PROVIDER_REQUEST_ACCEPTED.value,
                },
                identity=f"provider-request-accepted:{provider_id}",
            )
        if result.status == ProviderCancellationStatus.CANCEL_ACCEPTED:
            return self._cancellation_candidate(
                command,
                context,
                event_type="CancellationAcknowledged",
                payload={
                    "operation_id": operation.operation_id,
                    "scope": CancellationAckScope.PROVIDER_CANCEL_ACCEPTED.value,
                },
                identity=f"provider-cancel-accepted:{provider_id}",
            )
        if result.status == ProviderCancellationStatus.REJECTED:
            return self._cancellation_candidate(
                command,
                context,
                event_type="CancellationRejected",
                payload={
                    "operation_id": operation.operation_id,
                    "reason": _sanitized_reason(
                        result.reason,
                        fallback="PROVIDER_CANCELLATION_REJECTED",
                    ),
                },
                identity=f"provider-rejected:{provider_id}",
            )
        return self._cancellation_candidate(
            command,
            context,
            event_type="CancellationTooLate",
            payload={
                "operation_id": operation.operation_id,
                "reason": _sanitized_reason(
                    result.reason,
                    fallback="PROVIDER_CANCELLATION_TOO_LATE",
                ),
            },
            identity=f"provider-too-late:{provider_id}",
        )

    async def observe_callback(
        self,
        *,
        session_id: str,
        operation_id: str,
        observation: ProviderObservation,
        context: DispatchContext | None = None,
    ) -> EventCandidate | None:
        """Normalize a late/asynchronous callback without mutating authority."""

        _require_nonempty(session_id, "session_id")
        _require_nonempty(operation_id, "operation_id")
        if not isinstance(observation, ProviderObservation):
            raise ToolRuntimeError(
                ToolRuntimeErrorCode.PROVIDER_PROTOCOL_ERROR,
                "callback must be a ProviderObservation",
            )
        operation = self._resolve(session_id, operation_id)
        callback_command = DispatchTool(
            session_id=session_id,
            operation_id=operation_id,
        )
        try:
            descriptor, _ = self._trusted_descriptor(operation)
            self._snapshot_descriptor_gates(operation, descriptor)
        except ToolRuntimeError:
            # A late observation cannot be interpreted under a changed or
            # unavailable authorized capability; retain post-dispatch uncertainty.
            return self._timeout_candidate(
                callback_command,
                context or DispatchContext(),
                operation_id,
                after_dispatch=True,
                identity=f"callback-capability:{_safe_identity(observation.callback_dedupe_key)}",
            )
        state = await self._state(session_id, operation_id)
        return await self._normalize_observation(
            command=callback_command,
            context=context or DispatchContext(),
            operation=operation,
            descriptor=descriptor,
            observation=observation,
            state=state,
        )

    def _resolve(self, session_id: str, operation_id: str) -> OperationRecord:
        try:
            resolved = self._operation_resolver(session_id, operation_id)
        except Exception as exc:
            raise ToolRuntimeError(
                ToolRuntimeErrorCode.UNKNOWN_OPERATION,
                "operation snapshot could not be resolved",
            ) from exc
        if inspect.isawaitable(resolved):
            raise ToolRuntimeError(
                ToolRuntimeErrorCode.INVALID_OPERATION_SNAPSHOT,
                "operation resolver must be synchronous and read-only",
            )
        if resolved is None:
            raise ToolRuntimeError(
                ToolRuntimeErrorCode.UNKNOWN_OPERATION,
                "operation is unknown",
            )
        if not isinstance(resolved, OperationRecord):
            raise ToolRuntimeError(
                ToolRuntimeErrorCode.INVALID_OPERATION_SNAPSHOT,
                "resolver returned an invalid operation snapshot",
            )
        try:
            operation = OperationRecord.model_validate(
                strict_json_copy(
                    resolved.model_dump(mode="json"),
                    field="operation",
                )
            )
        except (IdempotencyError, ValueError, TypeError) as exc:
            raise ToolRuntimeError(
                ToolRuntimeErrorCode.INVALID_OPERATION_SNAPSHOT,
                "operation snapshot is invalid",
            ) from exc
        if operation.operation_id != operation_id:
            raise ToolRuntimeError(
                ToolRuntimeErrorCode.INVALID_OPERATION_SNAPSHOT,
                "resolved operation does not match command",
            )
        return operation

    def _trusted_descriptor(
        self,
        operation: OperationRecord,
    ) -> tuple[ToolDescriptor, str]:
        try:
            descriptor = self._registry.get(operation.tool_name)
            capability_hash = self._registry.capability_hash(operation.tool_name)
        except (KeyError, ValueError) as exc:
            raise ToolRuntimeError(
                ToolRuntimeErrorCode.UNKNOWN_DESCRIPTOR,
                "tool descriptor is not registered",
            ) from exc
        if _SHA256_PATTERN.fullmatch(capability_hash) is None:
            raise ToolRuntimeError(
                ToolRuntimeErrorCode.CAPABILITY_UNAVAILABLE,
                "current capability identity is unavailable",
            )
        return descriptor, capability_hash

    def _dispatch_gates(
        self,
        operation: OperationRecord,
    ) -> tuple[ToolDescriptor, str]:
        descriptor, current_hash = self._trusted_descriptor(operation)
        self._snapshot_descriptor_gates(operation, descriptor)
        stored_hash = operation.descriptor_capability_hash
        assert isinstance(stored_hash, str)
        assert stored_hash == current_hash
        if operation.state != OperationState.DISPATCHED:
            raise ToolRuntimeError(
                ToolRuntimeErrorCode.DISPATCH_NOT_AUTHORIZED,
                "operation is not reducer-authorized for dispatch",
            )
        if operation.dispatch_requested_event_id is None:
            raise ToolRuntimeError(
                ToolRuntimeErrorCode.DISPATCH_NOT_AUTHORIZED,
                "operation has no reducer-minted dispatch token",
            )
        if operation.speculative and not (
            descriptor.action_type == ActionType.READ_ONLY
            and descriptor.effect_classification == EffectClassification.NONE
        ):
            raise ToolRuntimeError(
                ToolRuntimeErrorCode.SPECULATION_FORBIDDEN,
                "speculation requires READ_ONLY/NONE capability",
            )
        return descriptor, current_hash

    def _snapshot_descriptor_gates(
        self,
        operation: OperationRecord,
        descriptor: ToolDescriptor,
    ) -> None:
        """Validate creation-time capability and safety metadata."""

        current_hash = self._registry.capability_hash(operation.tool_name)
        stored_hash = operation.descriptor_capability_hash
        if not isinstance(stored_hash, str) or _SHA256_PATTERN.fullmatch(stored_hash) is None:
            raise ToolRuntimeError(
                ToolRuntimeErrorCode.CAPABILITY_UNAVAILABLE,
                "stored capability identity is unavailable",
            )
        if stored_hash != current_hash:
            raise ToolRuntimeError(
                ToolRuntimeErrorCode.DESCRIPTOR_CHANGED,
                "tool descriptor changed after authorization",
            )
        if (
            operation.action_type != descriptor.action_type
            or operation.cancellation_policy != descriptor.cancellation_policy
        ):
            raise ToolRuntimeError(
                ToolRuntimeErrorCode.INVALID_OPERATION_SNAPSHOT,
                "operation safety metadata differs from trusted descriptor",
            )

    def _validated_arguments(
        self,
        operation: OperationRecord,
        descriptor: ToolDescriptor,
    ) -> dict[str, Any]:
        try:
            arguments = strict_json_copy(operation.args, field="arguments")
            if type(arguments) is not dict:
                raise TypeError("arguments must be an object")
            _validate_arguments(arguments, descriptor.argument_schema)
        except (IdempotencyError, OperationError, TypeError, ValueError) as exc:
            raise ToolRuntimeError(
                ToolRuntimeErrorCode.INVALID_ARGUMENTS,
                "operation arguments do not satisfy the trusted descriptor",
            ) from exc
        if descriptor.idempotency.supported:
            key_field = descriptor.idempotency.key_field
            if not key_field or arguments.get(key_field) != operation.idempotency_key:
                raise ToolRuntimeError(
                    ToolRuntimeErrorCode.IDEMPOTENCY_CONFLICT,
                    "provider idempotency field conflicts with operation identity",
                )
        return arguments

    async def _normalize_observation(
        self,
        *,
        command: BaseCommand,
        context: DispatchContext,
        operation: OperationRecord,
        descriptor: ToolDescriptor,
        observation: ProviderObservation,
        state: _InvocationState,
    ) -> EventCandidate | None:
        try:
            result = strict_json_copy(observation.result, field="provider_result")
            if type(result) is not dict:
                raise TypeError("provider result must be an object")
            nested_request_id = result.get("provider_request_id")
            if (
                nested_request_id is not None
                and nested_request_id != observation.provider_request_id
            ):
                raise ToolRuntimeError(
                    ToolRuntimeErrorCode.PROVIDER_PROTOCOL_ERROR,
                    "nested provider request identity conflicts with observation",
                )
            _validate_arguments(result, descriptor.result_schema)
            _validate_confirmation_semantics(observation.outcome, result, descriptor)
            payload = ToolResultObserved(
                operation_id=operation.operation_id,
                provider_request_id=observation.provider_request_id,
                outcome=observation.outcome,
                result=result,
                provider_effect_id=observation.provider_effect_id,
            )
            async with state.lock:
                # Correlation, classification and reservation share one atomic
                # per-operation snapshot. General result validation stays above.
                expected_provider_id = (
                    state.provider_request_id or operation.provider_request_id
                )
                if expected_provider_id is None and (
                    not operation.dispatch_requested_event_id
                    or operation.state in (
                        OperationState.CREATED, OperationState.PREPARING,
                        OperationState.READY,
                    )
                ):
                    raise ToolRuntimeError(
                        ToolRuntimeErrorCode.PROVIDER_PROTOCOL_ERROR,
                        "first callback has no accepted dispatch authority",
                    )
                if any(
                    established is not None
                    and observation.provider_request_id != established
                    for established in (
                        state.provider_request_id, operation.provider_request_id
                    )
                ):
                    raise ToolRuntimeError(
                        ToolRuntimeErrorCode.PROVIDER_PROTOCOL_ERROR,
                        "provider request identity conflicts with invocation",
                    )
                decision = OperationManager.classify_result(
                    operation,
                    payload,
                    callback_dedupe_key=observation.callback_dedupe_key,
                    known_observation_digests=dict(state.callback_digests),
                )
                if decision.status == CallbackStatus.NEW:
                    # Bind only after classification succeeds, so malformed or
                    # conflicting callback identities cannot reserve correlation.
                    if state.provider_request_id is None:
                        state.provider_request_id = observation.provider_request_id
                    state.callback_digests[decision.callback_dedupe_key] = (
                        decision.observation_digest
                    )
                    state.callback_digests.move_to_end(decision.callback_dedupe_key)
                    while len(state.callback_digests) > self._callback_dedupe_limit:
                        state.callback_digests.popitem(last=False)
                    state.boundary_crossed = True
                    state.provider_ready.set()
        except (IdempotencyError, OperationError, ToolRuntimeError, TypeError, ValueError):
            return self._timeout_candidate(
                command,
                context,
                operation.operation_id,
                after_dispatch=True,
                identity=f"callback-protocol:{_safe_identity(observation.callback_dedupe_key)}",
            )

        if decision.status == CallbackStatus.DUPLICATE:
            return None
        if decision.status == CallbackStatus.CONFLICT:
            return self._timeout_candidate(
                command,
                context,
                operation.operation_id,
                after_dispatch=True,
                identity=f"callback-conflict:{_safe_identity(observation.callback_dedupe_key)}",
            )
        return self._candidate(
            command,
            context,
            event_type="ToolResultObserved",
            payload=payload.model_dump(mode="json"),
            dedupe_key=(
                "tool-runtime:result:"
                f"{operation.operation_id}:{_safe_identity(observation.callback_dedupe_key)}"
            ),
        )

    async def _state(self, session_id: str, operation_id: str) -> _InvocationState:
        key = (session_id, operation_id)
        async with self._states_lock:
            state = self._states.get(key)
            if state is None:
                while len(self._states) >= self._retained_operation_limit:
                    removable = next(
                        (
                            candidate
                            for candidate, value in self._states.items()
                            if value.terminal_local and value.active_task is None
                        ),
                        None,
                    )
                    if removable is None:
                        raise ToolRuntimeError(
                            ToolRuntimeErrorCode.PROVIDER_PROTOCOL_ERROR,
                            "runtime correlation capacity is exhausted",
                        )
                    self._states.pop(removable, None)
                state = _InvocationState(operation_id=operation_id)
                self._states[key] = state
            else:
                self._states.move_to_end(key)
            return state

    async def _existing_state(
        self,
        session_id: str,
        operation_id: str,
    ) -> _InvocationState | None:
        """Return retained local history without manufacturing proof."""

        key = (session_id, operation_id)
        async with self._states_lock:
            state = self._states.get(key)
            if state is not None:
                self._states.move_to_end(key)
            return state

    async def _record_transport_error(
        self,
        state: _InvocationState,
        error: ToolTransportError,
    ) -> None:
        async with state.lock:
            state.boundary_crossed = state.boundary_crossed or error.after_dispatch
            if error.provider_request_id is not None:
                if (
                    state.provider_request_id is not None
                    and state.provider_request_id != error.provider_request_id
                ):
                    state.boundary_crossed = True
                else:
                    state.provider_request_id = error.provider_request_id
            if state.boundary_crossed or state.provider_request_id is not None:
                state.provider_ready.set()

    async def _finish_attempt(self, state: _InvocationState) -> None:
        async with state.lock:
            await self._finish_attempt_locked(state)

    async def _finish_attempt_locked(self, state: _InvocationState) -> None:
        state.active_task = None
        state.terminal_local = True
        state.provider_ready.set()

    @staticmethod
    def _may_retry_transport_error(
        operation: OperationRecord,
        descriptor: ToolDescriptor,
        error: ToolTransportError,
        attempt: int,
    ) -> bool:
        if attempt >= descriptor.retry_policy.max_attempts:
            return False
        if error.category not in descriptor.retry_policy.retry_on:
            return False
        if operation.action_type == ActionType.READ_ONLY:
            return True
        return (
            descriptor.idempotency.supported
            and descriptor.idempotency.scope == "PROVIDER"
            and not error.after_dispatch
        )

    @staticmethod
    def _may_retry_observation(
        operation: OperationRecord,
        descriptor: ToolDescriptor,
        category: str,
        attempt: int,
    ) -> bool:
        if attempt >= descriptor.retry_policy.max_attempts:
            return False
        if category not in descriptor.retry_policy.retry_on:
            return False
        return (
            operation.action_type == ActionType.READ_ONLY
            or (
                descriptor.idempotency.supported
                and descriptor.idempotency.scope == "PROVIDER"
            )
        )

    def _timeout_candidate(
        self,
        command: BaseCommand,
        context: DispatchContext,
        operation_id: str,
        *,
        after_dispatch: bool,
        identity: str,
    ) -> EventCandidate:
        return self._candidate(
            command,
            context,
            event_type="ToolTimedOut",
            payload={
                "operation_id": operation_id,
                "after_dispatch": after_dispatch,
            },
            dedupe_key=(
                f"tool-runtime:timeout:{operation_id}:{int(after_dispatch)}:"
                f"{_safe_identity(identity)}"
            ),
        )

    def _cancellation_candidate(
        self,
        command: BaseCommand,
        context: DispatchContext,
        *,
        event_type: str,
        payload: dict[str, Any],
        identity: str,
    ) -> EventCandidate:
        return self._candidate(
            command,
            context,
            event_type=event_type,
            payload=payload,
            dedupe_key=(
                f"tool-runtime:cancellation:{payload['operation_id']}:"
                f"{_safe_identity(identity)}"
            ),
        )

    @staticmethod
    def _candidate(
        command: BaseCommand,
        context: DispatchContext,
        *,
        event_type: str,
        payload: Mapping[str, Any],
        dedupe_key: str,
        source: EventSource = EventSource.TOOL,
    ) -> EventCandidate:
        return EventCandidate(
            event_type=event_type,
            session_id=command.session_id,
            source=source,
            payload=strict_json_copy(dict(payload), field="event_payload"),
            logical_time=context.logical_time,
            correlation_id=context.correlation_id,
            causation_id=context.origin_event_id,
            dedupe_key=dedupe_key,
        )


async def _asyncio_timeout(awaitable: Awaitable[_T], timeout_ms: int) -> _T:
    return await asyncio.wait_for(awaitable, timeout=timeout_ms / 1000.0)


def _require_response(value: Any) -> ProviderResponse:
    if not isinstance(value, ProviderResponse):
        raise TypeError("transport returned an invalid response")
    return value


def _validate_confirmation_semantics(
    outcome: ToolOutcome,
    result: Mapping[str, Any],
    descriptor: ToolDescriptor,
) -> None:
    semantics = descriptor.confirmation_semantics
    expected: str | None = None
    if outcome == ToolOutcome.ACKNOWLEDGED:
        expected = semantics.acknowledgement
    elif outcome == ToolOutcome.SUCCEEDED:
        expected = semantics.commit
        if expected is None and not (
            descriptor.action_type == ActionType.READ_ONLY
            and descriptor.effect_classification == EffectClassification.NONE
        ):
            raise ToolRuntimeError(
                ToolRuntimeErrorCode.PROVIDER_PROTOCOL_ERROR,
                "consequential success requires a commit confirmation semantic",
            )
    elif outcome == ToolOutcome.UNKNOWN:
        expected = semantics.unknown
    elif (
        outcome == ToolOutcome.FAILED
        and any(
            token is not None and result.get("status") == token
            for token in (
                semantics.acknowledgement, semantics.commit, semantics.unknown
            )
        )
    ):
        raise ToolRuntimeError(
            ToolRuntimeErrorCode.PROVIDER_PROTOCOL_ERROR,
            "failed outcome contradicts non-failure confirmation semantics",
        )
    if expected is not None and result.get("status") != expected:
        raise ToolRuntimeError(
            ToolRuntimeErrorCode.PROVIDER_PROTOCOL_ERROR,
            "provider result conflicts with confirmation semantics",
        )


def _execution_identity(operation: OperationRecord, arguments: Mapping[str, Any]) -> str:
    """Pin the execution identity independently of mutable lifecycle state."""

    return canonical_json({
        "operation_id": operation.operation_id,
        "tool_name": operation.tool_name,
        "logical_action_id": operation.logical_action_id,
        "idempotency_key": operation.idempotency_key,
        "arguments": arguments,
        "dispatch_requested_event_id": operation.dispatch_requested_event_id,
        "descriptor_capability_hash": operation.descriptor_capability_hash,
    })


def _digest(value: Any) -> str:
    return f"sha256:{sha256(canonical_json(value).encode('utf-8')).hexdigest()}"


def _require_nonempty(value: Any, field_name: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise ValueError(f"{field_name} must be a non-empty safe string")
    return value


def _safe_identity(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def _authoritative_pre_dispatch(operation: OperationRecord) -> bool:
    """Whether reducer state proves provider dispatch was never authorized."""

    return (
        operation.state
        in (OperationState.CREATED, OperationState.PREPARING, OperationState.READY)
        and operation.dispatch_requested_event_id is None
        and operation.provider_request_id is None
    )


def _sanitized_reason(value: str, *, fallback: str) -> str:
    """Allow stable reason codes only; never journal arbitrary provider text."""

    if _SAFE_REASON_PATTERN.fullmatch(value) is None:
        return fallback
    return value
