"""Pure deterministic state reducer for INTERLOCK.

Implements Reducer contract defined in:
- docs/contracts/INTERFACES.md
- docs/components/EVENT_JOURNAL_AND_REDUCER.md
- docs/architecture/EVENT_MODEL.md
- docs/architecture/STATE_MACHINES.md
- docs/architecture/DOMAIN_MODEL.md
- docs/architecture/INVARIANTS.md
"""

import hashlib
from typing import Any, Dict, List, Optional, Tuple

from interlock.domain.enums import (
    Authorization,
    BranchState,
    CancellationState,
    ClaimState,
    ControlKind,
    DivergenceState,
    EffectState,
    EvidenceAuthority,
    EvidenceSource,
    OperationState,
    PlanState,
    PlanStepState,
    RuntimeMode,
    SpeechState,
    ToolOutcome,
)
from interlock.domain.models import (
    BranchRecord,
    ClaimRecord,
    ControlIntent,
    DivergenceCase,
    EvidenceRecord,
    EventEnvelope,
    IntentNode,
    IntentRevision,
    MetricsSnapshot,
    OperationRecord,
    EffectRecord,
    ReconciliationPlan,
    SessionState,
    SpeechAct,
)
from interlock.runtime.commands import (
    BaseCommand,
    BuildReconciliationPlan,
    CancelSpeech,
    Command,
    DispatchTool,
    EmitOutput,
    InterpretInput,
    PrepareOperation,
    PublishProjection,
    QueueOutput,
    RecordProtocolViolation,
    RequestClarification,
    RequestToolCancellation,
    ValidateSpeech,
    VerifyOutcome,
)


class Reducer:
    """Pure, deterministic reducer for INTERLOCK session state.

    Authoritative writer of SessionState.
    Signature: reduce(state, envelope, mode) -> (new_state, commands).
    Zero external I/O, zero network, zero wall-clock dependencies.
    """

    @classmethod
    def reduce(
        cls,
        state: Optional[SessionState],
        envelope: EventEnvelope,
        mode: Optional[RuntimeMode] = None,
    ) -> Tuple[Optional[SessionState], List[Command]]:
        """Reduce an event envelope into next SessionState and emitted commands.

        Invariants enforced:
        - I11: Monotonic contiguous sequence numbering.
        - I12 / NFR-003: Replay mode (mode == RuntimeMode.REPLAY) suppresses ALL
          commands unconditionally across every return path.
        """
        effective_mode = (
            mode if mode is not None else (state.mode if state else RuntimeMode.DEMO)
        )

        next_state, cmds = cls._reduce_step(state, envelope)

        # Centralized invariant I12 / NFR-003: Replay discards every command across ALL paths
        if effective_mode == RuntimeMode.REPLAY:
            cmds = []

        return next_state, cmds

    @classmethod
    def _reduce_step(
        cls,
        state: Optional[SessionState],
        envelope: EventEnvelope,
    ) -> Tuple[Optional[SessionState], List[Command]]:
        """Internal deterministic reduction step without mode-based command suppression."""
        # 1. Basic Envelope Validation
        if envelope.schema_version != 1:
            sid = state.session_id if state else envelope.session_id
            return (
                state,
                [
                    RecordProtocolViolation(
                        session_id=sid,
                        boundary="reducer",
                        code="UNSUPPORTED_SCHEMA_VERSION",
                        digest=f"Envelope schema version {envelope.schema_version} unsupported",
                    )
                ],
            )

        # 2. Preconditions: Session Identity and Initialization
        is_uninitialized = (state is None) or (state.last_sequence == 0)

        if is_uninitialized:
            sid = state.session_id if state else envelope.session_id
            if envelope.event_type != "SessionStarted":
                return (
                    state,
                    [
                        RecordProtocolViolation(
                            session_id=sid,
                            boundary="reducer",
                            code="UNINITIALIZED_SESSION",
                            digest=f"Event '{envelope.event_type}' sequence {envelope.sequence} arrived before SessionStarted",
                        )
                    ],
                )
            if envelope.sequence != 1:
                return (
                    state,
                    [
                        RecordProtocolViolation(
                            session_id=sid,
                            boundary="reducer",
                            code="SEQUENCE_GAP",
                            digest=f"SessionStarted must have sequence 1, got {envelope.sequence}",
                        )
                    ],
                )
            # Create initial SessionState
            mode_val = envelope.payload.get("mode", RuntimeMode.DEMO)
            try:
                state_mode = RuntimeMode(mode_val)
            except ValueError:
                state_mode = RuntimeMode.DEMO

            # SessionState.mode represents canonical session runtime mode established by SessionStarted
            new_state = SessionState(
                session_id=envelope.session_id,
                last_sequence=1,
                mode=state_mode,
                intents={},
                active_intent_id=None,
                branches={},
                operations={},
                effects={},
                evidence={},
                claims={},
                divergences={},
                plans={},
                speech={},
                metrics=MetricsSnapshot(
                    session_id=envelope.session_id,
                    through_sequence=1,
                    counters={},
                    durations_ms={},
                    gauges={},
                ),
                schema_version=1,
            )
            commands: List[Command] = [
                PublishProjection(
                    session_id=envelope.session_id, sequence=1
                )
            ]
            return new_state, commands

        # State is already initialized
        if envelope.session_id != state.session_id:
            return (
                state,
                [
                    RecordProtocolViolation(
                        session_id=state.session_id,
                        boundary="reducer",
                        code="SESSION_MISMATCH",
                        digest=f"Envelope session '{envelope.session_id}' != state session '{state.session_id}'",
                    )
                ],
            )

        if envelope.event_type == "SessionStarted":
            return (
                state,
                [
                    RecordProtocolViolation(
                        session_id=state.session_id,
                        boundary="reducer",
                        code="SESSION_ALREADY_INITIALIZED",
                        digest=f"Session '{state.session_id}' is already initialized",
                    )
                ],
            )

        # Sequence must be strictly last_sequence + 1 (Invariant I11)
        if envelope.sequence != state.last_sequence + 1:
            code = (
                "SEQUENCE_REGRESSION"
                if envelope.sequence <= state.last_sequence
                else "SEQUENCE_GAP"
            )
            return (
                state,
                [
                    RecordProtocolViolation(
                        session_id=state.session_id,
                        boundary="reducer",
                        code=code,
                        digest=f"Expected sequence {state.last_sequence + 1}, got {envelope.sequence}",
                    )
                ],
            )

        # 3. Transition Handlers
        try:
            handler = _HANDLERS.get(envelope.event_type)
            if handler is None:
                return (
                    state,
                    [
                        RecordProtocolViolation(
                            session_id=state.session_id,
                            boundary="reducer",
                            code="UNKNOWN_EVENT_TYPE",
                            digest=f"No transition handler for event type: {envelope.event_type}",
                        )
                    ],
                )

            return handler(state, envelope)

        except Exception as e:
            return (
                state,
                [
                    RecordProtocolViolation(
                        session_id=state.session_id,
                        boundary="reducer",
                        code="REDUCER_TRANSITION_ERROR",
                        digest=str(e),
                    )
                ],
            )


# Global reduce function alias
reduce = Reducer.reduce


# --- Event Handlers ---


