"""RUN-004 application composition and the deterministic EXT-001 DEMO host.

Each session owns one journal, one reducer task, and fresh worker bookkeeping.
Only the reducer creates the next authoritative state. Application policy glue
returns canonical facts through the journal; snapshots handed out are detached.
Missing provider/output/planner integrations fail explicitly, not as successes.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
import json
import re
import sys
from typing import Any, Protocol

from interlock.config import Settings
from interlock.domain.enums import (
    Authorization, CancellationState, ClaimCertainty, ClaimState, ControlKind,
    DivergenceState, EffectState, EventSource, EvidenceAuthority, IntentMaturity, OperationState, RuntimeMode,
    SpeechActType, SpeechState,
)
from interlock.domain.models import (
    ClaimRecord, DivergenceCase, EffectRecord, EvidenceRecord, EventEnvelope, IntentRevision,
    MetricsSnapshot, OperationRecord, SessionState, SpeechAct,
)
from interlock.execution.descriptors import ToolRegistry
from interlock.execution.effects import EffectInterpretationError, EffectInterpreter, VerificationScope
from interlock.execution.operations import OperationManager
from interlock.execution.safepoint import SafePointPolicy
from interlock.execution.tools import (
    ProviderCancellationRequest, ProviderCancellationResult, ProviderObservation,
    ProviderResponse, ToolInvocation, ToolProviderTransport, ToolRuntime,
)
from interlock.intelligence.control import ControlInterpreter, InterpretationRequest
from interlock.intelligence.intent_graph import IntentGraph, bind_dependencies, dependency_fingerprint
from interlock.metrics import derive_metrics
from interlock.providers.base import StructuredProvider
from interlock.runtime.commands import (
    BaseCommand, BuildReconciliationPlan, CancelSpeech, DispatchTool, EmitOutput, InterpretInput,
    PrepareOperation, PublishProjection, RecordProtocolViolation,
    RequestClarification, RequestSpeechCorrection, RequestToolCancellation,
    ValidateSpeech,
)
from interlock.runtime.dispatcher import (
    CommandDispatcher, CommandHandler, DispatchContext, DispatchResult, HandlerResult,
    DispatchStatus,
)
from interlock.runtime.journal import EventCandidate, EventJournal
from interlock.runtime.reducer import Reducer
from interlock.runtime.session import SessionRegistry
from interlock.truth.claims import ClaimEvaluator, _match_slot
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
    projection: CommandHandler | None = None
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
        self.operations = OperationManager(registry)
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
        self._divergence_attempts: set[str] = set()
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
            (RequestClarification, self._clarify),
            (RequestSpeechCorrection, self._correct),
            (RecordProtocolViolation, self._violation),
            (PublishProjection, dependencies.projection or self._projection),
        ):
            self.dispatcher.register(kind, handler)
        if settings.INTERLOCK_MODE in (RuntimeMode.DEMO, RuntimeMode.TEST, RuntimeMode.LIVE):
            # EXE-006 owns repair planning.  EXT-001 only surfaces the canonical
            # divergence and deliberately leaves it unresolved.
            self.dispatcher.register(BuildReconciliationPlan, self._defer_reconciliation)
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
        session_mode = RuntimeMode(state.mode)
        if session_mode in (RuntimeMode.DEMO, RuntimeMode.TEST, RuntimeMode.LIVE):
            await self._booking_divergence_policy(event, state, context)
        if session_mode == RuntimeMode.DEMO:
            await self._demo_policies(event, previous, state, context)

    async def _booking_divergence_policy(
        self, event: EventEnvelope, state: SessionState, context: DispatchContext,
    ) -> None:
        """Surfaces real-world divergence between appointment revisions and authoritative effects.

        Shared across DEMO, TEST, and LIVE modes. Does NOT create operations,
        claims, authorizations, speech, reconciliation plans, or fake provider calls.
        """
        if event.event_type == "IntentRevisionCommitted":
            rev_payload = event.payload.get("revision")
            rev_id = (
                rev_payload.revision_id
                if hasattr(rev_payload, "revision_id")
                else rev_payload.get("revision_id")
                if isinstance(rev_payload, dict)
                else None
            )
            revision = state.revisions.get(rev_id) if rev_id else None
            if revision is None or revision.parent_revision_id is None:
                return
            if revision.values.get("requested_slot") is None:
                return
            for effect in sorted(state.effects.values(), key=lambda item: item.effect_id):
                await self._detect_booking_divergence(event, revision, effect, context)
            return

        if event.event_type == "WorldEffectObserved":
            effect_payload = event.payload.get("effect")
            eff_id = (
                effect_payload.effect_id
                if hasattr(effect_payload, "effect_id")
                else effect_payload.get("effect_id")
                if isinstance(effect_payload, dict)
                else None
            )
            effect = state.effects.get(eff_id) if eff_id else None
            node = state.intents.get(state.active_intent_id) if state.active_intent_id else None
            revision = state.revisions.get(node.active_revision_id) if node and node.active_revision_id else None
            if effect is not None and revision is not None:
                await self._detect_booking_divergence(event, revision, effect, context)
            return

    async def _demo_policies(
        self, event: EventEnvelope, previous: SessionState | None,
        state: SessionState, context: DispatchContext,
    ) -> None:
        """Minimal scripted appointment policy for the credential-free demo.

        It creates only canonical journal facts.  The reducer remains the sole
        state writer and every provider write still crosses SAFEPOINT and
        ToolRuntime.  A corrected goal is intentionally not auto-repaired.
        """
        if event.event_type == "IntentAuthorizationChanged":
            revision = state.revisions.get(event.payload["revision_id"])
            if revision is None or revision.authorization != Authorization.AUTHORIZED:
                return
            if revision.values.get("goal_type") != "appointment_booking":
                return
            await self._propose_demo_claim(event, revision, context)
            if revision.parent_revision_id is not None:
                return
            bindings = bind_dependencies(revision, ("center_id", "requested_slot"))
            known = {
                item.idempotency_key: item.fingerprint
                for item in state.operations.values() if item.idempotency_key
            }
            operation_id = _identity(revision.revision_id, "appointment.book")
            if operation_id in state.operations:
                return
            operation = self.operations.create_operation(
                operation_id=operation_id,
                session_id=self.session_id,
                intent_goal_id=revision.intent_id,
                intent_revision=revision,
                bindings=bindings,
                tool_name="appointment.book",
                arguments={
                    "center_id": revision.values["center_id"],
                    "requested_slot": revision.values["requested_slot"],
                },
                existing_operation_ids=set(state.operations),
                known_idempotency_digests=known,
            )
            await self.journal.append(_candidate(
                self.session_id, context, "OperationCreated",
                {"operation": operation.model_dump(mode="json")},
                identity=operation.operation_id,
            ))
            return

        if event.event_type == "IntentRevisionCommitted":
            rev_payload = event.payload.get("revision")
            rev_id = (
                rev_payload.revision_id
                if hasattr(rev_payload, "revision_id")
                else rev_payload.get("revision_id")
                if isinstance(rev_payload, dict)
                else None
            )
            revision = state.revisions.get(rev_id) if rev_id else None
            if revision is None:
                return
            if revision.parent_revision_id is not None:
                for operation in sorted(state.operations.values(), key=lambda item: item.operation_id):
                    if (operation.intent_revision_id == revision.parent_revision_id
                            and operation.state not in {
                                OperationState.SUCCEEDED, OperationState.FAILED,
                                OperationState.CANCELLED, OperationState.SUPERSEDED,
                            }
                            and operation.cancellation_state == CancellationState.NONE):
                        await self.journal.append(_candidate(
                            self.session_id, context, "CancellationRequested",
                            {"operation_id": operation.operation_id,
                             "reason": "intent revision was superseded"},
                            identity=_identity(revision.revision_id, operation.operation_id),
                        ))
                        break
            return

        if event.event_type == "DivergenceDetected":
            speech = SpeechAct(
                speech_id=_identity(event.event_id, "unresolved-divergence"),
                act_type=SpeechActType.UNCERTAINTY,
                template_id="tmpl_outcome_unknown",
                slots={}, claim_ids=[], requested_certainty=ClaimCertainty.UNCERTAIN,
                state=SpeechState.PROPOSED, created_by_event_id=event.event_id,
            )
            await self.journal.append(_candidate(
                self.session_id, context, "SpeechActProposed",
                {"speech_act": speech.model_dump(mode="json")}, identity=speech.speech_id,
            ))
            return

        if event.event_type == "ClaimStateChanged":
            to_state = event.payload.get("to_state")
            if to_state == ClaimState.CONFIRMED.value:
                claim_id = event.payload.get("claim_id")
                claim = state.claims.get(claim_id)
                if claim is not None and claim.predicate == "appointment_booked":
                    active_intent = state.intents.get(state.active_intent_id) if state.active_intent_id else None
                    active_rev_id = active_intent.active_revision_id if active_intent else None
                    if claim.intent_revision_id == active_rev_id:
                        unresolved = [
                            d for d in state.divergences.values()
                            if d.state in (
                                DivergenceState.OPEN,
                                DivergenceState.PLANNED,
                                DivergenceState.RECONCILING,
                                DivergenceState.ESCALATED,
                            )
                        ]
                        if not unresolved:
                            speech_id = _identity(claim.claim_id, "confirmed-speech")
                            already_proposed = any(
                                sp.speech_id == speech_id
                                or (claim.claim_id in sp.claim_ids and sp.act_type == SpeechActType.RESULT)
                                for sp in state.speech.values()
                            )
                            if not already_proposed:
                                requested_slot = (
                                    claim.object.get("requested_slot")
                                    if isinstance(claim.object, dict)
                                    else None
                                )
                                canonical_slot = (
                                    claim.object.get("confirmed_slot")
                                    or claim.object.get("requested_slot")
                                    if isinstance(claim.object, dict)
                                    else None
                                )
                                speech = SpeechAct(
                                    speech_id=speech_id,
                                    act_type=SpeechActType.RESULT,
                                    template_id="tmpl_booking_confirmed",
                                    slots={"slot": canonical_slot or "11:00"},
                                    claim_ids=[claim.claim_id],
                                    requested_certainty=ClaimCertainty.CONFIRMED,
                                    state=SpeechState.PROPOSED,
                                    created_by_event_id=event.event_id,
                                )
                                await self.journal.append(_candidate(
                                    self.session_id, context, "SpeechActProposed",
                                    {"speech_act": speech.model_dump(mode="json")},
                                    identity=speech.speech_id,
                                ))
            return

    async def _propose_demo_claim(
        self, event: EventEnvelope, revision: IntentRevision, context: DispatchContext,
    ) -> None:
        claim_id = _identity(revision.revision_id, "appointment-booked")
        if claim_id in self.snapshot().claims:
            return
        claim = ClaimRecord(
            claim_id=claim_id,
            predicate="appointment_booked",
            subject={"center_id": revision.values["center_id"]},
            object={
                "requested_slot": revision.values["requested_slot"],
                "operation_id": _identity(revision.revision_id, "appointment.book"),
            },
            state=ClaimState.PROPOSED,
            required_evidence_rule="appointment_booked",
            supporting_evidence_ids=[],
            intent_revision_id=revision.revision_id,
            updated_by_event_id=event.event_id,
        )
        await self.journal.append(_candidate(
            self.session_id, context, "ClaimProposed",
            {"claim": claim.model_dump(mode="json")}, identity=claim_id,
        ))

    async def _detect_booking_divergence(
        self,
        event: EventEnvelope,
        revision: IntentRevision,
        effect: EffectRecord,
        context: DispatchContext,
    ) -> None:
        state = self.snapshot()
        if effect.state != EffectState.COMMITTED or effect.authority != EvidenceAuthority.AUTHORITATIVE:
            return
        if any(e.supersedes_effect_id == effect.effect_id for e in state.effects.values()):
            return
        desired = revision.values.get("requested_slot")
        observed = effect.parameters.get("confirmed_slot") or effect.parameters.get("requested_slot")
        if desired is None or observed is None or _match_slot(observed, desired):
            return
        divergence_id = _identity(revision.revision_id, effect.effect_id, "divergence")
        if divergence_id in state.divergences or divergence_id in self._divergence_attempts:
            return
        if any(
            d.state == DivergenceState.OPEN
            and d.desired_fingerprint == revision.dependency_fingerprint
            and effect.effect_id in d.observed_effect_ids
            for d in state.divergences.values()
        ):
            return
        self._divergence_attempts.add(divergence_id)
        case = DivergenceCase(
            divergence_id=divergence_id,
            desired_fingerprint=revision.dependency_fingerprint,
            observed_effect_ids=[effect.effect_id],
            kind="DESIRED_SLOT_DIFFERS_FROM_CONFIRMED_SLOT",
            state=DivergenceState.OPEN,
            detected_by_event_id=event.event_id,
            authorization_required=True,
        )
        await self.journal.append(_candidate(
            self.session_id, context, "DivergenceDetected",
            {"case": case.model_dump(mode="json")}, identity=divergence_id,
        ))

    async def _defer_reconciliation(
        self, command: BaseCommand, context: DispatchContext,
    ) -> None:
        assert isinstance(command, BuildReconciliationPlan)
        return None

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
            operations=state.operations,
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
        demo_root = (
            _demo_root_booking(evidence.content_ref, command.evidence_id, context)
            if self.settings.INTERLOCK_MODE == RuntimeMode.DEMO and state.active_intent_id is None
            else None
        )
        if demo_root is not None:
            control, revision = demo_root
            return [
                _candidate(self.session_id, context, "ControlIntentInterpreted",
                           {"control": control}, source=EventSource.MODEL),
                _candidate(self.session_id, context, "IntentRevisionCommitted",
                           {"revision": revision.model_dump(mode="json")},
                           identity=_identity(revision.revision_id, "commit")),
                _candidate(self.session_id, context, "IntentAuthorizationChanged", {
                    "revision_id": revision.revision_id,
                    "authorization": Authorization.AUTHORIZED.value,
                    "evidence_id": command.evidence_id,
                }, identity=_identity(revision.revision_id, "authorization")),
            ]
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
            # Reducer model_copy transitions can retain enum instances despite
            # wire models using enum values. Normalize through canonical JSON at
            # this policy boundary before INTEL-002's strict JSON snapshot.
            graph = IntentGraph(
                {
                    key: type(value).model_validate_json(value.model_dump_json())
                    for key, value in state.intents.items()
                },
                {
                    key: type(value).model_validate_json(value.model_dump_json())
                    for key, value in state.revisions.items()
                },
            )
            proposal = graph.apply_delta(
                result.intent_delta, revision_id=_identity(context.origin_event_id or "", "revision"),
                created_by_event_id=context.origin_event_id or result.control.control_id,
            )
            candidates.append(_candidate(self.session_id, context, "IntentRevisionProposed",
                                          {"intent_delta": result.intent_delta.model_dump(mode="json")},
                                          source=EventSource.MODEL))
            if not result.provisional:
                # Reducer remains the sole writer. This policy fact carries the
                # exact validated proposal and starts NOT_REQUESTED; it grants
                # no authorization to dispatch consequential work.
                candidates.append(_candidate(
                    self.session_id, context, "IntentRevisionCommitted",
                    {"revision": proposal.proposed_revision.model_dump(mode="json")},
                    identity=_identity(context.origin_event_id or "", "revision-commit"),
                ))
                if (self.settings.INTERLOCK_MODE == RuntimeMode.DEMO
                        and proposal.proposed_revision.values.get("goal_type") == "appointment_booking"):
                    candidates.append(_candidate(
                        self.session_id, context, "IntentAuthorizationChanged", {
                            "revision_id": proposal.proposed_revision.revision_id,
                            "authorization": Authorization.AUTHORIZED.value,
                            "evidence_id": command.evidence_id,
                        }, identity=_identity(proposal.proposed_revision.revision_id, "authorization"),
                    ))
        return candidates

    async def _clarify(self, command: BaseCommand, context: DispatchContext) -> EventCandidate:
        """Turn a reducer clarification request into truth-gated output."""
        assert isinstance(command, RequestClarification)
        speech = SpeechAct(
            speech_id=_identity(command.control_id, context.origin_event_id or "", "clarification"),
            act_type=SpeechActType.CLARIFICATION,
            template_id="tmpl_clarification",
            slots={},
            claim_ids=[],
            requested_certainty=ClaimCertainty.PROGRESS,
            state=SpeechState.PROPOSED,
            created_by_event_id=context.origin_event_id or command.control_id,
        )
        return _candidate(
            self.session_id, context, "SpeechActProposed",
            {"speech_act": speech.model_dump(mode="json")},
            identity=speech.speech_id,
        )

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

    async def start_session(
        self,
        session_id: str,
        *,
        logical_time: int = 0,
        mode: RuntimeMode | str | None = None,
    ) -> SessionState:
        async with self._lifecycle_lock:
            if not session_id or session_id in self._sessions:
                raise ValueError("session identity must be new and nonempty")
            if len(self._sessions) >= self.max_sessions:
                raise RuntimeError("session capacity reached")
            try:
                session_mode = RuntimeMode(mode or self.settings.INTERLOCK_MODE)
            except ValueError as exc:
                raise ValueError("session mode is invalid") from exc
            if session_mode == RuntimeMode.REPLAY:
                raise ValueError("live sessions cannot start in REPLAY mode")
            session_settings = self.settings.model_copy(
                update={"INTERLOCK_MODE": session_mode.value}, deep=True
            )
            session = _Session(session_id, session_settings, self.registry, self.dependencies)
            self._sessions[session_id] = session
            try:
                event = await session.journal.append(EventCandidate(
                    session_id=session_id, event_type="SessionStarted", source=EventSource.SYSTEM,
                    payload={"mode": session_mode.value}, logical_time=logical_time,
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


_DEMO_SLOT_ALIASES = {
    "11": "2030-01-15T11:00:00+05:30",
    "11:00": "2030-01-15T11:00:00+05:30",
    "12": "2030-01-15T12:00:00+05:30",
    "12:00": "2030-01-15T12:00:00+05:30",
}


def _demo_root_booking(
    text: str, evidence_id: str, context: DispatchContext,
) -> tuple[dict[str, Any], IntentRevision] | None:
    """Recognize only the documented deterministic demo's root booking phrase."""
    normalized = " ".join(text.strip().lower().split())
    match = re.fullmatch(r"book\s+((?:11|12)(?::00)?)(?:\.)?", normalized)
    if match is None:
        return None
    slot = _DEMO_SLOT_ALIASES[match.group(1)]
    intent_id = _identity(context.origin_event_id or evidence_id, "appointment-intent")
    revision_id = _identity(context.origin_event_id or evidence_id, "appointment-revision")
    values = {
        "goal_type": "appointment_booking",
        "center_id": "ctr-01",
        "requested_slot": slot,
    }
    fingerprint = dependency_fingerprint(bind_dependencies(values, sorted(values)))
    revision = IntentRevision(
        revision_id=revision_id,
        intent_id=intent_id,
        values=values,
        maturity=IntentMaturity.COMMITTED,
        authorization=Authorization.NOT_REQUESTED,
        created_by_event_id=context.origin_event_id or evidence_id,
        dependency_fingerprint=fingerprint,
    )
    return ({
        "control_id": _identity(context.origin_event_id or evidence_id, "root-control"),
        "kind": ControlKind.ADD_GOAL.value,
        "confidence": 1.0,
        "consequential": True,
        "target_refs": [],
        "raw_evidence_id": evidence_id,
        "clarification": None,
    }, revision)


