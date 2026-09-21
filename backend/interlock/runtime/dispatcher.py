"""Asynchronous command routing and replay suppression for INTERLOCK.

The dispatcher is deliberately infrastructure-only.  It snapshots reducer
commands, routes them to explicitly registered async handlers, and appends
returned facts through :class:`EventJournal`.  It never receives or mutates a
``SessionState`` and never assigns event sequence numbers.
"""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass
from enum import Enum
from typing import Awaitable, Callable, Iterable, Sequence, TypeAlias

from interlock.domain.enums import EventSource, RuntimeMode
from interlock.domain.models import EventEnvelope
from interlock.runtime.commands import (
    BaseCommand,
    BuildReconciliationPlan,
    CancelSpeech,
    DispatchTool,
    EmitOutput,
    InterpretInput,
    PrepareBranch,
    PrepareOperation,
    PublishProjection,
    QueueOutput,
    RecordProtocolViolation,
    RequestClarification,
    RequestToolCancellation,
    ValidateSpeech,
    VerifyOutcome,
)
from interlock.runtime.journal import EventCandidate, EventJournal, JournalError


class DispatchStatus(str, Enum):
    """Private runtime outcome of a command submission."""

    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    SUPPRESSED = "SUPPRESSED"
    CANCELLED = "CANCELLED"


class DispatchErrorCode(str, Enum):
    """Stable fail-closed dispatcher error categories."""

    UNCONFIGURED_HANDLER = "UNCONFIGURED_HANDLER"
    HANDLER_FAILED = "HANDLER_FAILED"
    INVALID_HANDLER_RESULT = "INVALID_HANDLER_RESULT"
    SESSION_MISMATCH = "SESSION_MISMATCH"
    CAUSATION_MISMATCH = "CAUSATION_MISMATCH"
    JOURNAL_REJECTED = "JOURNAL_REJECTED"
    CANCELLED = "CANCELLED"
    INTERNAL_ERROR = "INTERNAL_ERROR"


@dataclass(frozen=True, slots=True)
class DispatchContext:
    """Immutable lineage and mode metadata for one reducer command batch."""

    origin_event_id: str | None = None
    origin_session_id: str | None = None
    correlation_id: str | None = None
    logical_time: int | None = None
    runtime_mode: RuntimeMode | None = None

    def __post_init__(self) -> None:
        for field_name, value in (
            ("origin_event_id", self.origin_event_id),
            ("origin_session_id", self.origin_session_id),
            ("correlation_id", self.correlation_id),
        ):
            if value is not None and (not isinstance(value, str) or not value):
                raise ValueError(f"{field_name} must be a non-empty string")
        if self.logical_time is not None and (
            isinstance(self.logical_time, bool)
            or not isinstance(self.logical_time, int)
            or self.logical_time < 0
        ):
            raise ValueError("logical_time must be a non-negative integer")
        if self.runtime_mode is not None and not isinstance(
            self.runtime_mode, RuntimeMode
        ):
            raise TypeError("runtime_mode must be a RuntimeMode")

    @classmethod
    def from_envelope(
        cls,
        envelope: EventEnvelope,
        *,
        runtime_mode: RuntimeMode | None = None,
    ) -> "DispatchContext":
        """Create context from the accepted fact that caused the commands."""

        return cls(
            origin_event_id=envelope.event_id,
            origin_session_id=envelope.session_id,
            correlation_id=envelope.correlation_id,
            logical_time=envelope.logical_time,
            runtime_mode=runtime_mode,
        )


@dataclass(frozen=True, slots=True)
class DispatchError:
    """Sanitized dispatcher failure safe for orchestration and diagnostics."""

    code: DispatchErrorCode
    session_id: str
    command_type: str
    correlation_id: str | None
    message: str


@dataclass(frozen=True, slots=True)
class DispatchResult:
    """Terminal outcome of one submitted command."""

    status: DispatchStatus
    session_id: str
    command_type: str
    correlation_id: str | None
    accepted_events: tuple[EventEnvelope, ...] = ()
    error: DispatchError | None = None


HandlerResult: TypeAlias = EventCandidate | Sequence[EventCandidate] | None
CommandHandler: TypeAlias = Callable[
    [BaseCommand, DispatchContext], Awaitable[HandlerResult]
]