def _handle_user_input(
    state: SessionState, env: EventEnvelope
) -> Tuple[SessionState, List[Command]]:
    evidence_id = env.payload["evidence_id"]
    modality = env.payload["modality"]
    content_ref = env.payload["content_ref"]
    content_hash = env.payload.get("content_hash")
    if not content_hash:
        digest = hashlib.sha256(content_ref.encode("utf-8")).hexdigest()
        content_hash = f"sha256:{digest}"

    ev = EvidenceRecord(
        evidence_id=evidence_id,
        source=EvidenceSource.USER,
        kind=modality,
        captured_at=env.occurred_at,
        content_ref=content_ref,
        content_hash=content_hash,
        authority=EvidenceAuthority.AUTHORITATIVE,
        provenance={"event_id": env.event_id, "sequence": env.sequence},
    )
    new_evidence = {**state.evidence, evidence_id: ev}
    new_state = state.model_copy(
        update={
            "evidence": new_evidence,
            "last_sequence": env.sequence,
            "metrics": state.metrics.model_copy(
                update={"through_sequence": env.sequence}
            ),
        }
    )
    cmds: List[Command] = [
        InterpretInput(
            session_id=state.session_id,
            evidence_id=evidence_id,
            modality=modality,
            content_ref=content_ref,
        ),
        PublishProjection(session_id=state.session_id, sequence=env.sequence),
    ]
    return new_state, cmds


def _handle_transcript_hypothesis(
    state: SessionState, env: EventEnvelope
) -> Tuple[SessionState, List[Command]]:
    evidence_id = env.payload["evidence_id"]
    text = env.payload["text"]
    final = bool(env.payload.get("final", False))
    content_hash = env.payload.get("content_hash")
    if not content_hash:
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        content_hash = f"sha256:{digest}"

    ev = EvidenceRecord(
        evidence_id=evidence_id,
        source=EvidenceSource.AUDIO,
        kind="transcript",
        captured_at=env.occurred_at,
        content_ref=text,
        content_hash=content_hash,
        authority=EvidenceAuthority.AUTHORITATIVE
        if final
        else EvidenceAuthority.NON_AUTHORITATIVE,
        provenance={"event_id": env.event_id, "sequence": env.sequence, "final": final},
    )
    new_evidence = {**state.evidence, evidence_id: ev}
    new_state = state.model_copy(
        update={
            "evidence": new_evidence,
            "last_sequence": env.sequence,
            "metrics": state.metrics.model_copy(
                update={"through_sequence": env.sequence}
            ),
        }
    )
    cmds: List[Command] = [
        PublishProjection(session_id=state.session_id, sequence=env.sequence)
    ]
    return new_state, cmds


def _handle_control_intent(
    state: SessionState, env: EventEnvelope
) -> Tuple[SessionState, List[Command]]:
    ctrl_data = env.payload["control"]
    control = (
        ctrl_data
        if isinstance(ctrl_data, ControlIntent)
        else ControlIntent.model_validate(ctrl_data)
    )

    cmds: List[Command] = []
    # Canonical ControlKind.CLARIFY produces RequestClarification
    if control.kind == ControlKind.CLARIFY:
        cmds.append(
            RequestClarification(
                session_id=state.session_id,
                control_id=control.control_id,
                clarification=control.clarification,
            )
        )
    cmds.append(
        PublishProjection(session_id=state.session_id, sequence=env.sequence)
    )

    new_state = state.model_copy(
        update={
            "last_sequence": env.sequence,
            "metrics": state.metrics.model_copy(
                update={"through_sequence": env.sequence}
            ),
        }
    )
    return new_state, cmds


def _handle_intent_revision_proposed(
    state: SessionState, env: EventEnvelope
) -> Tuple[SessionState, List[Command]]:
    new_state = state.model_copy(
        update={
            "last_sequence": env.sequence,
            "metrics": state.metrics.model_copy(
                update={"through_sequence": env.sequence}
            ),
        }
    )
    cmds: List[Command] = [
        PublishProjection(session_id=state.session_id, sequence=env.sequence)
    ]
    return new_state, cmds


def _handle_intent_revision_committed(
    state: SessionState, env: EventEnvelope
) -> Tuple[SessionState, List[Command]]:
    rev_data = env.payload["revision"]
    rev = (
        rev_data
        if isinstance(rev_data, IntentRevision)
        else IntentRevision.model_validate(rev_data)
    )

    node = state.intents.get(rev.intent_id)
    if node is not None:
        new_revs = list(node.revisions)
        if rev.revision_id not in new_revs:
            new_revs.append(rev.revision_id)
        new_node = node.model_copy(
            update={"revisions": new_revs, "active_revision_id": rev.revision_id}
        )
    else:
        goal_type = str(rev.values.get("goal_type", "default"))
        new_node = IntentNode(
            intent_id=rev.intent_id,
            goal_type=goal_type,
            revisions=[rev.revision_id],
            active_revision_id=rev.revision_id,
        )

    new_intents = {**state.intents, rev.intent_id: new_node}
    new_state = state.model_copy(
        update={
            "intents": new_intents,
            "active_intent_id": rev.intent_id,
            "last_sequence": env.sequence,
            "metrics": state.metrics.model_copy(
                update={"through_sequence": env.sequence}
            ),
        }
    )
    cmds: List[Command] = [
        PublishProjection(session_id=state.session_id, sequence=env.sequence)
    ]
    return new_state, cmds


def _handle_intent_authorization_changed(
    state: SessionState, env: EventEnvelope
) -> Tuple[SessionState, List[Command]]:
    rev_id = env.payload["revision_id"]
    # Check that revision exists in one of the intent nodes
    found = any(rev_id in node.revisions for node in state.intents.values())
    if not found:
        return (
            state,
            [
                RecordProtocolViolation(
                    session_id=state.session_id,
                    boundary="reducer",
                    code="UNKNOWN_REVISION",
                    digest=f"Revision '{rev_id}' not found in any intent",
                )
            ],
        )

    new_state = state.model_copy(
        update={
            "last_sequence": env.sequence,
            "metrics": state.metrics.model_copy(
                update={"through_sequence": env.sequence}
            ),
        }
    )
    cmds: List[Command] = [
        PublishProjection(session_id=state.session_id, sequence=env.sequence)
    ]
    return new_state, cmds


def _handle_branch_predicted(
    state: SessionState, env: EventEnvelope
) -> Tuple[SessionState, List[Command]]:
    b_data = env.payload["branch"]
    branch = (
        b_data
        if isinstance(b_data, BranchRecord)
        else BranchRecord.model_validate(b_data)
    )
    new_branches = {**state.branches, branch.branch_id: branch}
    new_state = state.model_copy(
        update={
            "branches": new_branches,
            "last_sequence": env.sequence,
            "metrics": state.metrics.model_copy(
                update={"through_sequence": env.sequence}
            ),
        }
    )
    cmds: List[Command] = [
        PublishProjection(session_id=state.session_id, sequence=env.sequence)
    ]
    return new_state, cmds


def _handle_branch_prep_started(
    state: SessionState, env: EventEnvelope
) -> Tuple[SessionState, List[Command]]:
    bid = env.payload["branch_id"]
    if bid not in state.branches:
        return (
            state,
            [
                RecordProtocolViolation(
                    session_id=state.session_id,
                    boundary="reducer",
                    code="UNKNOWN_BRANCH",
                    digest=f"Branch '{bid}' not found",
                )
            ],
        )
    branch = state.branches[bid]
    if branch.state != BranchState.PREDICTED:
        return (
            state,
            [
                RecordProtocolViolation(
                    session_id=state.session_id,
                    boundary="reducer",
                    code="INVALID_BRANCH_TRANSITION",
                    digest=f"Branch '{bid}' is in state '{branch.state}', expected PREDICTED",
                )
            ],
        )

    new_branches = dict(state.branches)
    new_branches[bid] = branch.model_copy(update={"state": BranchState.PREPARING})
    new_state = state.model_copy(
        update={
            "branches": new_branches,
            "last_sequence": env.sequence,
            "metrics": state.metrics.model_copy(
                update={"through_sequence": env.sequence}
            ),
        }
    )
    cmds: List[Command] = [
        PublishProjection(session_id=state.session_id, sequence=env.sequence)
    ]
    return new_state, cmds


