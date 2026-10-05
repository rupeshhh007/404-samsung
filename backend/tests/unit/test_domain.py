"""T-DOM-01: strict canonical domain serialization."""

import pytest
from pydantic import ValidationError

from interlock.domain.enums import (
    ActionType, CancellationPolicy, CancellationState, EffectState, OperationState,
)
from interlock.domain.models import OperationRecord


def test_t_dom_01_operation_round_trip_and_illegal_fields():
    operation = OperationRecord(
        operation_id="op-1", tool_name="lookup", intent_revision_id="rev-1",
        fingerprint="fingerprint", action_type=ActionType.READ_ONLY,
        cancellation_policy=CancellationPolicy.IMMEDIATE,
        state=OperationState.CREATED, cancellation_state=CancellationState.NONE,
        effect_state=EffectState.NOT_STARTED, speculative=False,
        logical_action_id="action-1", idempotency_key="key-1",
    )
    assert OperationRecord.model_validate_json(operation.model_dump_json()) == operation
    with pytest.raises(ValidationError):
        OperationRecord.model_validate({**operation.model_dump(), "unexpected": True})
    with pytest.raises(ValidationError):
        OperationRecord.model_validate({**operation.model_dump(), "speculative": True,
                                        "action_type": ActionType.IRREVERSIBLE})