@dataclass(frozen=True, slots=True)
class DispatchSubmission:
    """Awaitable handle for work accepted by ``CommandDispatcher.submit``."""

    session_id: str
    command_type: str
    correlation_id: str | None
    _future: asyncio.Future[DispatchResult]

    async def wait(self) -> DispatchResult:
        """Wait for the handler and all resulting journal appends."""

        try:
            return await self._future
        except asyncio.CancelledError:
            return _cancelled_result(
                self.session_id,
                self.command_type,
                self.correlation_id,
            )

    def cancel(self) -> bool:
        """Request cancellation without manufacturing a completion fact."""

        return self._future.cancel()

    @property
    def done(self) -> bool:
        return self._future.done()


_COMMAND_TYPES: tuple[type[BaseCommand], ...] = (
    InterpretInput,
    PrepareBranch,
    PrepareOperation,
    DispatchTool,
    RequestToolCancellation,
    VerifyOutcome,
    BuildReconciliationPlan,
    ValidateSpeech,
    QueueOutput,
    EmitOutput,
    PublishProjection,
    RecordProtocolViolation,
    RequestClarification,
    CancelSpeech,
)
_KNOWN_COMMAND_NAMES = frozenset(
    command_type.model_fields["command_type"].default
    for command_type in _COMMAND_TYPES
)