def _handle_branch_prep_completed(
    state: SessionState, env: EventEnvelope
) -> Tuple[SessionState, List[Command]]:
    bid = env.payload["branch_id"]
    if bid not in state.branches:
        return (
            state,
            [
                RecordProtocolViolation(
                    session_id=state.session_id,
                    boundary="reducer",
                    code="UNKNOWN_BRANCH",
                    digest=f"Branch '{bid}' not found",
                )
            ],
        )
    branch = state.branches[bid]
    if branch.state != BranchState.PREPARING:
        return (
            state,
            [
                RecordProtocolViolation(
                    session_id=state.session_id,
                    boundary="reducer",
                    code="INVALID_BRANCH_TRANSITION",
                    digest=f"Branch '{bid}' is in state '{branch.state}', expected PREPARING",
                )
            ],
        )

    new_branches = dict(state.branches)
    new_branches[bid] = branch.model_copy(update={"state": BranchState.READY})
    new_state = state.model_copy(
        update={
            "branches": new_branches,
            "last_sequence": env.sequence,
            "metrics": state.metrics.model_copy(
                update={"through_sequence": env.sequence}
            ),
        }
    )
    cmds: List[Command] = [
        PublishProjection(session_id=state.session_id, sequence=env.sequence)
    ]
    return new_state, cmds


def _handle_branch_promoted(
    state: SessionState, env: EventEnvelope
) -> Tuple[SessionState, List[Command]]:
    bid = env.payload["branch_id"]
    if bid not in state.branches:
        return (
            state,
            [
                RecordProtocolViolation(
                    session_id=state.session_id,
                    boundary="reducer",
                    code="UNKNOWN_BRANCH",
                    digest=f"Branch '{bid}' not found",
                )
            ],
        )
    branch = state.branches[bid]
    if branch.state != BranchState.READY:
        return (
            state,
            [
                RecordProtocolViolation(
                    session_id=state.session_id,
                    boundary="reducer",
                    code="INVALID_BRANCH_TRANSITION",
                    digest=f"Branch '{bid}' is in state '{branch.state}', expected READY",
                )
            ],
        )

    new_branches = dict(state.branches)
    new_branches[bid] = branch.model_copy(update={"state": BranchState.PROMOTED})
    new_state = state.model_copy(
        update={
            "branches": new_branches,
            "last_sequence": env.sequence,
            "metrics": state.metrics.model_copy(
                update={"through_sequence": env.sequence}
            ),
        }
    )
    cmds: List[Command] = [
        PublishProjection(session_id=state.session_id, sequence=env.sequence)
    ]
    return new_state, cmds


def _handle_branch_invalidated(
    state: SessionState, env: EventEnvelope
) -> Tuple[SessionState, List[Command]]:
    bid = env.payload["branch_id"]
    if bid not in state.branches:
        return (
            state,
            [
                RecordProtocolViolation(
                    session_id=state.session_id,
                    boundary="reducer",
                    code="UNKNOWN_BRANCH",
                    digest=f"Branch '{bid}' not found",
                )
            ],
        )
    branch = state.branches[bid]
    # Nonterminal -> INVALIDATED
    if branch.state in (
        BranchState.PROMOTED,
        BranchState.EXPIRED,
        BranchState.EVICTED,
        BranchState.INVALIDATED,
        BranchState.FAILED,
    ):
        return (
            state,
            [
                RecordProtocolViolation(
                    session_id=state.session_id,
                    boundary="reducer",
                    code="INVALID_BRANCH_TRANSITION",
                    digest=f"Cannot invalidate terminal branch '{bid}' ({branch.state})",
                )
            ],
        )

    new_branches = dict(state.branches)
    new_branches[bid] = branch.model_copy(update={"state": BranchState.INVALIDATED})
    new_state = state.model_copy(
        update={
            "branches": new_branches,
            "last_sequence": env.sequence,
            "metrics": state.metrics.model_copy(
                update={"through_sequence": env.sequence}
            ),
        }
    )
    cmds: List[Command] = [
        PublishProjection(session_id=state.session_id, sequence=env.sequence)
    ]
    return new_state, cmds


def _handle_operation_created(
    state: SessionState, env: EventEnvelope
) -> Tuple[SessionState, List[Command]]:
    op_data = env.payload["operation"]
    op = (
        op_data
        if isinstance(op_data, OperationRecord)
        else OperationRecord.model_validate(op_data)
    )
    new_ops = {**state.operations, op.operation_id: op}
    new_state = state.model_copy(
        update={
            "operations": new_ops,
            "last_sequence": env.sequence,
            "metrics": state.metrics.model_copy(
                update={"through_sequence": env.sequence}
            ),
        }
    )
    cmds: List[Command] = [
        PrepareOperation(session_id=state.session_id, operation_id=op.operation_id),
        PublishProjection(session_id=state.session_id, sequence=env.sequence),
    ]
    return new_state, cmds


def _handle_operation_prep_started(
    state: SessionState, env: EventEnvelope
) -> Tuple[SessionState, List[Command]]:
    op_id = env.payload["operation_id"]
    if op_id not in state.operations:
        return (
            state,
            [
                RecordProtocolViolation(
                    session_id=state.session_id,
                    boundary="reducer",
                    code="UNKNOWN_OPERATION",
                    digest=f"Operation '{op_id}' not found",
                )
            ],
        )
    op = state.operations[op_id]
    if op.state != OperationState.CREATED:
        return (
            state,
            [
                RecordProtocolViolation(
                    session_id=state.session_id,
                    boundary="reducer",
                    code="INVALID_OPERATION_TRANSITION",
                    digest=f"Operation '{op_id}' is in state '{op.state}', expected CREATED",
                )
            ],
        )

    new_ops = dict(state.operations)
    new_ops[op_id] = op.model_copy(update={"state": OperationState.PREPARING})
    new_state = state.model_copy(
        update={
            "operations": new_ops,
            "last_sequence": env.sequence,
            "metrics": state.metrics.model_copy(
                update={"through_sequence": env.sequence}
            ),
        }
    )
    cmds: List[Command] = [
        PublishProjection(session_id=state.session_id, sequence=env.sequence)
    ]
    return new_state, cmds


def _handle_operation_prepared(
    state: SessionState, env: EventEnvelope
) -> Tuple[SessionState, List[Command]]:
    op_id = env.payload["operation_id"]
    if op_id not in state.operations:
        return (
            state,
            [
                RecordProtocolViolation(
                    session_id=state.session_id,
                    boundary="reducer",
                    code="UNKNOWN_OPERATION",
                    digest=f"Operation '{op_id}' not found",
                )
            ],
        )
    op = state.operations[op_id]
    if op.state != OperationState.PREPARING:
        return (
            state,
            [
                RecordProtocolViolation(
                    session_id=state.session_id,
                    boundary="reducer",
                    code="INVALID_OPERATION_TRANSITION",
                    digest=f"Operation '{op_id}' is in state '{op.state}', expected PREPARING",
                )
            ],
        )

    new_ops = dict(state.operations)
    new_ops[op_id] = op.model_copy(update={"state": OperationState.READY})
    new_state = state.model_copy(
        update={
            "operations": new_ops,
            "last_sequence": env.sequence,
            "metrics": state.metrics.model_copy(
                update={"through_sequence": env.sequence}
            ),
        }
    )
    cmds: List[Command] = [
        PublishProjection(session_id=state.session_id, sequence=env.sequence)
    ]
    return new_state, cmds


