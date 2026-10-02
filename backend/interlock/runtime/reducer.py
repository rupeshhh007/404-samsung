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
    ActionType,
    Authorization,
    BranchState,
    CancellationAckScope,
    CancellationPolicy,
    CancellationState,
    ClaimState,
    ControlKind,
    DivergenceState,
    EffectState,
    EventSource,
    EvidenceAuthority,
    EvidenceSource,
    IntentMaturity,
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
    RequestSpeechCorrection,
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
                revisions={},
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

            next_state, commands = handler(state, envelope)
            if next_state is state and any(
                isinstance(command, RecordProtocolViolation)
                for command in commands
            ):
                consumed_state = state.model_copy(
                    update={
                        "last_sequence": envelope.sequence,
                        "metrics": state.metrics.model_copy(
                            update={"through_sequence": envelope.sequence}
                        ),
                    }
                )
                return (
                    consumed_state,
                    [
                        *commands,
                        PublishProjection(
                            session_id=state.session_id,
                            sequence=envelope.sequence,
                        ),
                    ],
                )
            return next_state, commands

        except Exception as e:
            return (
                state,
                [
                    RecordProtocolViolation(
                        session_id=state.session_id,
                        boundary="reducer",
                        code="REDUCER_TRANSITION_ERROR",
                        digest=f"Reducer transition failed ({type(e).__name__})",
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
    new_evidence, violation = _insert_immutable_evidence(state, ev)
    if violation is not None:
        return state, [violation]
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
    new_evidence, violation = _insert_immutable_evidence(state, ev)
    if violation is not None:
        return state, [violation]
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

    paused = state.paused
    if control.kind == ControlKind.PAUSE:
        paused = True
    elif control.kind == ControlKind.RESUME:
        paused = False

    cmds.append(
        PublishProjection(session_id=state.session_id, sequence=env.sequence)
    )

    new_state = state.model_copy(
        update={
            "paused": paused,
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

    existing_rev = state.revisions.get(rev.revision_id)
    if existing_rev is not None:
        immutable_match = (
            existing_rev.revision_id == rev.revision_id
            and existing_rev.intent_id == rev.intent_id
            and existing_rev.parent_revision_id == rev.parent_revision_id
            and existing_rev.values == rev.values
            and existing_rev.created_by_event_id == rev.created_by_event_id
            and existing_rev.dependency_fingerprint == rev.dependency_fingerprint
        )
        if not immutable_match:
            return (
                state,
                [
                    RecordProtocolViolation(
                        session_id=state.session_id,
                        boundary="reducer",
                        code="IMMUTABLE_REVISION_VIOLATION",
                        digest=f"Revision '{rev.revision_id}' conflicts with its immutable record",
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

    rev_maturity = rev.maturity.value if hasattr(rev.maturity, "value") else rev.maturity
    if rev_maturity == IntentMaturity.SUPERSEDED.value:
        return (
            state,
            [
                RecordProtocolViolation(
                    session_id=state.session_id,
                    boundary="reducer",
                    code="INVALID_REVISION_MATURITY",
                    digest=f"Incoming revision '{rev.revision_id}' has invalid initial maturity SUPERSEDED",
                )
            ],
        )
    if rev_maturity not in (
        IntentMaturity.PROVISIONAL.value,
        IntentMaturity.COMMITTED.value,
    ):
        return (
            state,
            [
                RecordProtocolViolation(
                    session_id=state.session_id,
                    boundary="reducer",
                    code="INVALID_REVISION_MATURITY",
                    digest=f"Incoming revision '{rev.revision_id}' has invalid initial maturity '{rev_maturity}'",
                )
            ],
        )

    rev_auth = rev.authorization.value if hasattr(rev.authorization, "value") else rev.authorization
    if rev_auth != Authorization.NOT_REQUESTED.value:
        return (
            state,
            [
                RecordProtocolViolation(
                    session_id=state.session_id,
                    boundary="reducer",
                    code="INVALID_REVISION_AUTHORIZATION",
                    digest=f"Incoming revision '{rev.revision_id}' must begin with authorization NOT_REQUESTED, got {rev_auth}",
                )
            ],
        )

    node = state.intents.get(rev.intent_id)
    new_revisions = dict(state.revisions)
    if node is None:
        if rev.parent_revision_id is not None:
            return (
                state,
                [
                    RecordProtocolViolation(
                        session_id=state.session_id,
                        boundary="reducer",
                        code="INVALID_REVISION_PARENT",
                        digest=f"Root revision '{rev.revision_id}' for intent '{rev.intent_id}' must have parent_revision_id None, got '{rev.parent_revision_id}'",
                    )
                ],
            )
        goal_type = str(rev.values.get("goal_type", "default"))
        new_node = IntentNode(
            intent_id=rev.intent_id,
            goal_type=goal_type,
            revisions=[rev.revision_id],
            active_revision_id=rev.revision_id,
        )
    else:
        if not node.active_revision_id or rev.parent_revision_id != node.active_revision_id:
            return (
                state,
                [
                    RecordProtocolViolation(
                        session_id=state.session_id,
                        boundary="reducer",
                        code="INVALID_REVISION_PARENT",
                        digest=f"Revision '{rev.revision_id}' parent '{rev.parent_revision_id}' does not match active revision '{node.active_revision_id}' of intent '{rev.intent_id}'",
                    )
                ],
            )

        parent_rev = state.revisions.get(rev.parent_revision_id)
        if parent_rev is None or parent_rev.intent_id != rev.intent_id:
            return (
                state,
                [
                    RecordProtocolViolation(
                        session_id=state.session_id,
                        boundary="reducer",
                        code="INVALID_REVISION_PARENT",
                        digest=f"Revision '{rev.revision_id}' parent '{rev.parent_revision_id}' not found in revisions or belongs to different intent",
                    )
                ],
            )

        superseded_parent = parent_rev.model_copy(
            update={"maturity": IntentMaturity.SUPERSEDED}
        )
        new_revisions[parent_rev.revision_id] = superseded_parent

        new_revs = list(node.revisions)
        if rev.revision_id not in new_revs:
            new_revs.append(rev.revision_id)
        new_node = node.model_copy(
            update={"revisions": new_revs, "active_revision_id": rev.revision_id}
        )

    committed_rev = rev.model_copy(
        update={
            "maturity": IntentMaturity.COMMITTED,
            "authorization": Authorization.NOT_REQUESTED,
        },
        deep=True,
    )
    new_revisions[rev.revision_id] = committed_rev
    new_intents = {**state.intents, rev.intent_id: new_node}
    new_state = state.model_copy(
        update={
            "intents": new_intents,
            "revisions": new_revisions,
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
    if rev_id not in state.revisions:
        return (
            state,
            [
                RecordProtocolViolation(
                    session_id=state.session_id,
                    boundary="reducer",
                    code="UNKNOWN_REVISION",
                    digest=f"Revision '{rev_id}' not found",
                )
            ],
        )

    current_rev = state.revisions[rev_id]
    current_maturity = current_rev.maturity.value if hasattr(current_rev.maturity, "value") else current_rev.maturity
    if current_maturity == IntentMaturity.SUPERSEDED.value:
        return (
            state,
            [
                RecordProtocolViolation(
                    session_id=state.session_id,
                    boundary="reducer",
                    code="INVALID_AUTHORIZATION_TRANSITION",
                    digest=f"Cannot change authorization for SUPERSEDED revision '{rev_id}'",
                )
            ],
        )

    target_auth = Authorization(env.payload["authorization"])
    current_auth = Authorization(current_rev.authorization)

    legal_auth_transitions: Dict[Authorization, set[Authorization]] = {
        Authorization.NOT_REQUESTED: {
            Authorization.REQUIRED,
            Authorization.AUTHORIZED,
            Authorization.DENIED,
        },
        Authorization.REQUIRED: {Authorization.AUTHORIZED, Authorization.DENIED},
        Authorization.AUTHORIZED: {Authorization.EXPIRED},
        Authorization.DENIED: set(),
        Authorization.EXPIRED: set(),
    }

    if target_auth not in legal_auth_transitions.get(current_auth, set()):
        return (
            state,
            [
                RecordProtocolViolation(
                    session_id=state.session_id,
                    boundary="reducer",
                    code="INVALID_AUTHORIZATION_TRANSITION",
                    digest=f"Cannot transition authorization for revision '{rev_id}' from {current_auth} to {target_auth}",
                )
            ],
        )

    updated_rev = current_rev.model_copy(
        update={"authorization": target_auth}, deep=True
    )
    new_revisions = dict(state.revisions)
    new_revisions[rev_id] = updated_rev

    new_state = state.model_copy(
        update={
            "revisions": new_revisions,
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

    if op.operation_id in state.operations:
        return (
            state,
            [
                RecordProtocolViolation(
                    session_id=state.session_id,
                    boundary="reducer",
                    code="DUPLICATE_OPERATION_ID",
                    digest=f"Operation '{op.operation_id}' already exists",
                )
            ],
        )

    op_state = op.state.value if hasattr(op.state, "value") else op.state
    op_cancel = (
        op.cancellation_state.value
        if hasattr(op.cancellation_state, "value")
        else op.cancellation_state
    )
    op_effect = (
        op.effect_state.value
        if hasattr(op.effect_state, "value")
        else op.effect_state
    )

    if (
        op_state != OperationState.CREATED.value
        or op_cancel != CancellationState.NONE.value
        or op_effect != EffectState.NOT_STARTED.value
        or op.provider_request_id is not None
        or op.dispatch_requested_event_id is not None
        or len(op.cancellation_ack_scopes) != 0
    ):
        return (
            state,
            [
                RecordProtocolViolation(
                    session_id=state.session_id,
                    boundary="reducer",
                    code="INVALID_OPERATION_CREATION",
                    digest=f"Operation '{op.operation_id}' has invalid initial creation state (state={op_state}, cancel={op_cancel}, effect={op_effect}, provider_req={op.provider_request_id}, token={op.dispatch_requested_event_id}, scopes={op.cancellation_ack_scopes})",
                )
            ],
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

    validated_seq = env.payload.get("validated_through_sequence")
    if validated_seq is None:
        return (
            state,
            [
                RecordProtocolViolation(
                    session_id=state.session_id,
                    boundary="reducer",
                    code="MISSING_SAFEPOINT_PIN",
                    digest="Dispatch requires validated_through_sequence pin, got None",
                )
            ],
        )
    if validated_seq < state.last_sequence:
        # Expected stale concurrency race: snapshot was taken at an earlier sequence.
        # Preserve the ENTIRE CURRENT operation exactly as-is, whatever its current state is.
        # Advance last_sequence and metrics, emit PublishProjection in live execution.
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

    if validated_seq > state.last_sequence:
        return (
            state,
            [
                RecordProtocolViolation(
                    session_id=state.session_id,
                    boundary="reducer",
                    code="FUTURE_SAFEPOINT_PIN",
                    digest=f"Dispatch pin '{validated_seq}' is ahead of session sequence '{state.last_sequence}'",
                )
            ],
        )

    # validated_seq == state.last_sequence:
    op_state = op.state.value if hasattr(op.state, "value") else op.state
    if op_state != OperationState.READY.value:
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

    # If operation somehow already contains a token before this transition, fail closed
    if op.dispatch_requested_event_id is not None:
        return (
            state,
            [
                RecordProtocolViolation(
                    session_id=state.session_id,
                    boundary="reducer",
                    code="INVALID_OPERATION_STATE",
                    digest=f"Operation '{op_id}' already contains dispatch token before dispatch request",
                )
            ],
        )

    # Authoritative revision and session guards
    if state.paused:
        return (
            state,
            [
                RecordProtocolViolation(
                    session_id=state.session_id,
                    boundary="reducer",
                    code="STALE_SAFEPOINT_DECISION",
                    digest="Session is paused; dispatch prohibited",
                )
            ],
        )

    rev = state.revisions.get(op.intent_revision_id)
    if rev is None:
        return (
            state,
            [
                RecordProtocolViolation(
                    session_id=state.session_id,
                    boundary="reducer",
                    code="STALE_SAFEPOINT_DECISION",
                    digest=f"Operation '{op_id}' revision '{op.intent_revision_id}' not found in authoritative revisions",
                )
            ],
        )

    node = state.intents.get(rev.intent_id)
    if node is None or node.active_revision_id != rev.revision_id:
        return (
            state,
            [
                RecordProtocolViolation(
                    session_id=state.session_id,
                    boundary="reducer",
                    code="STALE_SAFEPOINT_DECISION",
                    digest=f"Operation '{op_id}' revision '{rev.revision_id}' is not active for intent '{rev.intent_id}'",
                )
            ],
        )

    if state.active_intent_id != rev.intent_id:
        return (
            state,
            [
                RecordProtocolViolation(
                    session_id=state.session_id,
                    boundary="reducer",
                    code="STALE_SAFEPOINT_DECISION",
                    digest=f"Active intent '{state.active_intent_id}' does not match revision intent '{rev.intent_id}'",
                )
            ],
        )

    rev_maturity = rev.maturity.value if hasattr(rev.maturity, "value") else rev.maturity
    if rev_maturity == IntentMaturity.SUPERSEDED.value:
        return (
            state,
            [
                RecordProtocolViolation(
                    session_id=state.session_id,
                    boundary="reducer",
                    code="STALE_SAFEPOINT_DECISION",
                    digest=f"Revision '{rev.revision_id}' is SUPERSEDED",
                )
            ],
        )

    op_action_type = op.action_type.value if hasattr(op.action_type, "value") else op.action_type
    if op_action_type != ActionType.READ_ONLY.value:
        rev_auth = rev.authorization.value if hasattr(rev.authorization, "value") else rev.authorization
        if rev_maturity != IntentMaturity.COMMITTED.value or rev_auth != Authorization.AUTHORIZED.value:
            return (
                state,
                [
                    RecordProtocolViolation(
                        session_id=state.session_id,
                        boundary="reducer",
                        code="STALE_SAFEPOINT_DECISION",
                        digest=f"Consequential operation '{op_id}' requires COMMITTED + AUTHORIZED revision (maturity={rev_maturity}, auth={rev_auth})",
                    )
                ],
            )

    op_cancel_state = op.cancellation_state.value if hasattr(op.cancellation_state, "value") else op.cancellation_state
    op_cancel_policy = op.cancellation_policy.value if hasattr(op.cancellation_policy, "value") else op.cancellation_policy
    if op_cancel_state == CancellationState.REQUESTED.value and op_cancel_policy == CancellationPolicy.IMMEDIATE.value:
        return (
            state,
            [
                RecordProtocolViolation(
                    session_id=state.session_id,
                    boundary="reducer",
                    code="STALE_SAFEPOINT_DECISION",
                    digest=f"Cancellation is REQUESTED for operation '{op_id}' with policy IMMEDIATE",
                )
            ],
        )

    new_ops = dict(state.operations)
    new_ops[op_id] = op.model_copy(
        update={
            "state": OperationState.DISPATCHED,
            "dispatch_requested_event_id": env.event_id,
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
    if op.dispatch_requested_event_id is None:
        return (
            state,
            [
                RecordProtocolViolation(
                    session_id=state.session_id,
                    boundary="reducer",
                    code="UNAUTHORIZED_DISPATCH",
                    digest=f"Operation '{op_id}' has no dispatch token",
                )
            ],
        )

    provider_req_id = env.payload["provider_request_id"]
    if op.provider_request_id is not None and op.provider_request_id != provider_req_id:
        return (
            state,
            [
                RecordProtocolViolation(
                    session_id=state.session_id,
                    boundary="reducer",
                    code="PROVIDER_REQUEST_ID_MISMATCH",
                    digest=f"Incoming provider_request_id '{provider_req_id}' conflicts with established '{op.provider_request_id}'",
                )
            ],
        )

    if op.state == OperationState.DISPATCHED:
        new_op_state = OperationState.WAITING
    else:
        new_op_state = op.state
    if op.effect_state in (
        EffectState.COMMITTED,
        EffectState.FAILED,
        EffectState.OUTCOME_UNKNOWN,
        EffectState.COMPENSATED,
    ):
        new_effect_state = op.effect_state
    else:
        new_effect_state = EffectState.IN_FLIGHT

    new_ops = dict(state.operations)
    new_ops[op_id] = op.model_copy(
        update={
            "state": new_op_state,
            "provider_request_id": provider_req_id,
            "effect_state": new_effect_state,
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
    op_cancel_state = (
        op.cancellation_state.value
        if hasattr(op.cancellation_state, "value")
        else op.cancellation_state
    )
    if op_cancel_state not in (
        CancellationState.REQUESTED.value,
        CancellationState.ACKNOWLEDGED.value,
    ):
        return (
            state,
            [
                RecordProtocolViolation(
                    session_id=state.session_id,
                    boundary="reducer",
                    code="INVALID_CANCELLATION_TRANSITION",
                    digest=f"Cancellation must be REQUESTED or ACKNOWLEDGED before ACKNOWLEDGED, got {op.cancellation_state}",
                )
            ],
        )

    raw_scope = env.payload.get("scope")
    if not raw_scope:
        return (
            state,
            [
                RecordProtocolViolation(
                    session_id=state.session_id,
                    boundary="reducer",
                    code="INVALID_CANCELLATION_TRANSITION",
                    digest="CancellationAcknowledged requires 'scope' in payload",
                )
            ],
        )
    try:
        scope_enum = (
            raw_scope
            if isinstance(raw_scope, CancellationAckScope)
            else CancellationAckScope(raw_scope)
        )
    except Exception:
        return (
            state,
            [
                RecordProtocolViolation(
                    session_id=state.session_id,
                    boundary="reducer",
                    code="INVALID_CANCELLATION_TRANSITION",
                    digest=f"Invalid cancellation scope: {raw_scope}",
                )
            ],
        )

    scope_val = scope_enum.value
    existing_scope_vals = [
        s.value if hasattr(s, "value") else s for s in op.cancellation_ack_scopes
    ]
    new_scopes = list(op.cancellation_ack_scopes)
    if scope_val not in existing_scope_vals:
        new_scopes.append(scope_enum)

    new_ops = dict(state.operations)
    upd: Dict[str, Any] = {
        "cancellation_state": CancellationState.ACKNOWLEDGED,
        "cancellation_ack_scopes": new_scopes,
    }
    op_curr_state = op.state.value if hasattr(op.state, "value") else op.state
    if op_curr_state in (
        OperationState.CREATED.value,
        OperationState.PREPARING.value,
        OperationState.READY.value,
        OperationState.DISPATCHED.value,
        OperationState.WAITING.value,
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


def _handle_cancellation_rejected(
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
    op_cancel_state = (
        op.cancellation_state.value
        if hasattr(op.cancellation_state, "value")
        else op.cancellation_state
    )
    if op_cancel_state not in (
        CancellationState.REQUESTED.value,
        CancellationState.ACKNOWLEDGED.value,
    ):
        return (
            state,
            [
                RecordProtocolViolation(
                    session_id=state.session_id,
                    boundary="reducer",
                    code="INVALID_CANCELLATION_TRANSITION",
                    digest=f"Cancellation must be REQUESTED or ACKNOWLEDGED before REJECTED, got {op.cancellation_state}",
                )
            ],
        )

    provider_cancel_accepted_val = CancellationAckScope.PROVIDER_CANCEL_ACCEPTED.value
    has_provider_cancel_accepted = any(
        (s.value if hasattr(s, "value") else s) == provider_cancel_accepted_val
        for s in op.cancellation_ack_scopes
    )
    if has_provider_cancel_accepted:
        return (
            state,
            [
                RecordProtocolViolation(
                    session_id=state.session_id,
                    boundary="reducer",
                    code="INVALID_CANCELLATION_TRANSITION",
                    digest=f"Cannot reject cancellation after PROVIDER_CANCEL_ACCEPTED has been observed for operation '{op_id}'",
                )
            ],
        )

    new_ops = dict(state.operations)
    new_ops[op_id] = op.model_copy(
        update={"cancellation_state": CancellationState.REJECTED}
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


def _handle_cancellation_too_late(
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
    op_cancel_state = (
        op.cancellation_state.value
        if hasattr(op.cancellation_state, "value")
        else op.cancellation_state
    )
    if op_cancel_state not in (
        CancellationState.REQUESTED.value,
        CancellationState.ACKNOWLEDGED.value,
    ):
        return (
            state,
            [
                RecordProtocolViolation(
                    session_id=state.session_id,
                    boundary="reducer",
                    code="INVALID_CANCELLATION_TRANSITION",
                    digest=f"Cancellation must be REQUESTED or ACKNOWLEDGED before TOO_LATE, got {op.cancellation_state}",
                )
            ],
        )

    provider_cancel_accepted_val = CancellationAckScope.PROVIDER_CANCEL_ACCEPTED.value
    has_provider_cancel_accepted = any(
        (s.value if hasattr(s, "value") else s) == provider_cancel_accepted_val
        for s in op.cancellation_ack_scopes
    )
    if has_provider_cancel_accepted:
        return (
            state,
            [
                RecordProtocolViolation(
                    session_id=state.session_id,
                    boundary="reducer",
                    code="INVALID_CANCELLATION_TRANSITION",
                    digest=f"Cannot mark cancellation TOO_LATE after PROVIDER_CANCEL_ACCEPTED has been observed for operation '{op_id}'",
                )
            ],
        )

    new_ops = dict(state.operations)
    new_ops[op_id] = op.model_copy(
        update={"cancellation_state": CancellationState.TOO_LATE}
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

    op = state.operations[op_id]
    incoming_provider_id = env.payload.get("provider_request_id")

    if op.provider_request_id is not None:
        if incoming_provider_id != op.provider_request_id:
            return (
                state,
                [
                    RecordProtocolViolation(
                        session_id=state.session_id,
                        boundary="reducer",
                        code="PROVIDER_REQUEST_ID_MISMATCH",
                        digest=f"Incoming provider_request_id '{incoming_provider_id}' conflicts with established '{op.provider_request_id}'",
                    )
                ],
            )
    else:
        if op.dispatch_requested_event_id is None:
            return (
                state,
                [
                    RecordProtocolViolation(
                        session_id=state.session_id,
                        boundary="reducer",
                        code="UNAUTHORIZED_DISPATCH",
                        digest=f"Operation '{op_id}' has no dispatch token to accept result",
                    )
                ],
            )

    outcome = ToolOutcome(env.payload["outcome"])
    current_effect_state = EffectState(op.effect_state)

    contradictory_outcome = (
        current_effect_state in (EffectState.COMMITTED, EffectState.COMPENSATED)
        and outcome in (ToolOutcome.FAILED, ToolOutcome.UNKNOWN)
    ) or (
        current_effect_state == EffectState.FAILED
        and outcome in (ToolOutcome.SUCCEEDED, ToolOutcome.UNKNOWN)
    )
    if contradictory_outcome:
        return (
            state,
            [
                RecordProtocolViolation(
                    session_id=state.session_id,
                    boundary="reducer",
                    code="INVALID_OPERATION_TRANSITION",
                    digest=(
                        f"Tool result outcome '{outcome.value}' contradicts established "
                        f"effect state '{current_effect_state.value}' for operation '{op_id}'"
                    ),
                )
            ],
        )

    new_ops = dict(state.operations)
    upd: Dict[str, Any] = {}

    if op.provider_request_id is None and incoming_provider_id:
        upd["provider_request_id"] = incoming_provider_id

    # Stale results can update effect dimension, not reactivate operation.
    if current_effect_state != EffectState.COMPENSATED:
        if outcome == ToolOutcome.SUCCEEDED:
            upd["effect_state"] = EffectState.COMMITTED
        elif outcome == ToolOutcome.FAILED:
            upd["effect_state"] = EffectState.FAILED
        elif outcome == ToolOutcome.UNKNOWN:
            upd["effect_state"] = EffectState.OUTCOME_UNKNOWN

    if op.state in (OperationState.DISPATCHED, OperationState.WAITING):
        if outcome == ToolOutcome.SUCCEEDED:
            upd["state"] = OperationState.SUCCEEDED
        elif outcome == ToolOutcome.FAILED:
            upd["state"] = OperationState.FAILED

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
    after_dispatch = bool(env.payload.get("after_dispatch", False))
    active_states = (OperationState.DISPATCHED, OperationState.WAITING)
    late_ambiguity_states = (
        OperationState.TIMED_OUT,
        OperationState.CANCELLED,
        OperationState.SUPERSEDED,
    )

    if after_dispatch and op.dispatch_requested_event_id is None:
        return (
            state,
            [
                RecordProtocolViolation(
                    session_id=state.session_id,
                    boundary="reducer",
                    code="UNAUTHORIZED_DISPATCH",
                    digest=f"Operation '{op_id}' has no dispatch token to accept post-dispatch timeout",
                )
            ],
        )

    allowed_states = (
        active_states + late_ambiguity_states
        if after_dispatch
        else active_states
    )
    if op.state not in allowed_states:
        return (
            state,
            [
                RecordProtocolViolation(
                    session_id=state.session_id,
                    boundary="reducer",
                    code="INVALID_OPERATION_TRANSITION",
                    digest=(
                        f"Operation '{op_id}' is in state '{op.state}', expected "
                        f"DISPATCHED or WAITING"
                        + (
                            ", or previously-dispatched TIMED_OUT, CANCELLED, or SUPERSEDED"
                            if after_dispatch
                            else ""
                        )
                        + " for timeout"
                    ),
                )
            ],
        )

    new_ops = dict(state.operations)
    upd: Dict[str, Any] = {}
    if op.state in active_states:
        upd["state"] = OperationState.TIMED_OUT

    current_effect_state = EffectState(op.effect_state)
    unresolved_effect_states = (
        EffectState.NOT_STARTED,
        EffectState.IN_FLIGHT,
        EffectState.OUTCOME_UNKNOWN,
    )
    requires_verification = (
        after_dispatch and current_effect_state in unresolved_effect_states
    )
    if requires_verification:
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
    if requires_verification:
        cmds.append(
            VerifyOutcome(session_id=state.session_id, operation_id=op_id)
        )
    cmds.append(
        PublishProjection(session_id=state.session_id, sequence=env.sequence)
    )
    return new_state, cmds


def _has_scoped_effect_verification(
    state: SessionState, env: EventEnvelope, effect: EffectRecord
) -> bool:
    """Recognize a causally scoped verifier result without resolving projection here."""

    if (
        env.source != EventSource.TOOL
        or not env.causation_id
        or effect.authority != EvidenceAuthority.AUTHORITATIVE
        or effect.state not in (EffectState.COMMITTED, EffectState.FAILED, EffectState.COMPENSATED)
    ):
        return False
    covered_ids = sorted(
        previous.effect_id
        for previous in state.effects.values()
        if previous.provider_effect_id == effect.provider_effect_id
        and previous.authority == EvidenceAuthority.AUTHORITATIVE
    )
    if not covered_ids:
        return False
    return any(
        evidence is not None
        and evidence.source == EvidenceSource.TOOL
        and evidence.authority == EvidenceAuthority.AUTHORITATIVE
        and evidence.kind == "world_effect_verification"
        and evidence.provenance.get("provider_effect_id") == effect.provider_effect_id
        and evidence.provenance.get("verification_request_event_id") == env.causation_id
        and isinstance(evidence.provenance.get("provider_request_id"), str)
        and bool(evidence.provenance["provider_request_id"])
        and evidence.provenance.get("verification_of_effect_ids") == covered_ids
        for evidence in (state.evidence.get(evidence_id) for evidence_id in effect.evidence_ids)
    )


def _handle_world_effect_observed(
    state: SessionState, env: EventEnvelope
) -> Tuple[SessionState, List[Command]]:
    eff_data = env.payload["effect"]
    effect = (
        eff_data
        if isinstance(eff_data, EffectRecord)
        else EffectRecord.model_validate(eff_data)
    )
    operation = state.operations.get(effect.operation_id)
    if operation is None or operation.logical_action_id != effect.logical_action_id:
        return state, [
            RecordProtocolViolation(
                session_id=state.session_id,
                boundary="reducer",
                code="INVALID_EFFECT_CORRELATION",
                digest="Effect does not match a local operation",
            )
        ]

    existing = state.effects.get(effect.effect_id)
    if existing is not None:
        if existing.model_dump(mode="json") != effect.model_dump(mode="json"):
            return state, [
                RecordProtocolViolation(
                    session_id=state.session_id,
                    boundary="reducer",
                    code="IMMUTABLE_EFFECT_VIOLATION",
                    digest="Effect ID conflicts with its immutable observation",
                )
            ]
        # A repeated observation ID is idempotent; keep the stored object.
        new_effects = state.effects
    else:
        if effect.state == EffectState.COMPENSATED:
            prior = state.effects.get(effect.supersedes_effect_id or "")
            if (
                prior is None
                or prior.state != EffectState.COMMITTED
                or prior.provider_effect_id != effect.provider_effect_id
            ):
                return state, [
                    RecordProtocolViolation(
                        session_id=state.session_id,
                        boundary="reducer",
                        code="INVALID_EFFECT_COMPENSATION",
                        digest="Compensation has no matching committed predecessor",
                    )
                ]
        new_effects = {
            **state.effects,
            effect.effect_id: effect.model_copy(deep=True),
        }

    new_operations = state.operations
    prior_authoritative_failure = any(
        prior.state == EffectState.FAILED
        and prior.authority == EvidenceAuthority.AUTHORITATIVE
        and prior.provider_effect_id == effect.provider_effect_id
        for prior in state.effects.values()
    )
    if existing is None and effect.state == EffectState.COMMITTED and not prior_authoritative_failure and operation.effect_state in (
        EffectState.NOT_STARTED,
        EffectState.IN_FLIGHT,
        EffectState.OUTCOME_UNKNOWN,
    ):
        new_operations = {
            **state.operations,
            effect.operation_id: operation.model_copy(update={"effect_state": EffectState.COMMITTED}),
        }
    elif existing is None and effect.state == EffectState.COMPENSATED:
        predecessor = state.effects[effect.supersedes_effect_id]
        prior_operation = state.operations.get(predecessor.operation_id)
        if prior_operation is not None and prior_operation.effect_state == EffectState.COMMITTED:
            new_operations = {
                **state.operations,
                predecessor.operation_id: prior_operation.model_copy(
                    update={"effect_state": EffectState.COMPENSATED}
                ),
            }

    cmds: List[Command] = []
    scoped_verification = _has_scoped_effect_verification(state, env, effect)
    if existing is None and effect.state == EffectState.COMMITTED:
        # Observation IDs are local facts; provider IDs identify physical effects.
        # Neither conflicting physical facts nor duplicate physical writes can be
        # collapsed merely because the later callback arrived last.
        verification_targets: dict[str, str] = {}
        for previous in state.effects.values():
            if previous.state not in (
                EffectState.COMMITTED,
                EffectState.FAILED,
                EffectState.COMPENSATED,
            ) or previous.authority != EvidenceAuthority.AUTHORITATIVE:
                continue
            same_physical = previous.provider_effect_id == effect.provider_effect_id
            if same_physical and not scoped_verification and (
                previous.state != EffectState.COMMITTED
                or previous.effect_type != effect.effect_type
                or previous.subject != effect.subject
                or previous.parameters != effect.parameters
                or previous.logical_action_id != effect.logical_action_id
            ):
                verification_targets[effect.provider_effect_id] = effect.operation_id
            if (
                previous.state == EffectState.COMMITTED
                and not same_physical
                and previous.logical_action_id == effect.logical_action_id
            ):
                verification_targets[previous.provider_effect_id] = previous.operation_id
                verification_targets[effect.provider_effect_id] = effect.operation_id
        for provider_effect_id, operation_id in sorted(verification_targets.items()):
            cmds.append(
                VerifyOutcome(
                    session_id=state.session_id,
                    operation_id=operation_id,
                    provider_effect_id=provider_effect_id,
                )
            )
    elif existing is None and effect.supersedes_effect_id is not None and effect.state in (
        EffectState.COMPENSATED,
        EffectState.FAILED,
        EffectState.OUTCOME_UNKNOWN,
    ):
        predecessor = state.effects.get(effect.supersedes_effect_id)
        if predecessor is not None:
            competing_compensations = (
                previous
                for previous in state.effects.values()
                if previous.state == EffectState.COMPENSATED
                and previous.supersedes_effect_id == predecessor.effect_id
            )
            conflicting_compensation = any(
                previous.effect_type != effect.effect_type
                or previous.subject != effect.subject
                or previous.parameters != effect.parameters
                for previous in competing_compensations
            )
            if (effect.state != EffectState.COMPENSATED or conflicting_compensation) and not scoped_verification:
                cmds.append(
                    VerifyOutcome(
                        session_id=state.session_id,
                        operation_id=effect.operation_id,
                        provider_effect_id=predecessor.provider_effect_id,
                    )
                )
    elif existing is None and effect.state == EffectState.FAILED and effect.authority == EvidenceAuthority.AUTHORITATIVE:
        if not scoped_verification and any(
            previous.state == EffectState.COMMITTED
            and previous.authority == EvidenceAuthority.AUTHORITATIVE
            and previous.provider_effect_id == effect.provider_effect_id
            for previous in state.effects.values()
        ):
            cmds.append(
                VerifyOutcome(
                    session_id=state.session_id,
                    operation_id=effect.operation_id,
                    provider_effect_id=effect.provider_effect_id,
                )
            )
    new_state = state.model_copy(
        update={
            "effects": new_effects,
            "operations": new_operations,
            "last_sequence": env.sequence,
            "metrics": state.metrics.model_copy(
                update={"through_sequence": env.sequence}
            ),
        }
    )
    cmds.append(PublishProjection(session_id=state.session_id, sequence=env.sequence))
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

    new_evidence, violation = _insert_immutable_evidence(state, ev)
    if violation is not None:
        return state, [violation]
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


def _insert_immutable_evidence(
    state: SessionState,
    evidence: EvidenceRecord,
) -> Tuple[Optional[Dict[str, EvidenceRecord]], Optional[RecordProtocolViolation]]:
    """Return an immutable evidence map or a deterministic I8 violation."""

    existing = state.evidence.get(evidence.evidence_id)
    if existing is None:
        return {
            **state.evidence,
            evidence.evidence_id: evidence.model_copy(deep=True),
        }, None
    if existing.model_dump(mode="json") == evidence.model_dump(mode="json"):
        return state.evidence, None
    return (
        None,
        RecordProtocolViolation(
            session_id=state.session_id,
            boundary="reducer",
            code="IMMUTABLE_EVIDENCE_VIOLATION",
            digest=f"Evidence '{evidence.evidence_id}' conflicts with its immutable record",
        ),
    )


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
            "updated_by_event_id": env.event_id,
        }
    )

    # Inspect ONLY speech acts whose approved_claim_versions contain this claim
    new_speech = dict(state.speech)
    cmds: List[Command] = []
    for sp_id, speech in list(new_speech.items()):
        if cid in speech.approved_claim_versions:
            if speech.state == SpeechState.APPROVED:
                new_speech[sp_id] = speech.model_copy(update={"state": SpeechState.CANCELLED})
                cmds.append(CancelSpeech(session_id=state.session_id, speech_id=sp_id))
            elif speech.state in (SpeechState.QUEUED, SpeechState.EMITTING):
                new_speech[sp_id] = speech.model_copy(
                    update={"cancellation_pending": True, "correction_pending": True}
                )
                cmds.append(CancelSpeech(session_id=state.session_id, speech_id=sp_id))
            elif speech.state == SpeechState.EMITTED:
                if speech.heard is True:
                    new_speech[sp_id] = speech.model_copy(update={"state": SpeechState.CORRECTION_REQUIRED})
                    cmds.append(
                        RequestSpeechCorrection(
                            session_id=state.session_id,
                            speech_id=sp_id,
                            triggering_claim_id=cid,
                        )
                    )
                # If heard is False or None: preserve EMITTED history, do not request spoken correction
            elif speech.state == SpeechState.CORRECTION_REQUIRED:
                # remain as-is; do not generate duplicate correction requests.
                pass

    new_state = state.model_copy(
        update={
            "claims": new_claims,
            "speech": new_speech,
            "last_sequence": env.sequence,
            "metrics": state.metrics.model_copy(
                update={"through_sequence": env.sequence}
            ),
        }
    )
    cmds.append(PublishProjection(session_id=state.session_id, sequence=env.sequence))
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

    if speech.speech_id in state.speech:
        return (
            state,
            [
                RecordProtocolViolation(
                    session_id=state.session_id,
                    boundary="reducer",
                    code="DUPLICATE_SPEECH_ID",
                    digest=f"SpeechAct with ID '{speech.speech_id}' already exists in session state",
                )
            ],
        )

    if (
        speech.state != SpeechState.PROPOSED
        or speech.rendered_text is not None
        or speech.approved_policy_id is not None
        or speech.approved_through_sequence is not None
        or speech.approved_claim_versions != {}
        or speech.heard is not None
        or speech.cancellation_pending is not False
        or speech.correction_pending is not False
    ):
        return (
            state,
            [
                RecordProtocolViolation(
                    session_id=state.session_id,
                    boundary="reducer",
                    code="INVALID_SPEECH_PROPOSAL",
                    digest=(
                        f"SpeechAct '{speech.speech_id}' cannot pre-populate reducer-owned lifecycle fields: "
                        f"state={speech.state}, rendered_text={speech.rendered_text}, "
                        f"policy={speech.approved_policy_id}, through_seq={speech.approved_through_sequence}, "
                        f"claim_versions={speech.approved_claim_versions}, heard={speech.heard}, "
                        f"cancellation_pending={speech.cancellation_pending}, "
                        f"correction_pending={speech.correction_pending}"
                    ),
                )
            ],
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

    through_sequence = env.payload.get("through_sequence")
    claim_versions = env.payload.get("claim_versions", {})

    # Future pin check
    if through_sequence is not None and through_sequence > state.last_sequence:
        return (
            state,
            [
                RecordProtocolViolation(
                    session_id=state.session_id,
                    boundary="reducer",
                    code="FUTURE_SPEECH_PIN",
                    digest=f"Speech approval through_sequence {through_sequence} exceeds current sequence {state.last_sequence}",
                )
            ],
        )

    # Missing pin check
    if through_sequence is None:
        return (
            state,
            [
                RecordProtocolViolation(
                    session_id=state.session_id,
                    boundary="reducer",
                    code="MISSING_SPEECH_PIN",
                    digest=f"Speech approval for '{sp_id}' is missing required through_sequence pin",
                )
            ],
        )

    # Exact claim-version key coverage check
    expected_claim_ids = set(speech.claim_ids)
    provided_claim_ids = set(claim_versions.keys())
    if expected_claim_ids != provided_claim_ids:
        return (
            state,
            [
                RecordProtocolViolation(
                    session_id=state.session_id,
                    boundary="reducer",
                    code="INVALID_SPEECH_APPROVAL_PROOF",
                    digest=(
                        f"Speech '{sp_id}' claim_versions keys {provided_claim_ids} "
                        f"do not match expected claim_ids {expected_claim_ids}"
                    ),
                )
            ],
        )

    # Check for blank versions in claim_versions
    for cid, ver in claim_versions.items():
        if not ver or not isinstance(ver, str):
            return (
                state,
                [
                    RecordProtocolViolation(
                        session_id=state.session_id,
                        boundary="reducer",
                        code="INVALID_SPEECH_APPROVAL_PROOF",
                        digest=f"Speech '{sp_id}' has blank or invalid version for claim '{cid}'",
                    )
                ],
            )

    # Staleness check:
    # 1. sequence pin staleness
    is_stale = through_sequence < state.last_sequence

    # 2. claim version staleness
    if not is_stale:
        for cid, ver in claim_versions.items():
            if cid not in state.claims or state.claims[cid].updated_by_event_id != ver:
                is_stale = True
                break

    if is_stale:
        # Normal race condition: stale snapshot evaluated by TRUTHLOCK.
        # Retry: leave speech PROPOSED, emit ValidateSpeech again, advance sequence, PublishProjection.
        new_state = state.model_copy(
            update={
                "last_sequence": env.sequence,
                "metrics": state.metrics.model_copy(
                    update={"through_sequence": env.sequence}
                ),
            }
        )
        cmds: List[Command] = [
            ValidateSpeech(session_id=state.session_id, speech_id=sp_id),
            PublishProjection(session_id=state.session_id, sequence=env.sequence),
        ]
        return new_state, cmds

    # Valid approval: persist rendered_text and proof, transition to APPROVED, emit QueueOutput
    new_speech = dict(state.speech)
    new_speech[sp_id] = speech.model_copy(
        update={
            "state": SpeechState.APPROVED,
            "rendered_text": env.payload["rendered_text"],
            "approved_policy_id": env.payload["policy_id"],
            "approved_through_sequence": through_sequence,
            "approved_claim_versions": claim_versions,
        }
    )
    new_state = state.model_copy(
        update={
            "speech": new_speech,
            "last_sequence": env.sequence,
            "metrics": state.metrics.model_copy(
                update={"through_sequence": env.sequence}
            ),
        }
    )
    cmds = [
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
    if speech.state == SpeechState.QUEUED:
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

    if speech.state == SpeechState.CANCELLED:
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

    # Pre-queue currency check:
    # 1. cancellation_pending flag
    # 2. For each approved_claim_versions entry: current ClaimRecord must exist and updated_by_event_id must exactly match.
    is_stale = speech.cancellation_pending
    if not is_stale:
        for cid, ver in speech.approved_claim_versions.items():
            if cid not in state.claims or state.claims[cid].updated_by_event_id != ver:
                is_stale = True
                break

    new_speech = dict(state.speech)
    if is_stale:
        new_speech[sp_id] = speech.model_copy(
            update={
                "state": SpeechState.CANCELLED,
                "cancellation_pending": False,
                "correction_pending": False,
            }
        )
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
    if speech.state == SpeechState.EMITTING:
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
    heard = bool(env.payload.get("heard", False))

    if speech.state in (
        SpeechState.EMITTED,
        SpeechState.CORRECTION_REQUIRED,
        SpeechState.CANCELLED,
    ):
        if speech.heard is not None and heard == speech.heard:
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

        return (
            state,
            [
                RecordProtocolViolation(
                    session_id=state.session_id,
                    boundary="reducer",
                    code="CONTRADICTORY_SPEECH_TERMINAL",
                    digest=(
                        f"Incoming SpeechEmissionFinished heard={heard} contradicts established speech "
                        f"'{sp_id}' in state {speech.state} (heard={speech.heard})"
                    ),
                )
            ],
        )

    if speech.state not in (SpeechState.QUEUED, SpeechState.EMITTING):
        return (
            state,
            [
                RecordProtocolViolation(
                    session_id=state.session_id,
                    boundary="reducer",
                    code="INVALID_SPEECH_TRANSITION",
                    digest=f"Speech '{sp_id}' is in state '{speech.state}', expected EMITTING or QUEUED",
                )
            ],
        )

    cmds: List[Command] = []

    if not heard:
        if speech.cancellation_pending:
            target_state = SpeechState.CANCELLED
        else:
            target_state = SpeechState.EMITTED
    else:  # heard is True
        if speech.correction_pending:
            target_state = SpeechState.CORRECTION_REQUIRED
            triggering_cid = ""
            for cid, ver in speech.approved_claim_versions.items():
                if cid not in state.claims or state.claims[cid].updated_by_event_id != ver:
                    triggering_cid = cid
                    break
            if not triggering_cid and speech.claim_ids:
                triggering_cid = speech.claim_ids[0]
            cmds.append(
                RequestSpeechCorrection(
                    session_id=state.session_id,
                    speech_id=sp_id,
                    triggering_claim_id=triggering_cid,
                )
            )
        else:
            target_state = SpeechState.EMITTED

    new_speech = dict(state.speech)
    new_speech[sp_id] = speech.model_copy(
        update={
            "state": target_state,
            "heard": heard,
            "cancellation_pending": False,
            "correction_pending": False,
        }
    )
    new_state = state.model_copy(
        update={
            "speech": new_speech,
            "last_sequence": env.sequence,
            "metrics": state.metrics.model_copy(
                update={"through_sequence": env.sequence}
            ),
        }
    )
    cmds.append(PublishProjection(session_id=state.session_id, sequence=env.sequence))
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
        SpeechState.CORRECTION_REQUIRED,
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

    if speech.state in (SpeechState.QUEUED, SpeechState.EMITTING):
        new_speech = dict(state.speech)
        new_speech[sp_id] = speech.model_copy(update={"cancellation_pending": True})
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


def _handle_speech_emission_failed(
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
    heard = bool(env.payload.get("heard", False))

    if speech.state in (
        SpeechState.EMITTED,
        SpeechState.CORRECTION_REQUIRED,
        SpeechState.CANCELLED,
    ):
        if speech.heard is not None and heard == speech.heard:
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

        return (
            state,
            [
                RecordProtocolViolation(
                    session_id=state.session_id,
                    boundary="reducer",
                    code="CONTRADICTORY_SPEECH_TERMINAL",
                    digest=(
                        f"Incoming SpeechEmissionFailed heard={heard} contradicts established speech "
                        f"'{sp_id}' in state {speech.state} (heard={speech.heard})"
                    ),
                )
            ],
        )

    cmds: List[Command] = []

    if speech.state == SpeechState.APPROVED:
        if heard:
            return (
                state,
                [
                    RecordProtocolViolation(
                        session_id=state.session_id,
                        boundary="reducer",
                        code="INVALID_SPEECH_TRANSITION",
                        digest=f"Speech '{sp_id}' in state APPROVED cannot fail with heard=True",
                    )
                ],
            )
        target_state = SpeechState.CANCELLED
        new_speech = dict(state.speech)
        new_speech[sp_id] = speech.model_copy(
            update={
                "state": target_state,
                "heard": False,
                "cancellation_pending": False,
                "correction_pending": False,
            }
        )
    elif speech.state in (SpeechState.QUEUED, SpeechState.EMITTING):
        if not heard:
            target_state = SpeechState.CANCELLED
            new_speech = dict(state.speech)
            new_speech[sp_id] = speech.model_copy(
                update={
                    "state": target_state,
                    "heard": False,
                    "cancellation_pending": False,
                    "correction_pending": False,
                }
            )
        elif heard and not speech.correction_pending:
            target_state = SpeechState.EMITTED
            new_speech = dict(state.speech)
            new_speech[sp_id] = speech.model_copy(
                update={
                    "state": target_state,
                    "heard": True,
                    "cancellation_pending": False,
                    "correction_pending": False,
                }
            )
        else:  # heard and speech.correction_pending
            target_state = SpeechState.CORRECTION_REQUIRED
            triggering_cid = ""
            for cid, ver in speech.approved_claim_versions.items():
                if cid not in state.claims or state.claims[cid].updated_by_event_id != ver:
                    triggering_cid = cid
                    break
            if not triggering_cid and speech.claim_ids:
                triggering_cid = speech.claim_ids[0]
            cmds.append(
                RequestSpeechCorrection(
                    session_id=state.session_id,
                    speech_id=sp_id,
                    triggering_claim_id=triggering_cid,
                )
            )
            new_speech = dict(state.speech)
            new_speech[sp_id] = speech.model_copy(
                update={
                    "state": target_state,
                    "heard": True,
                    "cancellation_pending": False,
                    "correction_pending": False,
                }
            )
    else:
        return (
            state,
            [
                RecordProtocolViolation(
                    session_id=state.session_id,
                    boundary="reducer",
                    code="INVALID_SPEECH_TRANSITION",
                    digest=f"Cannot handle SpeechEmissionFailed for speech '{sp_id}' in state '{speech.state}'",
                )
            ],
        )

    new_state = state.model_copy(
        update={
            "speech": new_speech,
            "last_sequence": env.sequence,
            "metrics": state.metrics.model_copy(
                update={"through_sequence": env.sequence}
            ),
        }
    )
    cmds.append(PublishProjection(session_id=state.session_id, sequence=env.sequence))
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
    "CancellationRejected": _handle_cancellation_rejected,
    "CancellationTooLate": _handle_cancellation_too_late,
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
    "SpeechEmissionFailed": _handle_speech_emission_failed,
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