class CommandDispatcher:
    """Route immutable command snapshots to concurrent async workers.

    Submissions are scheduled in caller order and execute independently.  Every
    returned fact is validated and appended through the journal, whose
    per-session lock is the sole sequence allocator.  Replay/disabled mode is
    checked before handler lookup or task creation.
    """

    def __init__(
        self,
        journal: EventJournal,
        *,
        dispatch_enabled: bool = True,
        completed_result_limit: int = 1024,
    ) -> None:
        if completed_result_limit < 1:
            raise ValueError("completed_result_limit must be at least 1")
        self._journal = journal
        self._dispatch_enabled = dispatch_enabled
        self._handlers: dict[str, CommandHandler] = {}
        self._builtin_handlers: set[str] = set()
        self._tasks: set[asyncio.Task[DispatchResult]] = set()
        self._task_identity: dict[
            asyncio.Task[DispatchResult], tuple[str, str, str | None]
        ] = {}
        self._completed: deque[DispatchResult] = deque(
            maxlen=completed_result_limit
        )
        self._install_builtin_handlers()

    @property
    def dispatch_enabled(self) -> bool:
        return self._dispatch_enabled

    @property
    def pending_count(self) -> int:
        return len(self._tasks)

    def set_dispatch_enabled(self, enabled: bool) -> None:
        """Enable or disable future submissions; existing work is unchanged."""

        if not isinstance(enabled, bool):
            raise TypeError("enabled must be a boolean")
        self._dispatch_enabled = enabled

    def register(
        self,
        command_type: type[BaseCommand],
        handler: CommandHandler,
        *,
        replace_builtin: bool = False,
    ) -> None:
        """Register exactly one handler for a canonical command type."""

        command_name = _command_name(command_type)
        if command_name not in _KNOWN_COMMAND_NAMES:
            raise ValueError(f"Unsupported command type: {command_name}")
        if not callable(handler):
            raise TypeError("handler must be callable")
        if command_name in self._handlers:
            if not replace_builtin:
                raise ValueError(f"Handler already registered for {command_name}")
            if command_name not in self._builtin_handlers:
                raise ValueError(
                    f"Cannot replace non-builtin handler for {command_name}"
                )
            self._builtin_handlers.remove(command_name)
        elif replace_builtin:
            raise ValueError(f"{command_name} is not a builtin handler")
        self._handlers[command_name] = handler

    async def submit(
        self,
        command: BaseCommand,
        *,
        context: DispatchContext | None = None,
    ) -> DispatchSubmission:
        """Accept a command and return immediately with an awaitable handle."""

        command_snapshot = _snapshot_command(command)
        dispatch_context = context or DispatchContext()
        command_name = command_snapshot.command_type
        correlation_id = dispatch_context.correlation_id

        if (
            not self._dispatch_enabled
            or dispatch_context.runtime_mode == RuntimeMode.REPLAY
        ):
            result = DispatchResult(
                status=DispatchStatus.SUPPRESSED,
                session_id=command_snapshot.session_id,
                command_type=command_name,
                correlation_id=correlation_id,
            )
            return self._completed_submission(result)

        if (
            dispatch_context.origin_session_id is not None
            and dispatch_context.origin_session_id != command_snapshot.session_id
        ):
            return self._completed_submission(
                _failure_result(
                    DispatchErrorCode.SESSION_MISMATCH,
                    command_snapshot.session_id,
                    command_name,
                    correlation_id,
                    "Origin event belongs to a different session",
                )
            )

        handler = self._handlers.get(command_name)
        if handler is None:
            result = _failure_result(
                DispatchErrorCode.UNCONFIGURED_HANDLER,
                command_snapshot.session_id,
                command_name,
                correlation_id,
                "No handler is configured for this command type",
            )
            return self._completed_submission(result)

        task = asyncio.create_task(
            self._execute(command_snapshot, dispatch_context, handler),
            name=f"interlock-dispatch:{command_snapshot.session_id}:{command_name}",
        )
        self._tasks.add(task)
        self._task_identity[task] = (
            command_snapshot.session_id,
            command_name,
            correlation_id,
        )
        task.add_done_callback(self._on_task_done)
        return DispatchSubmission(
            session_id=command_snapshot.session_id,
            command_type=command_name,
            correlation_id=correlation_id,
            _future=task,
        )

    async def submit_all(
        self,
        commands: Iterable[BaseCommand],
        *,
        context: DispatchContext | None = None,
    ) -> tuple[DispatchSubmission, ...]:
        """Submit one reducer command list in its exact returned order."""

        submissions: list[DispatchSubmission] = []
        for command in commands:
            submissions.append(await self.submit(command, context=context))
        return tuple(submissions)

    async def drain(self) -> tuple[DispatchResult, ...]:
        """Wait for the currently pending worker tasks without polling."""

        pending = tuple(self._tasks)
        if not pending:
            return ()
        identities = {
            task: self._task_identity.get(task)
            for task in pending
        }
        settled = await asyncio.gather(*pending, return_exceptions=True)
        results: list[DispatchResult] = []
        for task, outcome in zip(pending, settled):
            if isinstance(outcome, DispatchResult):
                results.append(outcome)
                continue
            identity = identities[task]
            if identity is None:
                continue
            if isinstance(outcome, asyncio.CancelledError):
                results.append(_cancelled_result(*identity))
            else:
                results.append(
                    _failure_result(
                        DispatchErrorCode.INTERNAL_ERROR,
                        *identity,
                        f"Dispatcher task failed ({type(outcome).__name__})",
                    )
                )
        return tuple(results)

    async def cancel_pending(self) -> tuple[DispatchResult, ...]:
        """Cancel current workers and wait until every task is contained."""

        pending = tuple(self._tasks)
        for task in pending:
            task.cancel()
        if not pending:
            return ()
        results: list[DispatchResult] = []
        for task in pending:
            identity = self._task_identity.get(task)
            try:
                results.append(await task)
            except asyncio.CancelledError:
                if identity is not None:
                    results.append(_cancelled_result(*identity))
        return tuple(results)

    def take_completed(self) -> tuple[DispatchResult, ...]:
        """Return and clear bounded terminal results retained for observability."""

        results = tuple(self._completed)
        self._completed.clear()
        return results

    async def _execute(
        self,
        command: BaseCommand,
        context: DispatchContext,
        handler: CommandHandler,
    ) -> DispatchResult:
        accepted: list[EventEnvelope] = []
        try:
            handler_command = _snapshot_command(command)
            raw_result = await handler(handler_command, context)
            candidates = _normalize_handler_result(raw_result)
            prepared_candidates = tuple(
                _prepare_candidate(candidate, command, context)
                for candidate in candidates
            )
            for prepared in prepared_candidates:
                envelope = await self._journal.append(prepared)
                accepted.append(envelope.model_copy(deep=True))
            return DispatchResult(
                status=DispatchStatus.COMPLETED,
                session_id=command.session_id,
                command_type=command.command_type,
                correlation_id=context.correlation_id,
                accepted_events=tuple(accepted),
            )
        except asyncio.CancelledError:
            return DispatchResult(
                status=DispatchStatus.CANCELLED,
                session_id=command.session_id,
                command_type=command.command_type,
                correlation_id=context.correlation_id,
                accepted_events=tuple(accepted),
                error=DispatchError(
                    code=DispatchErrorCode.CANCELLED,
                    session_id=command.session_id,
                    command_type=command.command_type,
                    correlation_id=context.correlation_id,
                    message="Command execution was cancelled",
                ),
            )
        except _DispatcherBoundaryError as error:
            return DispatchResult(
                status=DispatchStatus.FAILED,
                session_id=command.session_id,
                command_type=command.command_type,
                correlation_id=context.correlation_id,
                accepted_events=tuple(accepted),
                error=DispatchError(
                    code=error.code,
                    session_id=command.session_id,
                    command_type=command.command_type,
                    correlation_id=context.correlation_id,
                    message=error.safe_message,
                ),
            )
        except JournalError as error:
            return _failure_result(
                DispatchErrorCode.JOURNAL_REJECTED,
                command.session_id,
                command.command_type,
                context.correlation_id,
                f"Journal rejected the event ({error.code})",
                accepted_events=accepted,
            )
        except Exception as error:  # containment boundary for injected handlers
            return _failure_result(
                DispatchErrorCode.HANDLER_FAILED,
                command.session_id,
                command.command_type,
                context.correlation_id,
                f"Command handler failed ({type(error).__name__})",
                accepted_events=accepted,
            )

    def _completed_submission(self, result: DispatchResult) -> DispatchSubmission:
        future = asyncio.get_running_loop().create_future()
        future.set_result(result)
        self._completed.append(result)
        return DispatchSubmission(
            session_id=result.session_id,
            command_type=result.command_type,
            correlation_id=result.correlation_id,
            _future=future,
        )

    def _on_task_done(self, task: asyncio.Task[DispatchResult]) -> None:
        identity = self._task_identity.pop(task, None)
        self._tasks.discard(task)
        try:
            result = task.result()
        except asyncio.CancelledError:
            if identity is None:
                return
            result = _cancelled_result(*identity)
        except Exception as error:  # final task-containment boundary
            if identity is None:
                return
            result = _failure_result(
                DispatchErrorCode.INTERNAL_ERROR,
                *identity,
                f"Dispatcher task failed ({type(error).__name__})",
            )
        self._completed.append(result)

    def _install_builtin_handlers(self) -> None:
        self._handlers = {
            "PrepareBranch": _accept_prepare_branch,
            "PrepareOperation": _accept_prepare_operation,
            "QueueOutput": _accept_queue_output,
        }
        self._builtin_handlers = set(self._handlers.keys())