def _handle_tool_dispatch_requested(
    state: SessionState, env: EventEnvelope
) -> Tuple[SessionState, List[Command]]:
    op_id = env.payload["operation_id"]
    if op_id not in state.operations:
        return (
            state,
            [
                RecordProtocolViolation(
                    session_id=state.session_id,
                    boundary="reducer",
                    code="UNKNOWN_OPERATION",
                    digest=f"Operation '{op_id}' not found for dispatch",
                )
            ],
        )
    op = state.operations[op_id]
    if op.state != OperationState.READY:
        return (
            state,
            [
                RecordProtocolViolation(
                    session_id=state.session_id,
                    boundary="reducer",
                    code="INVALID_OPERATION_TRANSITION",
                    digest=f"Operation '{op_id}' is in state '{op.state}', expected READY for dispatch",
                )
            ],
        )

    new_ops = dict(state.operations)
    new_ops[op_id] = op.model_copy(update={"state": OperationState.DISPATCHED})
    new_state = state.model_copy(
        update={
            "operations": new_ops,
            "last_sequence": env.sequence,
            "metrics": state.metrics.model_copy(
                update={"through_sequence": env.sequence}
            ),
        }
    )
    cmds: List[Command] = [
        DispatchTool(session_id=state.session_id, operation_id=op_id),
        PublishProjection(session_id=state.session_id, sequence=env.sequence),
    ]
    return new_state, cmds


def _handle_tool_dispatch_accepted(
    state: SessionState, env: EventEnvelope
) -> Tuple[SessionState, List[Command]]:
    op_id = env.payload["operation_id"]
    if op_id not in state.operations:
        return (
            state,
            [
                RecordProtocolViolation(
                    session_id=state.session_id,
                    boundary="reducer",
                    code="UNKNOWN_OPERATION",
                    digest=f"Operation '{op_id}' not found",
                )
            ],
        )
    op = state.operations[op_id]
    if op.state != OperationState.DISPATCHED:
        return (
            state,
            [
                RecordProtocolViolation(
                    session_id=state.session_id,
                    boundary="reducer",
                    code="INVALID_OPERATION_TRANSITION",
                    digest=f"Operation '{op_id}' is in state '{op.state}', expected DISPATCHED",
                )
            ],
        )

    provider_req_id = env.payload["provider_request_id"]
    new_ops = dict(state.operations)
    new_ops[op_id] = op.model_copy(
        update={
            "state": OperationState.WAITING,
            "provider_request_id": provider_req_id,
            "effect_state": EffectState.IN_FLIGHT,
        }
    )
    new_state = state.model_copy(
        update={
            "operations": new_ops,
            "last_sequence": env.sequence,
            "metrics": state.metrics.model_copy(
                update={"through_sequence": env.sequence}
            ),
        }
    )
    cmds: List[Command] = [
        PublishProjection(session_id=state.session_id, sequence=env.sequence)
    ]
    return new_state, cmds


def _handle_cancellation_requested(
    state: SessionState, env: EventEnvelope
) -> Tuple[SessionState, List[Command]]:
    op_id = env.payload["operation_id"]
    if op_id not in state.operations:
        return (
            state,
            [
                RecordProtocolViolation(
                    session_id=state.session_id,
                    boundary="reducer",
                    code="UNKNOWN_OPERATION",
                    digest=f"Operation '{op_id}' not found for cancellation",
                )
            ],
        )
    op = state.operations[op_id]
    if op.cancellation_state != CancellationState.NONE:
        return (
            state,
            [
                RecordProtocolViolation(
                    session_id=state.session_id,
                    boundary="reducer",
                    code="INVALID_CANCELLATION_TRANSITION",
                    digest=f"Operation '{op_id}' cancellation already in state '{op.cancellation_state}'",
                )
            ],
        )
    if op.state in (
        OperationState.SUCCEEDED,
        OperationState.FAILED,
        OperationState.CANCELLED,
        OperationState.SUPERSEDED,
    ):
        return (
            state,
            [
                RecordProtocolViolation(
                    session_id=state.session_id,
                    boundary="reducer",
                    code="INVALID_OPERATION_TRANSITION",
                    digest=f"Cannot cancel terminal operation '{op_id}' ({op.state})",
                )
            ],
        )

    reason = env.payload.get("reason")
    new_ops = dict(state.operations)
    new_ops[op_id] = op.model_copy(
        update={"cancellation_state": CancellationState.REQUESTED}
    )
    new_state = state.model_copy(
        update={
            "operations": new_ops,
            "last_sequence": env.sequence,
            "metrics": state.metrics.model_copy(
                update={"through_sequence": env.sequence}
            ),
        }
    )
    cmds: List[Command] = [
        RequestToolCancellation(
            session_id=state.session_id, operation_id=op_id, reason=reason
        ),
        PublishProjection(session_id=state.session_id, sequence=env.sequence),
    ]
    return new_state, cmds


def _handle_cancellation_acknowledged(
    state: SessionState, env: EventEnvelope
) -> Tuple[SessionState, List[Command]]:
    op_id = env.payload["operation_id"]
    if op_id not in state.operations:
        return (
            state,
            [
                RecordProtocolViolation(
                    session_id=state.session_id,
                    boundary="reducer",
                    code="UNKNOWN_OPERATION",
                    digest=f"Operation '{op_id}' not found",
                )
            ],
        )
    op = state.operations[op_id]
    if op.cancellation_state != CancellationState.REQUESTED:
        return (
            state,
            [
                RecordProtocolViolation(
                    session_id=state.session_id,
                    boundary="reducer",
                    code="INVALID_CANCELLATION_TRANSITION",
                    digest=f"Cancellation must be REQUESTED before ACKNOWLEDGED, got {op.cancellation_state}",
                )
            ],
        )

    new_ops = dict(state.operations)
    upd: Dict[str, Any] = {"cancellation_state": CancellationState.ACKNOWLEDGED}
    if op.state in (
        OperationState.CREATED,
        OperationState.PREPARING,
        OperationState.READY,
        OperationState.DISPATCHED,
        OperationState.WAITING,
    ):
        upd["state"] = OperationState.CANCELLED
    new_ops[op_id] = op.model_copy(update=upd)
    new_state = state.model_copy(
        update={
            "operations": new_ops,
            "last_sequence": env.sequence,
            "metrics": state.metrics.model_copy(
                update={"through_sequence": env.sequence}
            ),
        }
    )
    cmds: List[Command] = [
        PublishProjection(session_id=state.session_id, sequence=env.sequence)
    ]
    return new_state, cmds


def _handle_safepoint_reached(
    state: SessionState, env: EventEnvelope
) -> Tuple[SessionState, List[Command]]:
    op_id = env.payload["operation_id"]
    if op_id not in state.operations:
        return (
            state,
            [
                RecordProtocolViolation(
                    session_id=state.session_id,
                    boundary="reducer",
                    code="UNKNOWN_OPERATION",
                    digest=f"Operation '{op_id}' not found",
                )
            ],
        )

    new_state = state.model_copy(
        update={
            "last_sequence": env.sequence,
            "metrics": state.metrics.model_copy(
                update={"through_sequence": env.sequence}
            ),
        }
    )
    cmds: List[Command] = [
        PublishProjection(session_id=state.session_id, sequence=env.sequence)
    ]
    return new_state, cmds