def _demo_input_context(
    state: SessionState, evidence: EvidenceRecord,
) -> dict[str, Any]:
    del state, evidence
    return {
        "correction_field": "requested_slot",
        "value_aliases": dict(_DEMO_SLOT_ALIASES),
    }


def _demo_bindings(
    state: SessionState, operation: OperationRecord,
) -> Mapping[str, Sequence[str]]:
    del state
    return {binding.path: tuple(binding.evidence_ids) for binding in operation.bindings}


class _DelayedDemoTransport:
    """SCRIPTED response delay after the SIMULATED provider has acted."""

    def __init__(self, delegate: ToolProviderTransport, delay_ms: int) -> None:
        self._delegate = delegate
        self._delay_s = delay_ms / 1000

    async def invoke(self, invocation: ToolInvocation) -> ProviderResponse:
        response = await self._delegate.invoke(invocation)
        if self._delay_s:
            await asyncio.sleep(self._delay_s)
        return response

    async def cancel(
        self, request: ProviderCancellationRequest,
    ) -> ProviderCancellationResult:
        return await self._delegate.cancel(request)


class DemoTextOutput(OutputPort):
    """Deterministic console sink for exact TRUTHLOCK-approved text.

    Completion records ``heard=False`` because console rendering is real output
    but is not audible output.  That distinction is exposed in projections.
    """

    def __init__(self) -> None:
        self._application: Application | None = None
        self._tasks: set[asyncio.Task[None]] = set()

    def bind(self, application: Application) -> None:
        if self._application is not None and self._application is not application:
            raise RuntimeError("demo output is already bound")
        self._application = application

    async def emit(
        self, *, session_id: str, speech_id: str, rendered_text: str,
    ) -> None:
        application = self._require_application()
        origins = [
            event.event_id for event in application.events(session_id)
            if event.event_type == "SpeechQueued"
            and event.payload.get("speech_id") == speech_id
        ]
        if not origins:
            raise OutputPortFailure("DEMO_OUTPUT_LINEAGE_MISSING", heard=False)
        # This line is the text adapter's actual output behavior.  JSON encoding
        # preserves the exact approved string without terminal-control ambiguity.
        print(json.dumps({
            "label": "REAL INTERLOCK / DEMO TEXT OUTPUT",
            "session_id": session_id,
            "speech_id": speech_id,
            "rendered_text": rendered_text,
        }, ensure_ascii=False), file=sys.stdout, flush=True)

        async def finish() -> None:
            await asyncio.sleep(0)
            await application.output_finished(
                session_id, speech_id, heard=False, logical_time=0,
                origin_event_id=origins[-1],
            )

        task = asyncio.create_task(finish(), name=f"demo-output:{speech_id}")
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def cancel(self, *, session_id: str, speech_id: str) -> None:
        # Console rendering is atomic.  The already scheduled terminal fact
        # records heard=False; reducer cancellation_pending decides whether the
        # lifecycle ends CANCELLED or EMITTED.
        return None

    async def shutdown(self) -> None:
        if self._tasks:
            await asyncio.gather(*tuple(self._tasks), return_exceptions=True)

    def _require_application(self) -> Application:
        if self._application is None:
            raise RuntimeError("demo output must be bound before use")
        return self._application