class _DispatcherBoundaryError(ValueError):
    def __init__(self, code: DispatchErrorCode, safe_message: str) -> None:
        super().__init__(safe_message)
        self.code = code
        self.safe_message = safe_message


async def _accept_prepare_branch(
    command: BaseCommand,
    context: DispatchContext,
) -> EventCandidate:
    assert isinstance(command, PrepareBranch)
    return _acceptance_candidate(
        command,
        context,
        event_type="BranchPreparationStarted",
        payload={
            "branch_id": command.branch_id,
            "operation_id": command.operation_id,
        },
        identity=f"{command.branch_id}:{command.operation_id}",
    )


async def _accept_prepare_operation(
    command: BaseCommand,
    context: DispatchContext,
) -> EventCandidate:
    assert isinstance(command, PrepareOperation)
    return _acceptance_candidate(
        command,
        context,
        event_type="OperationPreparationStarted",
        payload={"operation_id": command.operation_id},
        identity=command.operation_id,
    )


async def _accept_queue_output(
    command: BaseCommand,
    context: DispatchContext,
) -> EventCandidate:
    assert isinstance(command, QueueOutput)
    return _acceptance_candidate(
        command,
        context,
        event_type="SpeechQueued",
        payload={"speech_id": command.speech_id},
        identity=command.speech_id,
    )