def _handle_tool_result_observed(
    state: SessionState, env: EventEnvelope
) -> Tuple[SessionState, List[Command]]:
    op_id = env.payload["operation_id"]
    if op_id not in state.operations:
        return (
            state,
            [
                RecordProtocolViolation(
                    session_id=state.session_id,
                    boundary="reducer",
                    code="UNKNOWN_OPERATION",
                    digest=f"Operation '{op_id}' not found",
                )
            ],
        )

    outcome = ToolOutcome(env.payload["outcome"])
    new_ops = dict(state.operations)
    op = new_ops[op_id]
    upd: Dict[str, Any] = {}

    # Stale results can update effect dimension, not reactivate operation
    if op.state in (OperationState.DISPATCHED, OperationState.WAITING):
        if outcome == ToolOutcome.SUCCEEDED:
            upd["state"] = OperationState.SUCCEEDED
            upd["effect_state"] = EffectState.COMMITTED
        elif outcome == ToolOutcome.FAILED:
            upd["state"] = OperationState.FAILED
            upd["effect_state"] = EffectState.FAILED
        elif outcome == ToolOutcome.UNKNOWN:
            upd["effect_state"] = EffectState.OUTCOME_UNKNOWN
    elif op.state in (OperationState.CANCELLED, OperationState.SUPERSEDED):
        if outcome == ToolOutcome.SUCCEEDED:
            upd["effect_state"] = EffectState.COMMITTED

    if env.payload.get("provider_request_id"):
        upd["provider_request_id"] = env.payload["provider_request_id"]

    new_ops[op_id] = op.model_copy(update=upd)
    new_state = state.model_copy(
        update={
            "operations": new_ops,
            "last_sequence": env.sequence,
            "metrics": state.metrics.model_copy(
                update={"through_sequence": env.sequence}
            ),
        }
    )
    cmds: List[Command] = [
        PublishProjection(session_id=state.session_id, sequence=env.sequence)
    ]
    return new_state, cmds


def _handle_tool_timed_out(
    state: SessionState, env: EventEnvelope
) -> Tuple[SessionState, List[Command]]:
    op_id = env.payload["operation_id"]
    if op_id not in state.operations:
        return (
            state,
            [
                RecordProtocolViolation(
                    session_id=state.session_id,
                    boundary="reducer",
                    code="UNKNOWN_OPERATION",
                    digest=f"Operation '{op_id}' not found",
                )
            ],
        )
    op = state.operations[op_id]
    if op.state not in (OperationState.DISPATCHED, OperationState.WAITING):
        return (
            state,
            [
                RecordProtocolViolation(
                    session_id=state.session_id,
                    boundary="reducer",
                    code="INVALID_OPERATION_TRANSITION",
                    digest=f"Operation '{op_id}' is in state '{op.state}', expected DISPATCHED or WAITING for timeout",
                )
            ],
        )

    after_dispatch = bool(env.payload.get("after_dispatch", False))
    new_ops = dict(state.operations)
    upd: Dict[str, Any] = {"state": OperationState.TIMED_OUT}
    if after_dispatch:
        upd["effect_state"] = EffectState.OUTCOME_UNKNOWN
    new_ops[op_id] = op.model_copy(update=upd)

    new_state = state.model_copy(
        update={
            "operations": new_ops,
            "last_sequence": env.sequence,
            "metrics": state.metrics.model_copy(
                update={"through_sequence": env.sequence}
            ),
        }
    )
    cmds: List[Command] = []
    if after_dispatch:
        cmds.append(
            VerifyOutcome(session_id=state.session_id, operation_id=op_id)
        )
    cmds.append(
        PublishProjection(session_id=state.session_id, sequence=env.sequence)
    )
    return new_state, cmds


def _handle_world_effect_observed(
    state: SessionState, env: EventEnvelope
) -> Tuple[SessionState, List[Command]]:
    eff_data = env.payload["effect"]
    effect = (
        eff_data
        if isinstance(eff_data, EffectRecord)
        else EffectRecord.model_validate(eff_data)
    )
    new_effects = {**state.effects, effect.effect_id: effect}
    new_state = state.model_copy(
        update={
            "effects": new_effects,
            "last_sequence": env.sequence,
            "metrics": state.metrics.model_copy(
                update={"through_sequence": env.sequence}
            ),
        }
    )
    cmds: List[Command] = [
        PublishProjection(session_id=state.session_id, sequence=env.sequence)
    ]
    return new_state, cmds


def _handle_evidence_recorded(
    state: SessionState, env: EventEnvelope
) -> Tuple[SessionState, List[Command]]:
    ev_data = env.payload["evidence"]
    ev = (
        ev_data
        if isinstance(ev_data, EvidenceRecord)
        else EvidenceRecord.model_validate(ev_data)
    )

    # Invariant I8: EvidenceRecord is immutable
    if ev.evidence_id in state.evidence:
        existing = state.evidence[ev.evidence_id]
        if (
            existing.content_hash != ev.content_hash
            or existing.content_ref != ev.content_ref
        ):
            return (
                state,
                [
                    RecordProtocolViolation(
                        session_id=state.session_id,
                        boundary="reducer",
                        code="IMMUTABLE_EVIDENCE_VIOLATION",
                        digest=f"Evidence '{ev.evidence_id}' already exists with different content",
                    )
                ],
            )

    new_evidence = {**state.evidence, ev.evidence_id: ev}
    new_state = state.model_copy(
        update={
            "evidence": new_evidence,
            "last_sequence": env.sequence,
            "metrics": state.metrics.model_copy(
                update={"through_sequence": env.sequence}
            ),
        }
    )
    cmds: List[Command] = [
        PublishProjection(session_id=state.session_id, sequence=env.sequence)
    ]
    return new_state, cmds


def _handle_claim_proposed(
    state: SessionState, env: EventEnvelope
) -> Tuple[SessionState, List[Command]]:
    cl_data = env.payload["claim"]
    claim = (
        cl_data
        if isinstance(cl_data, ClaimRecord)
        else ClaimRecord.model_validate(cl_data)
    )
    new_claims = {**state.claims, claim.claim_id: claim}
    new_state = state.model_copy(
        update={
            "claims": new_claims,
            "last_sequence": env.sequence,
            "metrics": state.metrics.model_copy(
                update={"through_sequence": env.sequence}
            ),
        }
    )
    cmds: List[Command] = [
        PublishProjection(session_id=state.session_id, sequence=env.sequence)
    ]
    return new_state, cmds