class _ASGIApplication(Protocol):
    async def __call__(
        self, scope: Mapping[str, Any],
        receive: Callable[[], Awaitable[dict[str, Any]]],
        send: Callable[[dict[str, Any]], Awaitable[None]],
    ) -> None: ...


class _DemoASGI:
    def __init__(
        self, http: _ASGIApplication, websocket: _ASGIApplication,
        application: Application, hub: Any, output: DemoTextOutput,
        provider: Any = None,
    ) -> None:
        self.http = http
        self.websocket = websocket
        self.application = application
        self.hub = hub
        self.output = output
        self.provider = provider

    async def __call__(self, scope: Mapping[str, Any], receive: Any, send: Any) -> None:
        if scope.get("type") == "websocket":
            await self.websocket(scope, receive, send)
            return
        if scope.get("type") != "lifespan":
            await self.http(scope, receive, send)
            return
        while True:
            message = await receive()
            if message["type"] == "lifespan.startup":
                await send({"type": "lifespan.startup.complete"})
            elif message["type"] == "lifespan.shutdown":
                await self.application.close()
                await self.output.shutdown()
                await self.hub.shutdown()
                await send({"type": "lifespan.shutdown.complete"})
                return


def create_demo_asgi_app(settings: Settings | None = None) -> _DemoASGI:
    """Compose the real runtime with SIMULATED provider and SCRIPTED delay."""
    from fastapi.middleware.cors import CORSMiddleware
    from interlock.adapters.http import create_http_app
    from interlock.adapters.websocket import ProjectionHub, WebSocketProjectionASGI
    from interlock.providers.fake_tools import create_fake_tool_transport
    from interlock.testing.fixtures import load_demo_fixture, register_tool_manifests

    effective = settings or Settings()
    if effective.INTERLOCK_MODE != RuntimeMode.DEMO:
        raise RuntimeError("the EXT-001 local ASGI host requires INTERLOCK_MODE=DEMO")
    fixture = load_demo_fixture()
    if fixture.fixture_id != "samsung-demo-v1":
        raise RuntimeError("unexpected demo fixture")
    registry = ToolRegistry(default_timeout_ms=effective.INTERLOCK_TOOL_TIMEOUT_MS)
    register_tool_manifests(registry)
    transport, provider = create_fake_tool_transport(fixture)
    output = DemoTextOutput()
    hub = ProjectionHub(max_sessions=128)
    dependencies = RuntimeDependencies(
        tool_transport=_DelayedDemoTransport(transport, effective.INTERLOCK_FAKE_LATENCY_MS),
        output=output,
        bindings=_demo_bindings,
        input_context=_demo_input_context,
        projection=hub.handle_publish,
    )
    application = Application(effective, registry=registry, dependencies=dependencies)
    output.bind(application)
    hub.bind(application)

    def _reset_demo_provider(fixture_id: str) -> None:
        if fixture_id != "samsung-demo-v1":
            raise ValueError(f"unexpected demo fixture '{fixture_id}'")
        provider.reset(load_demo_fixture())

    http = create_http_app(application, hub=hub, demo_reset_hook=_reset_demo_provider)
    cors = CORSMiddleware(
        http,
        allow_origins=effective.frontend_origins_list,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["content-type"],
    )
    return _DemoASGI(cors, WebSocketProjectionASGI(hub), application, hub, output, provider)


class _LazyDemoASGI:
    """Keep imports side-effect free while exposing ``interlock.main:app``."""

    def __init__(self) -> None:
        self._application: _DemoASGI | None = None
        self._lock: asyncio.Lock | None = None

    async def __call__(self, scope: Mapping[str, Any], receive: Any, send: Any) -> None:
        if self._application is None:
            if self._lock is None:
                self._lock = asyncio.Lock()
            async with self._lock:
                if self._application is None:
                    self._application = create_demo_asgi_app()
        await self._application(scope, receive, send)


app = _LazyDemoASGI()