def _acceptance_candidate(
    command: BaseCommand,
    context: DispatchContext,
    *,
    event_type: str,
    payload: dict[str, str],
    identity: str,
) -> EventCandidate:
    return EventCandidate(
        event_type=event_type,
        session_id=command.session_id,
        source=EventSource.SYSTEM,
        payload=payload,
        logical_time=context.logical_time,
        correlation_id=context.correlation_id,
        causation_id=context.origin_event_id,
        dedupe_key=f"dispatcher:{event_type}:{identity}",
    )


def _prepare_candidate(
    candidate: EventCandidate,
    command: BaseCommand,
    context: DispatchContext,
) -> EventCandidate:
    if candidate.session_id != command.session_id:
        raise _DispatcherBoundaryError(
            DispatchErrorCode.SESSION_MISMATCH,
            "Handler result targeted a different session",
        )
    if (
        context.origin_event_id is not None
        and candidate.causation_id not in (None, context.origin_event_id)
    ):
        raise _DispatcherBoundaryError(
            DispatchErrorCode.CAUSATION_MISMATCH,
            "Handler result conflicted with the originating event",
        )
    updates: dict[str, object] = {}
    if candidate.causation_id is None and context.origin_event_id is not None:
        updates["causation_id"] = context.origin_event_id
    if candidate.correlation_id is None and context.correlation_id is not None:
        updates["correlation_id"] = context.correlation_id
    if candidate.logical_time is None and context.logical_time is not None:
        updates["logical_time"] = context.logical_time
    return candidate.model_copy(update=updates, deep=True)


def _normalize_handler_result(result: HandlerResult) -> tuple[EventCandidate, ...]:
    if result is None:
        return ()
    if isinstance(result, EventCandidate):
        return (result.model_copy(deep=True),)
    if isinstance(result, (str, bytes)) or not isinstance(result, Sequence):
        raise _DispatcherBoundaryError(
            DispatchErrorCode.INVALID_HANDLER_RESULT,
            "Handler returned an unsupported result container",
        )
    candidates: list[EventCandidate] = []
    for item in result:
        if not isinstance(item, EventCandidate):
            raise _DispatcherBoundaryError(
                DispatchErrorCode.INVALID_HANDLER_RESULT,
                "Handler returned a non-event result",
            )
        candidates.append(item.model_copy(deep=True))
    return tuple(candidates)


def _snapshot_command(command: BaseCommand) -> BaseCommand:
    if not isinstance(command, BaseCommand):
        raise TypeError("command must be a BaseCommand instance")
    command_name = command.command_type
    if command_name not in _KNOWN_COMMAND_NAMES:
        raise ValueError(f"Unsupported command type: {command_name}")
    snapshot = type(command).model_validate(command.model_dump(mode="python"))
    if not isinstance(snapshot, BaseCommand):
        raise TypeError("command snapshot did not preserve BaseCommand")
    return snapshot.model_copy(deep=True)


def _command_name(command_type: type[BaseCommand]) -> str:
    if not isinstance(command_type, type) or not issubclass(command_type, BaseCommand):
        raise TypeError("command_type must be a BaseCommand subclass")
    command_name = command_type.model_fields["command_type"].default
    if not isinstance(command_name, str):
        raise TypeError("command_type must define a literal string default")
    return command_name


def _failure_result(
    code: DispatchErrorCode,
    session_id: str,
    command_type: str,
    correlation_id: str | None,
    message: str,
    *,
    accepted_events: Sequence[EventEnvelope] = (),
) -> DispatchResult:
    return DispatchResult(
        status=DispatchStatus.FAILED,
        session_id=session_id,
        command_type=command_type,
        correlation_id=correlation_id,
        accepted_events=tuple(
            envelope.model_copy(deep=True) for envelope in accepted_events
        ),
        error=DispatchError(
            code=code,
            session_id=session_id,
            command_type=command_type,
            correlation_id=correlation_id,
            message=message,
        ),
    )


def _cancelled_result(
    session_id: str,
    command_type: str,
    correlation_id: str | None,
) -> DispatchResult:
    return DispatchResult(
        status=DispatchStatus.CANCELLED,
        session_id=session_id,
        command_type=command_type,
        correlation_id=correlation_id,
        error=DispatchError(
            code=DispatchErrorCode.CANCELLED,
            session_id=session_id,
            command_type=command_type,
            correlation_id=correlation_id,
            message="Command execution was cancelled",
        ),
    )