def _handle_claim_state_changed(
    state: SessionState, env: EventEnvelope
) -> Tuple[SessionState, List[Command]]:
    cid = env.payload["claim_id"]
    if cid not in state.claims:
        return (
            state,
            [
                RecordProtocolViolation(
                    session_id=state.session_id,
                    boundary="reducer",
                    code="UNKNOWN_CLAIM",
                    digest=f"Claim '{cid}' not found",
                )
            ],
        )

    claim = state.claims[cid]
    target_state = ClaimState(env.payload["to_state"])

    # Enforce optional from_state guard
    if "from_state" in env.payload and claim.state.value != env.payload["from_state"]:
        return (
            state,
            [
                RecordProtocolViolation(
                    session_id=state.session_id,
                    boundary="reducer",
                    code="INVALID_CLAIM_TRANSITION",
                    digest=f"Claim '{cid}' from_state mismatch: actual {claim.state.value} != expected {env.payload['from_state']}",
                )
            ],
        )

    # Enforce STATE_MACHINES.md transition table for Claim
    legal_claim_transitions = {
        ClaimState.PROPOSED: {
            ClaimState.PENDING,
            ClaimState.CONFIRMED,
            ClaimState.CONTRADICTED,
            ClaimState.UNCERTAIN,
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
        ClaimState.CONFIRMED: {ClaimState.STALE, ClaimState.SUPERSEDED},
        ClaimState.CONTRADICTED: {ClaimState.STALE, ClaimState.SUPERSEDED},
        ClaimState.STALE: {ClaimState.SUPERSEDED},
        ClaimState.SUPERSEDED: set(),
    }

    if target_state not in legal_claim_transitions.get(claim.state, set()):
        return (
            state,
            [
                RecordProtocolViolation(
                    session_id=state.session_id,
                    boundary="reducer",
                    code="INVALID_CLAIM_TRANSITION",
                    digest=f"Cannot transition claim '{cid}' from {claim.state} to {target_state}",
                )
            ],
        )

    new_claims = dict(state.claims)
    new_claims[cid] = claim.model_copy(
        update={
            "state": target_state,
            "supporting_evidence_ids": env.payload.get(
                "evidence_ids", claim.supporting_evidence_ids
            ),
        }
    )
    new_state = state.model_copy(
        update={
            "claims": new_claims,
            "last_sequence": env.sequence,
            "metrics": state.metrics.model_copy(
                update={"through_sequence": env.sequence}
            ),
        }
    )
    cmds: List[Command] = [
        PublishProjection(session_id=state.session_id, sequence=env.sequence)
    ]
    return new_state, cmds


def _handle_speech_act_proposed(
    state: SessionState, env: EventEnvelope
) -> Tuple[SessionState, List[Command]]:
    sp_data = env.payload["speech_act"]
    speech = (
        sp_data
        if isinstance(sp_data, SpeechAct)
        else SpeechAct.model_validate(sp_data)
    )
    new_speech = {**state.speech, speech.speech_id: speech}
    new_state = state.model_copy(
        update={
            "speech": new_speech,
            "last_sequence": env.sequence,
            "metrics": state.metrics.model_copy(
                update={"through_sequence": env.sequence}
            ),
        }
    )
    cmds: List[Command] = [
        ValidateSpeech(session_id=state.session_id, speech_id=speech.speech_id),
        PublishProjection(session_id=state.session_id, sequence=env.sequence),
    ]
    return new_state, cmds


def _handle_speech_act_approved(
    state: SessionState, env: EventEnvelope
) -> Tuple[SessionState, List[Command]]:
    sp_id = env.payload["speech_id"]
    if sp_id not in state.speech:
        return (
            state,
            [
                RecordProtocolViolation(
                    session_id=state.session_id,
                    boundary="reducer",
                    code="UNKNOWN_SPEECH",
                    digest=f"Speech '{sp_id}' not found",
                )
            ],
        )
    speech = state.speech[sp_id]
    if speech.state != SpeechState.PROPOSED:
        return (
            state,
            [
                RecordProtocolViolation(
                    session_id=state.session_id,
                    boundary="reducer",
                    code="INVALID_SPEECH_TRANSITION",
                    digest=f"Speech '{sp_id}' is in state '{speech.state}', expected PROPOSED",
                )
            ],
        )

    new_speech = dict(state.speech)
    new_speech[sp_id] = speech.model_copy(update={"state": SpeechState.APPROVED})
    new_state = state.model_copy(
        update={
            "speech": new_speech,
            "last_sequence": env.sequence,
            "metrics": state.metrics.model_copy(
                update={"through_sequence": env.sequence}
            ),
        }
    )
    cmds: List[Command] = [
        QueueOutput(
            session_id=state.session_id,
            speech_id=sp_id,
            rendered_text=env.payload["rendered_text"],
            policy_id=env.payload["policy_id"],
        ),
        PublishProjection(session_id=state.session_id, sequence=env.sequence),
    ]
    return new_state, cmds


def _handle_speech_act_blocked(
    state: SessionState, env: EventEnvelope
) -> Tuple[SessionState, List[Command]]:
    sp_id = env.payload["speech_id"]
    if sp_id not in state.speech:
        return (
            state,
            [
                RecordProtocolViolation(
                    session_id=state.session_id,
                    boundary="reducer",
                    code="UNKNOWN_SPEECH",
                    digest=f"Speech '{sp_id}' not found",
                )
            ],
        )
    speech = state.speech[sp_id]
    if speech.state != SpeechState.PROPOSED:
        return (
            state,
            [
                RecordProtocolViolation(
                    session_id=state.session_id,
                    boundary="reducer",
                    code="INVALID_SPEECH_TRANSITION",
                    digest=f"Speech '{sp_id}' is in state '{speech.state}', expected PROPOSED",
                )
            ],
        )

    new_speech = dict(state.speech)
    new_speech[sp_id] = speech.model_copy(update={"state": SpeechState.BLOCKED})
    new_state = state.model_copy(
        update={
            "speech": new_speech,
            "last_sequence": env.sequence,
            "metrics": state.metrics.model_copy(
                update={"through_sequence": env.sequence}
            ),
        }
    )
    cmds: List[Command] = [
        PublishProjection(session_id=state.session_id, sequence=env.sequence)
    ]
    return new_state, cmds


def _handle_speech_queued(
    state: SessionState, env: EventEnvelope
) -> Tuple[SessionState, List[Command]]:
    sp_id = env.payload["speech_id"]
    if sp_id not in state.speech:
        return (
            state,
            [
                RecordProtocolViolation(
                    session_id=state.session_id,
                    boundary="reducer",
                    code="UNKNOWN_SPEECH",
                    digest=f"Speech '{sp_id}' not found",
                )
            ],
        )
    speech = state.speech[sp_id]
    if speech.state != SpeechState.APPROVED:
        return (
            state,
            [
                RecordProtocolViolation(
                    session_id=state.session_id,
                    boundary="reducer",
                    code="INVALID_SPEECH_TRANSITION",
                    digest=f"Speech '{sp_id}' is in state '{speech.state}', expected APPROVED",
                )
            ],
        )

    new_speech = dict(state.speech)
    new_speech[sp_id] = speech.model_copy(update={"state": SpeechState.QUEUED})
    new_state = state.model_copy(
        update={
            "speech": new_speech,
            "last_sequence": env.sequence,
            "metrics": state.metrics.model_copy(
                update={"through_sequence": env.sequence}
            ),
        }
    )
    cmds: List[Command] = [
        EmitOutput(session_id=state.session_id, speech_id=sp_id),
        PublishProjection(session_id=state.session_id, sequence=env.sequence),
    ]
    return new_state, cmds


def _handle_speech_emission_started(
    state: SessionState, env: EventEnvelope
) -> Tuple[SessionState, List[Command]]:
    sp_id = env.payload["speech_id"]
    if sp_id not in state.speech:
        return (
            state,
            [
                RecordProtocolViolation(
                    session_id=state.session_id,
                    boundary="reducer",
                    code="UNKNOWN_SPEECH",
                    digest=f"Speech '{sp_id}' not found",
                )
            ],
        )
    speech = state.speech[sp_id]
    if speech.state != SpeechState.QUEUED:
        return (
            state,
            [
                RecordProtocolViolation(
                    session_id=state.session_id,
                    boundary="reducer",
                    code="INVALID_SPEECH_TRANSITION",
                    digest=f"Speech '{sp_id}' is in state '{speech.state}', expected QUEUED",
                )
            ],
        )

    new_speech = dict(state.speech)
    new_speech[sp_id] = speech.model_copy(update={"state": SpeechState.EMITTING})
    new_state = state.model_copy(
        update={
            "speech": new_speech,
            "last_sequence": env.sequence,
            "metrics": state.metrics.model_copy(
                update={"through_sequence": env.sequence}
            ),
        }
    )
    cmds: List[Command] = [
        PublishProjection(session_id=state.session_id, sequence=env.sequence)
    ]
    return new_state, cmds


def _handle_speech_emission_finished(
    state: SessionState, env: EventEnvelope
) -> Tuple[SessionState, List[Command]]:
    sp_id = env.payload["speech_id"]
    if sp_id not in state.speech:
        return (
            state,
            [
                RecordProtocolViolation(
                    session_id=state.session_id,
                    boundary="reducer",
                    code="UNKNOWN_SPEECH",
                    digest=f"Speech '{sp_id}' not found",
                )
            ],
        )
    speech = state.speech[sp_id]
    if speech.state != SpeechState.EMITTING:
        return (
            state,
            [
                RecordProtocolViolation(
                    session_id=state.session_id,
                    boundary="reducer",
                    code="INVALID_SPEECH_TRANSITION",
                    digest=f"Speech '{sp_id}' is in state '{speech.state}', expected EMITTING",
                )
            ],
        )

    new_speech = dict(state.speech)
    new_speech[sp_id] = speech.model_copy(update={"state": SpeechState.EMITTED})
    new_state = state.model_copy(
        update={
            "speech": new_speech,
            "last_sequence": env.sequence,
            "metrics": state.metrics.model_copy(
                update={"through_sequence": env.sequence}
            ),
        }
    )
    cmds: List[Command] = [
        PublishProjection(session_id=state.session_id, sequence=env.sequence)
    ]
    return new_state, cmds


def _handle_speech_cancellation_requested(
    state: SessionState, env: EventEnvelope
) -> Tuple[SessionState, List[Command]]:
    sp_id = env.payload["speech_id"]
    if sp_id not in state.speech:
        return (
            state,
            [
                RecordProtocolViolation(
                    session_id=state.session_id,
                    boundary="reducer",
                    code="UNKNOWN_SPEECH",
                    digest=f"Speech '{sp_id}' not found",
                )
            ],
        )
    speech = state.speech[sp_id]
    if speech.state in (
        SpeechState.EMITTED,
        SpeechState.CANCELLED,
        SpeechState.BLOCKED,
    ):
        return (
            state,
            [
                RecordProtocolViolation(
                    session_id=state.session_id,
                    boundary="reducer",
                    code="INVALID_SPEECH_TRANSITION",
                    digest=f"Cannot cancel terminal speech '{sp_id}' ({speech.state})",
                )
            ],
        )

    new_speech = dict(state.speech)
    new_speech[sp_id] = speech.model_copy(update={"state": SpeechState.CANCELLED})
    new_state = state.model_copy(
        update={
            "speech": new_speech,
            "last_sequence": env.sequence,
            "metrics": state.metrics.model_copy(
                update={"through_sequence": env.sequence}
            ),
        }
    )
    cmds: List[Command] = [
        CancelSpeech(session_id=state.session_id, speech_id=sp_id),
        PublishProjection(session_id=state.session_id, sequence=env.sequence),
    ]
    return new_state, cmds


def _handle_divergence_detected(
    state: SessionState, env: EventEnvelope
) -> Tuple[SessionState, List[Command]]:
    div_data = env.payload["case"]
    case = (
        div_data
        if isinstance(div_data, DivergenceCase)
        else DivergenceCase.model_validate(div_data)
    )
    new_divs = {**state.divergences, case.divergence_id: case}
    new_state = state.model_copy(
        update={
            "divergences": new_divs,
            "last_sequence": env.sequence,
            "metrics": state.metrics.model_copy(
                update={"through_sequence": env.sequence}
            ),
        }
    )
    cmds: List[Command] = [
        BuildReconciliationPlan(
            session_id=state.session_id, divergence_id=case.divergence_id
        ),
        PublishProjection(session_id=state.session_id, sequence=env.sequence),
    ]
    return new_state, cmds


def _handle_reconciliation_planned(
    state: SessionState, env: EventEnvelope
) -> Tuple[SessionState, List[Command]]:
    plan_data = env.payload["plan"]
    plan = (
        plan_data
        if isinstance(plan_data, ReconciliationPlan)
        else ReconciliationPlan.model_validate(plan_data)
    )
    if plan.divergence_id not in state.divergences:
        return (
            state,
            [
                RecordProtocolViolation(
                    session_id=state.session_id,
                    boundary="reducer",
                    code="UNKNOWN_DIVERGENCE",
                    digest=f"Divergence '{plan.divergence_id}' not found for plan",
                )
            ],
        )

    div = state.divergences[plan.divergence_id]
    if div.state != DivergenceState.OPEN:
        return (
            state,
            [
                RecordProtocolViolation(
                    session_id=state.session_id,
                    boundary="reducer",
                    code="INVALID_DIVERGENCE_TRANSITION",
                    digest=f"Divergence '{plan.divergence_id}' is in state '{div.state}', expected OPEN",
                )
            ],
        )

    new_plans = {**state.plans, plan.plan_id: plan}
    new_divs = dict(state.divergences)
    new_divs[plan.divergence_id] = div.model_copy(
        update={"state": DivergenceState.PLANNED}
    )
    new_state = state.model_copy(
        update={
            "plans": new_plans,
            "divergences": new_divs,
            "last_sequence": env.sequence,
            "metrics": state.metrics.model_copy(
                update={"through_sequence": env.sequence}
            ),
        }
    )
    cmds: List[Command] = [
        PublishProjection(session_id=state.session_id, sequence=env.sequence)
    ]
    return new_state, cmds


def _handle_reconciliation_authorized(
    state: SessionState, env: EventEnvelope
) -> Tuple[SessionState, List[Command]]:
    pid = env.payload["plan_id"]
    if pid not in state.plans:
        return (
            state,
            [
                RecordProtocolViolation(
                    session_id=state.session_id,
                    boundary="reducer",
                    code="UNKNOWN_PLAN",
                    digest=f"Plan '{pid}' not found",
                )
            ],
        )
    plan = state.plans[pid]
    if plan.state != PlanState.DRAFT:
        return (
            state,
            [
                RecordProtocolViolation(
                    session_id=state.session_id,
                    boundary="reducer",
                    code="INVALID_PLAN_TRANSITION",
                    digest=f"Plan '{pid}' is in state '{plan.state}', expected DRAFT",
                )
            ],
        )

    did = plan.divergence_id
    if did not in state.divergences:
        return (
            state,
            [
                RecordProtocolViolation(
                    session_id=state.session_id,
                    boundary="reducer",
                    code="UNKNOWN_DIVERGENCE",
                    digest=f"Associated divergence '{did}' not found for plan '{pid}'",
                )
            ],
        )
    div = state.divergences[did]
    if div.state != DivergenceState.PLANNED:
        return (
            state,
            [
                RecordProtocolViolation(
                    session_id=state.session_id,
                    boundary="reducer",
                    code="INVALID_DIVERGENCE_TRANSITION",
                    digest=f"Associated divergence '{did}' is in state '{div.state}', expected PLANNED",
                )
            ],
        )

    new_plans = dict(state.plans)
    new_plans[pid] = plan.model_copy(
        update={
            "state": PlanState.AUTHORIZED,
            "authorized_by_evidence_id": env.payload.get("evidence_id"),
        }
    )
    new_divs = dict(state.divergences)
    new_divs[did] = div.model_copy(update={"state": DivergenceState.RECONCILING})
    new_state = state.model_copy(
        update={
            "plans": new_plans,
            "divergences": new_divs,
            "last_sequence": env.sequence,
            "metrics": state.metrics.model_copy(
                update={"through_sequence": env.sequence}
            ),
        }
    )
    cmds: List[Command] = [
        PublishProjection(session_id=state.session_id, sequence=env.sequence)
    ]
    return new_state, cmds


def _handle_reconciliation_denied(
    state: SessionState, env: EventEnvelope
) -> Tuple[SessionState, List[Command]]:
    pid = env.payload["plan_id"]
    if pid not in state.plans:
        return (
            state,
            [
                RecordProtocolViolation(
                    session_id=state.session_id,
                    boundary="reducer",
                    code="UNKNOWN_PLAN",
                    digest=f"Plan '{pid}' not found",
                )
            ],
        )
    plan = state.plans[pid]
    if plan.state != PlanState.DRAFT:
        return (
            state,
            [
                RecordProtocolViolation(
                    session_id=state.session_id,
                    boundary="reducer",
                    code="INVALID_PLAN_TRANSITION",
                    digest=f"Plan '{pid}' is in state '{plan.state}', expected DRAFT",
                )
            ],
        )

    new_plans = dict(state.plans)
    new_divs = dict(state.divergences)
    failed_plan = plan.model_copy(update={"state": PlanState.FAILED})
    new_plans[pid] = failed_plan
    if plan.divergence_id in new_divs:
        new_divs[plan.divergence_id] = new_divs[plan.divergence_id].model_copy(
            update={"state": DivergenceState.ESCALATED}
        )
    new_state = state.model_copy(
        update={
            "plans": new_plans,
            "divergences": new_divs,
            "last_sequence": env.sequence,
            "metrics": state.metrics.model_copy(
                update={"through_sequence": env.sequence}
            ),
        }
    )
    cmds: List[Command] = [
        PublishProjection(session_id=state.session_id, sequence=env.sequence)
    ]
    return new_state, cmds


def _handle_reconciliation_step_changed(
    state: SessionState, env: EventEnvelope
) -> Tuple[SessionState, List[Command]]:
    pid = env.payload["plan_id"]
    sid = env.payload["step_id"]
    if pid not in state.plans:
        return (
            state,
            [
                RecordProtocolViolation(
                    session_id=state.session_id,
                    boundary="reducer",
                    code="UNKNOWN_PLAN",
                    digest=f"Plan '{pid}' not found",
                )
            ],
        )
    plan = state.plans[pid]
    target_state = PlanStepState(env.payload["state"])

    step_found = any(s.step_id == sid for s in plan.steps)
    if not step_found:
        return (
            state,
            [
                RecordProtocolViolation(
                    session_id=state.session_id,
                    boundary="reducer",
                    code="UNKNOWN_PLAN_STEP",
                    digest=f"Step '{sid}' not found in plan '{pid}'",
                )
            ],
        )

    new_plans = dict(state.plans)
    new_steps = [
        s.model_copy(update={"state": target_state})
        if s.step_id == sid
        else s
        for s in plan.steps
    ]
    plan_upd: Dict[str, Any] = {"steps": new_steps}
    if target_state == PlanStepState.RUNNING and plan.state == PlanState.AUTHORIZED:
        plan_upd["state"] = PlanState.RUNNING
    new_plans[pid] = plan.model_copy(update=plan_upd)

    new_state = state.model_copy(
        update={
            "plans": new_plans,
            "last_sequence": env.sequence,
            "metrics": state.metrics.model_copy(
                update={"through_sequence": env.sequence}
            ),
        }
    )
    cmds: List[Command] = [
        PublishProjection(session_id=state.session_id, sequence=env.sequence)
    ]
    return new_state, cmds


def _handle_divergence_resolved(
    state: SessionState, env: EventEnvelope
) -> Tuple[SessionState, List[Command]]:
    did = env.payload["divergence_id"]
    if did not in state.divergences:
        return (
            state,
            [
                RecordProtocolViolation(
                    session_id=state.session_id,
                    boundary="reducer",
                    code="UNKNOWN_DIVERGENCE",
                    digest=f"Divergence '{did}' not found",
                )
            ],
        )
    div = state.divergences[did]
    if div.state != DivergenceState.RECONCILING:
        return (
            state,
            [
                RecordProtocolViolation(
                    session_id=state.session_id,
                    boundary="reducer",
                    code="INVALID_DIVERGENCE_TRANSITION",
                    digest=f"Divergence '{did}' in state '{div.state}', expected RECONCILING",
                )
            ],
        )

    new_divs = dict(state.divergences)
    new_divs[did] = div.model_copy(update={"state": DivergenceState.RESOLVED})
    new_state = state.model_copy(
        update={
            "divergences": new_divs,
            "last_sequence": env.sequence,
            "metrics": state.metrics.model_copy(
                update={"through_sequence": env.sequence}
            ),
        }
    )
    cmds: List[Command] = [
        PublishProjection(session_id=state.session_id, sequence=env.sequence)
    ]
    return new_state, cmds


def _handle_fault_activated(
    state: SessionState, env: EventEnvelope
) -> Tuple[SessionState, List[Command]]:
    new_state = state.model_copy(
        update={
            "last_sequence": env.sequence,
            "metrics": state.metrics.model_copy(
                update={"through_sequence": env.sequence}
            ),
        }
    )
    cmds: List[Command] = [
        PublishProjection(session_id=state.session_id, sequence=env.sequence)
    ]
    return new_state, cmds


def _handle_protocol_violation(
    state: SessionState, env: EventEnvelope
) -> Tuple[SessionState, List[Command]]:
    cnt = dict(state.metrics.counters)
    cnt["protocol_violations"] = cnt.get("protocol_violations", 0) + 1
    new_metrics = state.metrics.model_copy(
        update={"through_sequence": env.sequence, "counters": cnt}
    )
    new_state = state.model_copy(
        update={"last_sequence": env.sequence, "metrics": new_metrics}
    )
    cmds: List[Command] = [
        PublishProjection(session_id=state.session_id, sequence=env.sequence)
    ]
    return new_state, cmds


_HANDLERS = {
    "UserInputObserved": _handle_user_input,
    "TranscriptHypothesisObserved": _handle_transcript_hypothesis,
    "ControlIntentInterpreted": _handle_control_intent,
    "IntentRevisionProposed": _handle_intent_revision_proposed,
    "IntentRevisionCommitted": _handle_intent_revision_committed,
    "IntentAuthorizationChanged": _handle_intent_authorization_changed,
    "BranchPredicted": _handle_branch_predicted,
    "BranchPreparationStarted": _handle_branch_prep_started,
    "BranchPreparationCompleted": _handle_branch_prep_completed,
    "BranchPromoted": _handle_branch_promoted,
    "BranchInvalidated": _handle_branch_invalidated,
    "OperationCreated": _handle_operation_created,
    "OperationPreparationStarted": _handle_operation_prep_started,
    "OperationPrepared": _handle_operation_prepared,
    "ToolDispatchRequested": _handle_tool_dispatch_requested,
    "ToolDispatchAccepted": _handle_tool_dispatch_accepted,
    "CancellationRequested": _handle_cancellation_requested,
    "CancellationAcknowledged": _handle_cancellation_acknowledged,
    "SafePointReached": _handle_safepoint_reached,
    "ToolResultObserved": _handle_tool_result_observed,
    "ToolTimedOut": _handle_tool_timed_out,
    "WorldEffectObserved": _handle_world_effect_observed,
    "EvidenceRecorded": _handle_evidence_recorded,
    "ClaimProposed": _handle_claim_proposed,
    "ClaimStateChanged": _handle_claim_state_changed,
    "SpeechActProposed": _handle_speech_act_proposed,
    "SpeechActApproved": _handle_speech_act_approved,
    "SpeechActBlocked": _handle_speech_act_blocked,
    "SpeechQueued": _handle_speech_queued,
    "SpeechEmissionStarted": _handle_speech_emission_started,
    "SpeechEmissionFinished": _handle_speech_emission_finished,
    "SpeechCancellationRequested": _handle_speech_cancellation_requested,
    "DivergenceDetected": _handle_divergence_detected,
    "ReconciliationPlanned": _handle_reconciliation_planned,
    "ReconciliationAuthorized": _handle_reconciliation_authorized,
    "ReconciliationDenied": _handle_reconciliation_denied,
    "ReconciliationStepChanged": _handle_reconciliation_step_changed,
    "DivergenceResolved": _handle_divergence_resolved,
    "FaultActivated": _handle_fault_activated,
    "ProtocolViolationObserved": _handle_protocol_violation,
}
