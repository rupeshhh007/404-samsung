"""Runtime command definitions and command union for INTERLOCK.

Implements all command types emitted by the pure reducer as defined in:
- docs/contracts/INTERFACES.md
- docs/components/EVENT_JOURNAL_AND_REDUCER.md
- docs/architecture/EVENT_MODEL.md
- docs/architecture/REPOSITORY_BLUEPRINT.md
"""

from typing import Annotated, Literal, Optional, Union
from pydantic import Field
from interlock.domain.models import DomainBaseModel


class BaseCommand(DomainBaseModel):
    """Base model for all immutable commands emitted by the reducer."""

    session_id: str = Field(..., min_length=1)


class InterpretInput(BaseCommand):
    """Command to interpret raw user input evidence via ControlInterpreter."""

    command_type: Literal["InterpretInput"] = "InterpretInput"
    evidence_id: str = Field(..., min_length=1)
    modality: str = Field(..., min_length=1)
    content_ref: str = Field(..., min_length=1)


class PrepareBranch(BaseCommand):
    """Command to prepare an eligible speculative read-only branch."""

    command_type: Literal["PrepareBranch"] = "PrepareBranch"
    branch_id: str = Field(..., min_length=1)
    operation_id: str = Field(..., min_length=1)


class PrepareOperation(BaseCommand):
    """Command to prepare an operation once created by planner."""

    command_type: Literal["PrepareOperation"] = "PrepareOperation"
    operation_id: str = Field(..., min_length=1)


class DispatchTool(BaseCommand):
    """Command to dispatch an authorized, ready operation to the tool executor."""

    command_type: Literal["DispatchTool"] = "DispatchTool"
    operation_id: str = Field(..., min_length=1)


class RequestToolCancellation(BaseCommand):
    """Command to request cooperative cancellation of an in-flight tool operation."""

    command_type: Literal["RequestToolCancellation"] = "RequestToolCancellation"
    operation_id: str = Field(..., min_length=1)
    reason: Optional[str] = None


class VerifyOutcome(BaseCommand):
    """Command to schedule verification of an uncertain operation effect."""

    command_type: Literal["VerifyOutcome"] = "VerifyOutcome"
    operation_id: str = Field(..., min_length=1)
    provider_effect_id: Optional[str] = Field(default=None, min_length=1)


class BuildReconciliationPlan(BaseCommand):
    """Command to build a reconciliation plan for an open divergence case."""

    command_type: Literal["BuildReconciliationPlan"] = "BuildReconciliationPlan"
    divergence_id: str = Field(..., min_length=1)


class ValidateSpeech(BaseCommand):
    """Command to submit proposed speech to TRUTHLOCK for claim verification."""

    command_type: Literal["ValidateSpeech"] = "ValidateSpeech"
    speech_id: str = Field(..., min_length=1)


class QueueOutput(BaseCommand):
    """Command to queue approved speech for emission."""

    command_type: Literal["QueueOutput"] = "QueueOutput"
    speech_id: str = Field(..., min_length=1)
    rendered_text: str = Field(..., min_length=1)
    policy_id: str = Field(..., min_length=1)


class EmitOutput(BaseCommand):
    """Command to emit queued speech through the output adapter."""

    command_type: Literal["EmitOutput"] = "EmitOutput"
    speech_id: str = Field(..., min_length=1)


class PublishProjection(BaseCommand):
    """Command to publish a state projection snapshot/delta pinned to a sequence."""

    command_type: Literal["PublishProjection"] = "PublishProjection"
    sequence: int = Field(..., ge=0)


class RecordProtocolViolation(BaseCommand):
    """Command emitted on invalid state transitions or protocol breaches."""

    command_type: Literal["RecordProtocolViolation"] = "RecordProtocolViolation"
    boundary: str = Field(..., min_length=1)
    code: str = Field(..., min_length=1)
    digest: str = Field(..., min_length=1)


class RequestClarification(BaseCommand):
    """Command emitted when control intent requests clarification."""

    command_type: Literal["RequestClarification"] = "RequestClarification"
    control_id: str = Field(..., min_length=1)
    clarification: Optional[str] = None


class CancelSpeech(BaseCommand):
    """Command to stop speech emission immediately without cancelling operations."""

    command_type: Literal["CancelSpeech"] = "CancelSpeech"
    speech_id: str = Field(..., min_length=1)


Command = Annotated[
    Union[
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
    ],
    Field(discriminator="command_type"),
]
