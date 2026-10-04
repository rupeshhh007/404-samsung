"""RUN-004 application composition; no HTTP, voice, or demo-provider adapter.

Each session owns one journal, one reducer task, and fresh worker bookkeeping.
Only the reducer creates the next authoritative state. Application policy glue
returns canonical facts through the journal; snapshots handed out are detached.
Missing provider/output/planner integrations fail explicitly, not as successes.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from hashlib import sha256
import re
from typing import Any

from interlock.config import Settings
from interlock.domain.enums import (
    ControlKind, EventSource, OperationState, RuntimeMode, SpeechState,
)
from interlock.domain.models import EvidenceRecord, EventEnvelope, MetricsSnapshot, OperationRecord, SessionState
from interlock.execution.descriptors import ToolRegistry
from interlock.execution.effects import EffectInterpretationError, EffectInterpreter, VerificationScope
from interlock.execution.safepoint import SafePointPolicy
from interlock.execution.tools import ProviderObservation, ToolProviderTransport, ToolRuntime
from interlock.intelligence.control import ControlInterpreter, InterpretationRequest
from interlock.intelligence.intent_graph import IntentGraph
from interlock.metrics import derive_metrics
from interlock.providers.base import StructuredProvider
from interlock.runtime.commands import (
    BaseCommand, CancelSpeech, DispatchTool, EmitOutput, InterpretInput,
    PrepareOperation, PublishProjection, RecordProtocolViolation,
    RequestSpeechCorrection, RequestToolCancellation, ValidateSpeech,
)
from interlock.runtime.dispatcher import (
    CommandDispatcher, CommandHandler, DispatchContext, DispatchResult, HandlerResult,
    DispatchStatus,
)
from interlock.runtime.journal import EventCandidate, EventJournal
from interlock.runtime.reducer import Reducer
from interlock.runtime.session import SessionRegistry
from interlock.truth.claims import ClaimEvaluator
from interlock.truth.evidence import EvidenceStore
from interlock.truth.speech import CorrectionPolicy, OutputPort, OutputPortFailure
from interlock.truth.truthlock import Truthlock


BindingResolver = Callable[[SessionState, OperationRecord], Mapping[str, Sequence[str]]]


def _identity(*values: str) -> str:
    return sha256(repr(values).encode()).hexdigest()


def _candidate(
    session_id: str, context: DispatchContext, event_type: str,
    payload: dict[str, Any], *, source: EventSource = EventSource.POLICY,
    identity: str | None = None,
) -> EventCandidate:
    return EventCandidate(
        session_id=session_id, event_type=event_type, source=source, payload=payload,
        causation_id=context.origin_event_id, correlation_id=context.correlation_id,
        logical_time=context.logical_time,
        dedupe_key=f"run004:{event_type}:{identity or context.origin_event_id}",
    )


@dataclass(frozen=True)
class RuntimeDependencies:
    """Explicit inward integrations; construction never calls these boundaries.

    bindings resolves *current* evidence for exactly the operation's bound paths;
    historical bindings are never silently substituted. extra_handlers allows
    existing/future verification and reconciliation workers to be injected using
    the canonical dispatcher interface, without inventing provider arguments.
    """

    tool_transport: ToolProviderTransport | None = None
    output: OutputPort | None = None
    model: StructuredProvider | None = None
    bindings: BindingResolver | None = None
    verification_scope: Callable[[EventEnvelope, SessionState], VerificationScope | None] | None = None
    input_context: Callable[[SessionState, EvidenceRecord], dict[str, Any]] | None = None
    extra_handlers: Mapping[type[BaseCommand], CommandHandler] | None = None


class _Session:
    def __init__(
        self, session_id: str, settings: Settings, registry: ToolRegistry,
        dependencies: RuntimeDependencies,
    ) -> None:
        self.session_id = session_id
        self.settings = settings
        self.registry = registry
        self.dependencies = dependencies
        # Session-private infrastructure can be reclaimed without reaching into
        # EventJournal's private locks/queues or retaining retired session IDs.
        self.sessions = SessionRegistry(settings.INTERLOCK_SESSION_RETENTION_S)
        self.journal = EventJournal(self.sessions, settings.INTERLOCK_EVENT_RETENTION)
        self.dispatcher = CommandDispatcher(self.journal)
        self.control = ControlInterpreter(settings, configured_provider=dependencies.model)
        self.effects = EffectInterpreter(registry=registry)
        self.claims = ClaimEvaluator()
        self.truthlock = Truthlock()
        self.corrections = CorrectionPolicy()
        self._state: SessionState | None = None
        self.closing = False
        self.failure: RuntimeError | None = None
        self._changed = asyncio.Condition()
        self._output_attempts: dict[str, DispatchContext] = {}
        self._output_ready: dict[str, asyncio.Event] = {}
        self._cancel_attempts: set[str] = set()
        self._output_lock = asyncio.Lock()
        self._monitors: set[asyncio.Task[None]] = set()
        self._last_event: EventEnvelope | None = None
        self.tools = (
            ToolRuntime(registry=registry, operation_resolver=self.operation,
                        transport=dependencies.tool_transport)
            if dependencies.tool_transport is not None else None
        )
        if self.tools is not None:
            self.dispatcher.register(PrepareOperation, self.tools.handle_prepare_operation,
                                     replace_builtin=True)
            self.dispatcher.register(DispatchTool, self.tools.handle_dispatch_tool)
            self.dispatcher.register(RequestToolCancellation,
                                     self.tools.handle_request_tool_cancellation)
        else:
            # Do not let the builtin "started" acceptance imply real preparation.
            self.dispatcher.register(PrepareOperation, self._missing_tool,
                                     replace_builtin=True)
        for kind, handler in (
            (InterpretInput, self._interpret), (ValidateSpeech, self._validate_speech),
            (EmitOutput, self._emit), (CancelSpeech, self._cancel),
            (RequestSpeechCorrection, self._correct),
            (RecordProtocolViolation, self._violation),
            (PublishProjection, self._projection),
        ):
            self.dispatcher.register(kind, handler)
        for kind, handler in (dependencies.extra_handlers or {}).items():
            self.dispatcher.register(kind, handler)
        self.task = asyncio.create_task(self._run(), name=f"interlock-reducer:{session_id}")

    def snapshot(self) -> SessionState:
        if self.failure:
            raise self.failure
        if self._state is None:
            raise RuntimeError("session has not started")
        return self._state.model_copy(deep=True)

    def operation(self, session_id: str, operation_id: str) -> OperationRecord | None:
        if session_id != self.session_id or self.failure or self._state is None:
            return None
        op = self._state.operations.get(operation_id)
        return op.model_copy(deep=True) if op else None

    async def wait_through(self, sequence: int) -> None:
        async with self._changed:
            await self._changed.wait_for(
                lambda: self.failure is not None
                or (self._state is not None and self._state.last_sequence >= sequence)
            )
        if self.failure:
            raise self.failure

    async def settle_queue(self) -> None:
        """A halted reducer cannot strand callers waiting on an undrained queue."""
        joined = asyncio.create_task(self.journal.get_queue(self.session_id).join())
        try:
            await asyncio.wait((joined, self.task), return_when=asyncio.FIRST_COMPLETED)
            if self.task.done():
                raise self.failure or RuntimeError("session reducer is not running")
            await joined
        finally:
            if not joined.done():
                joined.cancel()
            await asyncio.gather(joined, return_exceptions=True)

    def context(self, event: EventEnvelope) -> DispatchContext:
        context = DispatchContext.from_envelope(event, runtime_mode=RuntimeMode(self.snapshot().mode))
        # Inputs without a caller correlation still get a trace rooted at input.
        return DispatchContext(
            origin_event_id=context.origin_event_id,
            origin_session_id=context.origin_session_id,
            correlation_id=context.correlation_id or event.event_id,
            logical_time=context.logical_time, runtime_mode=context.runtime_mode,
        )

    async def _run(self) -> None:
        queue = self.journal.get_queue(self.session_id)
        try:
            while True:
                event = await queue.get()
                try:
                    old = self._state
                    next_state, commands = Reducer.reduce(old, event)
                    if next_state is None or next_state.last_sequence != event.sequence:
                        raise RuntimeError("reducer failed to consume accepted sequence")
                    # The sole authoritative replacement is the reducer's result.
                    self._state = next_state
                    self._last_event = event
                    async with self._changed:
                        self._changed.notify_all()
                    if next_state.mode != RuntimeMode.REPLAY:
                        context = self.context(event)
                        await self.submit(commands, context)
                        await self._policies(event, old, context)
                        if queue.empty():
                            await self._settled_policies(event, context)
                finally:
                    queue.task_done()
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self.failure = RuntimeError(f"runtime session halted ({type(error).__name__})")
            self.sessions.halt_session(self.session_id, "RUNTIME_REDUCTION_FAILED")
            self.dispatcher.set_dispatch_enabled(False)
            async with self._changed:
                self._changed.notify_all()

    async def submit(self, commands: Iterable[BaseCommand], context: DispatchContext) -> None:
        for command in commands:
            submission = await self.dispatcher.submit(command, context=context)

            output_id = command.speech_id if isinstance(command, EmitOutput) else None

            async def observe(handle=submission, origin=context, speech_id=output_id) -> None:
                result = await handle.wait()
                if speech_id in self._output_ready:
                    self._output_ready[speech_id].set()
                if result.status == DispatchStatus.FAILED and result.error is not None:
                    try:
                        await self.journal.append(_candidate(
                            self.session_id, origin, "ProtocolViolationObserved", {
                                "boundary": "dispatcher", "code": result.error.code.value,
                                "digest": result.error.message,
                            }, source=EventSource.SYSTEM,
                            identity=_identity(origin.origin_event_id or "", result.command_type),
                        ))
                    except Exception as error:
                        self.failure = RuntimeError(f"failure ingress rejected ({type(error).__name__})")
                        async with self._changed:
                            self._changed.notify_all()

            monitor = asyncio.create_task(observe())
            self._monitors.add(monitor)
            monitor.add_done_callback(self._monitors.discard)

    async def _policies(
        self, event: EventEnvelope, previous: SessionState | None, context: DispatchContext,
    ) -> None:
        state = self.snapshot()
        if event.event_type == "TranscriptHypothesisObserved":
            eid = event.payload["evidence_id"]
            if previous is not None and eid not in previous.evidence and eid in state.evidence:
                await self.submit([InterpretInput(
                    session_id=self.session_id, evidence_id=eid, modality="transcript",
                    content_ref=event.payload["text"],
                )], context)
        if event.event_type == "ToolResultObserved" and previous is not None:
            op = previous.operations.get(event.payload["operation_id"])
            if op is not None:
                try:
                    scope = (self.dependencies.verification_scope(event.model_copy(deep=True), state)
                             if self.dependencies.verification_scope else None)
                    candidates = self.effects.observe(
                        event, operation=op, known_effects=state.effects,
                        known_evidence=state.evidence, verification_scope=scope,
                    )
                except EffectInterpretationError:
                    candidates = (_candidate(self.session_id, context, "ProtocolViolationObserved", {
                        "boundary": "effect_interpreter", "code": "INVALID_EFFECT_OBSERVATION",
                        "digest": "Observation could not establish canonical effect authority",
                    }, source=EventSource.SYSTEM),)
                for candidate in candidates:
                    await self.journal.append(candidate)
        if event.event_type == "ControlIntentInterpreted":
            control = event.payload["control"]
            if control["kind"] == ControlKind.CANCEL_SPEECH:
                for speech_id, speech in sorted(state.speech.items()):
                    if speech.state in (SpeechState.APPROVED, SpeechState.QUEUED, SpeechState.EMITTING):
                        await self.journal.append(_candidate(
                            self.session_id, context, "SpeechCancellationRequested",
                            {"speech_id": speech_id}, identity=_identity(event.event_id, speech_id),
                        ))

    async def _settled_policies(self, event: EventEnvelope, context: DispatchContext) -> None:
        """Evaluate fresh state only after accepted facts have been consumed.

        Emit one pinned transition at a time: batching pins from the same state
        would make every transition after the first stale by construction.
        """
        state = self.snapshot()
        active = state.intents.get(state.active_intent_id)
        changes = self.claims.evaluate_all(
            state.claims, effects=state.effects, evidence=state.evidence,
            sequence=state.last_sequence, as_of=event.occurred_at,
            active_intent_revision_id=active.active_revision_id if active else None,
            plans=state.plans, divergences=state.divergences,
        )
        if changes:
            change = changes[0]
            await self.journal.append(_candidate(
                self.session_id, context, "ClaimStateChanged", change.model_dump(mode="json", by_alias=True),
                identity=_identity(event.event_id, change.claim_id),
            ))
            return
        if self.closing or self.dependencies.bindings is None:
            return
        for op in sorted(state.operations.values(), key=lambda item: item.operation_id):
            if op.state != OperationState.READY:
                continue
            revision = state.revisions.get(op.intent_revision_id)
            node = state.intents.get(revision.intent_id) if revision else None
            current = state.revisions.get(node.active_revision_id) if node else None
            if current is None:
                continue
            decision = SafePointPolicy.decide(
                operation=op, current_revision=current, session_state=state,
                registry=self.registry,
                evidence_ids_by_path=self.dependencies.bindings(state.model_copy(deep=True), op.model_copy(deep=True)),
            )
            follow_up = decision.follow_up_event
            if follow_up is not None and type(follow_up).__name__ == "CancellationRequested" and op.cancellation_state != "NONE":
                continue
            if follow_up is not None:
                await self.journal.append(_candidate(
                    self.session_id, context, type(follow_up).__name__,
                    follow_up.model_dump(mode="json"),
                    identity=_identity(event.event_id, op.operation_id),
                ))
                return

    async def _missing_tool(self, command: BaseCommand, context: DispatchContext) -> None:
        raise RuntimeError("PRV-001 or an explicitly injected tool transport is required")

    async def _projection(self, command: BaseCommand, context: DispatchContext) -> None:
        # API-002 owns publication; callers can read the detached pinned snapshot.
        return None

    async def _violation(self, command: BaseCommand, context: DispatchContext) -> EventCandidate:
        assert isinstance(command, RecordProtocolViolation)
        return _candidate(self.session_id, context, "ProtocolViolationObserved", {
            "boundary": command.boundary, "code": command.code, "digest": command.digest,
        }, source=EventSource.SYSTEM)

    async def _interpret(self, command: BaseCommand, context: DispatchContext) -> HandlerResult:
        assert isinstance(command, InterpretInput)
        state = self.snapshot()
        evidence = state.evidence[command.evidence_id]
        # Media references are not transcript text and are never fetched here.
        if command.modality not in ("text", "transcript"):
            raise RuntimeError("input text resolver is not configured for this modality")
        result = await self.control.interpret(InterpretationRequest(
            control_id=_identity(context.origin_event_id or "", command.evidence_id),
            raw_evidence_id=command.evidence_id, text=evidence.content_ref,
            final=evidence.provenance.get("final", True),
            correlation_id=context.correlation_id or context.origin_event_id or command.evidence_id,
            active_intent_id=state.active_intent_id,
            candidate_target_ids=sorted(state.intents),
            context=(self.dependencies.input_context(state.model_copy(deep=True), evidence.model_copy(deep=True))
                     if self.dependencies.input_context else {}),
        ))
        if self.snapshot().last_sequence != state.last_sequence:
            # A slow model cannot apply control to a different sequence-pinned
            # context. No worker owns a hidden mutable "current intent" store.
            return _candidate(self.session_id, context, "ControlIntentInterpreted", {"control": {
                **result.control.model_dump(mode="json"), "kind": "CLARIFY", "consequential": False,
                "clarification": "The context changed while interpreting this input. Please clarify.",
            }})
        if result.provisional and result.control.consequential:
            # The canonical proposal event has no operational consequences.
            # A partial PAUSE/RESUME/etc. must not be applied as a final control.
            candidates = []
        else:
            candidates = [_candidate(self.session_id, context, "ControlIntentInterpreted",
                                     {"control": result.control.model_dump(mode="json")},
                                     source=EventSource.MODEL)]
        if result.intent_delta is not None:
            # A delta is only a proposal. No partial/final transcript grants
            # action authorization, and unsupported goal lifecycle is not invented.
            IntentGraph(state.intents, state.revisions).apply_delta(
                result.intent_delta, revision_id=_identity(context.origin_event_id or "", "revision"),
                created_by_event_id=context.origin_event_id or result.control.control_id,
            )
            candidates.append(_candidate(self.session_id, context, "IntentRevisionProposed",
                                          {"intent_delta": result.intent_delta.model_dump(mode="json")},
                                          source=EventSource.MODEL))
        return candidates

    async def _validate_speech(self, command: BaseCommand, context: DispatchContext) -> HandlerResult:
        assert isinstance(command, ValidateSpeech)
        state = self.snapshot()
        speech = state.speech.get(command.speech_id)
        if speech is None or speech.state != SpeechState.PROPOSED:
            return None
        decision = self.truthlock.validate(
            speech_act=speech, claims=state.claims, evidence=state.evidence,
            through_sequence=state.last_sequence, authoritative_sequence=state.last_sequence,
            divergences=state.divergences, state=state,
            as_of=self._last_event.occurred_at if self._last_event else None,
        )
        if decision.is_retry_stale:
            raise RuntimeError("truth policy returned stale for current snapshot")
        payload = decision.create_approval_event() if decision.is_approved else decision.create_blocked_event()
        return _candidate(self.session_id, context, type(payload).__name__,
                          payload.model_dump(mode="json"),
                          identity=_identity(command.speech_id, str(state.last_sequence)))

    async def _correct(self, command: BaseCommand, context: DispatchContext) -> HandlerResult:
        assert isinstance(command, RequestSpeechCorrection)
        proposal = self.corrections.propose(
            command, self.snapshot(),
            correction_speech_id=_identity(command.speech_id, context.origin_event_id or ""),
        )
        if proposal is None:
            return None
        return _candidate(self.session_id, context, "SpeechActProposed",
                          {"speech_act": proposal.speech_act.model_dump(mode="json")})

    async def _emit(self, command: BaseCommand, context: DispatchContext) -> HandlerResult:
        assert isinstance(command, EmitOutput)
        await self.settle_queue()
        async with self._output_lock:
            if command.speech_id in self._output_attempts:
                return None
            # Serialize audible acts, not just command submissions. An adapter
            # terminal fact releases the next act; ambiguity never grants it.
            async with self._changed:
                await self._changed.wait_for(lambda: self.closing or self.failure is not None
                    or self._state.speech[command.speech_id].cancellation_pending
                    or all(self._state.speech[sid].heard is not None for sid in self._output_attempts))
            state = self.snapshot()
            speech = state.speech.get(command.speech_id)
            if (self.closing or speech is None or speech.state != SpeechState.QUEUED
                    or speech.cancellation_pending or speech.correction_pending
                    or not speech.rendered_text or not speech.approved_policy_id
                    or speech.approved_through_sequence is None
                    or set(speech.approved_claim_versions) != set(speech.claim_ids)
                    or any(state.claims.get(cid) is None or state.claims[cid].updated_by_event_id != version
                           for cid, version in speech.approved_claim_versions.items())):
                return None
            if self.dependencies.output is None:
                raise RuntimeError("OutputPort is not configured")
            if len(self._output_attempts) >= self.settings.INTERLOCK_EVENT_RETENTION:
                raise RuntimeError("output attempt retention exhausted; start a fresh session")
            # Reserve before I/O, including ambiguous failures: retries must not
            # repeat audible output when the adapter cannot prove it did not start.
            self._output_attempts[command.speech_id] = context
            self._output_ready[command.speech_id] = asyncio.Event()
            try:
                await self.dependencies.output.emit(
                    session_id=self.session_id, speech_id=command.speech_id,
                    rendered_text=speech.rendered_text,
                )
            except OutputPortFailure as failure:
                return self._output_failure(command.speech_id, context, failure)
            return _candidate(self.session_id, context, "SpeechEmissionStarted",
                              {"speech_id": command.speech_id}, source=EventSource.OUTPUT_ADAPTER,
                              identity=command.speech_id)

    def _output_failure(self, speech_id: str, context: DispatchContext, failure: OutputPortFailure) -> EventCandidate:
        return _candidate(self.session_id, context, "SpeechEmissionFailed", {
            "speech_id": speech_id,
            "error_code": (failure.error_code if re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", failure.error_code)
                           else "OUTPUT_ADAPTER_FAILURE"),
            "heard": failure.heard, "retryable": failure.retryable,
        }, source=EventSource.OUTPUT_ADAPTER, identity=speech_id)

    async def _cancel(self, command: BaseCommand, context: DispatchContext) -> HandlerResult:
        assert isinstance(command, CancelSpeech)
        if command.speech_id not in self._output_attempts:
            return None
        speech = self.snapshot().speech.get(command.speech_id)
        if speech is None or speech.state not in (SpeechState.QUEUED, SpeechState.EMITTING):
            return None
        identity = _identity(command.speech_id, context.origin_event_id or "")
        if identity in self._cancel_attempts:
            return None
        if self.dependencies.output is None:
            raise RuntimeError("OutputPort is not configured")
        if len(self._cancel_attempts) >= self.settings.INTERLOCK_EVENT_RETENTION:
            raise RuntimeError("output cancellation retention exhausted")
        self._cancel_attempts.add(identity)
        try:
            await self.dependencies.output.cancel(session_id=self.session_id, speech_id=command.speech_id)
        except OutputPortFailure as failure:
            return self._output_failure(command.speech_id, context, failure)
        return None


class Application:
    """Small bounded application graph, with no construction-time I/O.

    DEMO constructs with fallback interpretation and no credentials. Tool/output
    execution requires explicitly injected inward ports; it is not a fake demo.
    """

    def __init__(
        self, settings: Settings | None = None, *, registry: ToolRegistry | None = None,
        dependencies: RuntimeDependencies | None = None, max_sessions: int = 128,
    ) -> None:
        if type(max_sessions) is not int or max_sessions < 1:
            raise ValueError("max_sessions must be positive")
        self.settings = (settings or Settings()).model_copy(deep=True)
        self.registry = registry or ToolRegistry(default_timeout_ms=self.settings.INTERLOCK_TOOL_TIMEOUT_MS)
        self.dependencies = dependencies or RuntimeDependencies()
        self.max_sessions = max_sessions
        self._sessions: dict[str, _Session] = {}
        self._lifecycle_lock = asyncio.Lock()

    async def start_session(self, session_id: str, *, logical_time: int = 0) -> SessionState:
        async with self._lifecycle_lock:
            if not session_id or session_id in self._sessions:
                raise ValueError("session identity must be new and nonempty")
            if len(self._sessions) >= self.max_sessions:
                raise RuntimeError("session capacity reached")
            session = _Session(session_id, self.settings, self.registry, self.dependencies)
            self._sessions[session_id] = session
            try:
                event = await session.journal.append(EventCandidate(
                    session_id=session_id, event_type="SessionStarted", source=EventSource.SYSTEM,
                    payload={"mode": self.settings.INTERLOCK_MODE}, logical_time=logical_time,
                ))
                await session.wait_through(event.sequence)
            except BaseException:
                session.task.cancel()
                await asyncio.gather(session.task, return_exceptions=True)
                del self._sessions[session_id]
                raise
            return session.snapshot()

    async def append(self, candidate: EventCandidate) -> EventEnvelope:
        session = self._sessions[candidate.session_id]
        if session.closing:
            raise RuntimeError("session is closing")
        if (session.journal.get_queue(candidate.session_id).qsize() >= self.settings.INTERLOCK_EVENT_RETENTION
                or session.dispatcher.pending_count >= self.settings.INTERLOCK_EVENT_RETENTION):
            raise RuntimeError("user intake capacity reached; retry after drain")
        event = await session.journal.append(candidate)
        await session.wait_through(event.sequence)
        return event

    def snapshot(self, session_id: str) -> SessionState:
        return self._sessions[session_id].snapshot()

    def evidence_snapshot(self, session_id: str) -> EvidenceStore:
        """Disposable read projection, never a second authoritative evidence store."""
        store = EvidenceStore(session_id)
        for evidence in self.snapshot(session_id).evidence.values():
            store.add(evidence)
        return store

    def events(self, session_id: str) -> list[EventEnvelope]:
        return self._sessions[session_id].journal.read_events(session_id)

    def metrics(self, session_id: str) -> MetricsSnapshot:
        state = self.snapshot(session_id)
        return derive_metrics(session_id, self.events(session_id), through_sequence=state.last_sequence)

    def dispatch_results(self, session_id: str) -> tuple[DispatchResult, ...]:
        return self._sessions[session_id].dispatcher.take_completed()

    async def drain(self, session_id: str) -> None:
        session = self._sessions[session_id]
        queue = session.journal.get_queue(session_id)
        while True:
            if session.failure:
                raise session.failure
            await session.settle_queue()
            await session.dispatcher.drain()
            if session._monitors:
                await asyncio.gather(*tuple(session._monitors))
            if queue.empty() and session.dispatcher.pending_count == 0 and not session._monitors:
                return

    async def output_finished(self, session_id: str, speech_id: str, *, heard: bool,
                              logical_time: int, origin_event_id: str) -> EventEnvelope:
        """Adapter terminal fact; only after start acceptance has been reduced."""
        if type(heard) is not bool:
            raise TypeError("heard must be an explicit boolean")
        session = self._sessions[session_id]
        context = session._output_attempts[speech_id]
        if context.origin_event_id != origin_event_id:
            raise ValueError("output completion belongs to a different attempt/generation")
        # Wait for this speech's start/terminal fact, not unrelated tool work.
        await session._output_ready[speech_id].wait()
        if session.failure:
            raise session.failure
        event = await session.journal.append(_candidate(
            session_id, DispatchContext(
                origin_event_id=context.origin_event_id, origin_session_id=session_id,
                correlation_id=context.correlation_id, logical_time=logical_time,
            ), "SpeechEmissionFinished", {"speech_id": speech_id, "heard": heard},
            source=EventSource.OUTPUT_ADAPTER, identity=speech_id,
        ))
        await session.wait_through(event.sequence)
        return event

    async def output_failed(self, session_id: str, speech_id: str, *,
                            failure: OutputPortFailure, logical_time: int,
                            origin_event_id: str) -> EventEnvelope:
        """Trusted asynchronous adapter failure, with explicit heard semantics."""
        if not isinstance(failure, OutputPortFailure):
            raise TypeError("output failure ingress requires OutputPortFailure")
        session = self._sessions[session_id]
        context = session._output_attempts[speech_id]
        if context.origin_event_id != origin_event_id:
            raise ValueError("output failure belongs to a different attempt/generation")
        await session._output_ready[speech_id].wait()
        terminal_context = DispatchContext(
            origin_event_id=context.origin_event_id, origin_session_id=session_id,
            correlation_id=context.correlation_id, logical_time=logical_time,
        )
        event = await session.journal.append(session._output_failure(speech_id, terminal_context, failure))
        await session.wait_through(event.sequence)
        return event

    async def tool_callback(self, session_id: str, operation_id: str,
                            observation: ProviderObservation, *,
                            context: DispatchContext) -> EventEnvelope | None:
        """Late callback ingress remains available while a session is closing."""
        session = self._sessions[session_id]
        if context.origin_session_id != session_id or not context.origin_event_id:
            raise ValueError("callback requires same-session accepted command lineage")
        operation = session.operation(session_id, operation_id)
        if operation is None or context.origin_event_id != operation.dispatch_requested_event_id:
            raise ValueError("callback lineage does not match current dispatch token")
        if session.tools is None:
            raise RuntimeError("tool transport is not configured")
        candidate = await session.tools.observe_callback(
            session_id=session_id, operation_id=operation_id,
            observation=observation, context=context,
        )
        if candidate is None:
            return None
        event = await session.journal.append(candidate)
        await session.wait_through(event.sequence)
        return event

    @staticmethod
    def replay(events: Iterable[EventEnvelope]) -> SessionState:
        state = None
        for event in events:
            next_state, commands = Reducer.reduce(state, event.model_copy(deep=True), mode=RuntimeMode.REPLAY)
            if commands or next_state is None or next_state.last_sequence != event.sequence:
                raise ValueError("replay requires a complete contiguous session journal")
            state = next_state
        if state is None:
            raise ValueError("replay requires SessionStarted")
        return state.model_copy(deep=True)

    async def close_session(self, session_id: str) -> SessionState:
        """Quiesce before retirement; never erase a session with in-flight workers.

        The caller may bound this wait, but cancellation leaves a closing session
        intact for a later drain/close rather than losing late physical facts.
        """
        async with self._lifecycle_lock:
            session = self._sessions[session_id]
            session.closing = True
            async with session._changed:
                session._changed.notify_all()
            await self.drain(session_id)
            context = session.context(session._last_event)
            for speech_id in tuple(session._output_attempts):
                speech = session.snapshot().speech[speech_id]
                if speech.state in (SpeechState.QUEUED, SpeechState.EMITTING):
                    await session.journal.append(_candidate(
                        session_id, context, "SpeechCancellationRequested", {"speech_id": speech_id},
                        identity=_identity("shutdown", speech_id),
                    ))
            await self.drain(session_id)
            async with session._changed:
                await session._changed.wait_for(lambda: session.failure is not None or all(
                    session._state.speech[sid].heard is not None for sid in session._output_attempts
                ))
            if session.failure:
                raise session.failure
            for op in session.snapshot().operations.values():
                if op.dispatch_requested_event_id and op.effect_state in ("NOT_STARTED", "IN_FLIGHT", "OUTCOME_UNKNOWN"):
                    await session.journal.append(_candidate(
                        session_id, context, "ToolTimedOut", {
                            "operation_id": op.operation_id, "after_dispatch": True,
                        }, source=EventSource.SYSTEM, identity=_identity("shutdown", op.operation_id),
                    ))
            await self.drain(session_id)
            final = session.snapshot()
            session.dispatcher.set_dispatch_enabled(False)
            session.task.cancel()
            await asyncio.gather(session.task, return_exceptions=True)
            await session.journal.clear_session(session_id)
            del self._sessions[session_id]
            return final

    async def close(self) -> None:
        for session_id in tuple(self._sessions):
            await self.close_session(session_id)
