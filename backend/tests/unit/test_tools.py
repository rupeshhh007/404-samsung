"""T-TOL-01, T-IDM-01, T-INV-I5-P, T-INV-I5-N: stable identities."""

import pytest
import asyncio

from interlock.domain.events import ToolResultObserved
from interlock.execution.tools import ToolInvocation
from interlock.execution.idempotency import (
    CallbackStatus, IdempotencyError, IdempotencyStatus,
    classify_callback, classify_idempotency, derive_idempotency_key,
    derive_logical_action_id,
)


def test_t_tol_01_t_idm_01_t_inv_i5_p_same_action_is_duplicate():
    action = derive_logical_action_id(
        tool_name="appointment.book", consequential_arguments={"slot": "11"},
        intent_goal_id="booking",
    )
    assert action == derive_logical_action_id(
        tool_name="appointment.book", consequential_arguments={"slot": "11"},
        intent_goal_id="booking",
    )
    key = derive_idempotency_key(session_id="s", logical_action_id=action,
                                 manifest_version=1)
    first = classify_idempotency(idempotency_key=key,
                                 consequential_arguments={"slot": "11"},
                                 known_argument_digests={})
    duplicate = classify_idempotency(idempotency_key=key,
                                     consequential_arguments={"slot": "11"},
                                     known_argument_digests={key: first.argument_digest})
    assert first.status == IdempotencyStatus.NEW
    assert duplicate.status == IdempotencyStatus.DUPLICATE


def test_t_idm_01_t_inv_i5_n_conflicting_retry_or_callback_fails_closed():
    first = classify_idempotency(idempotency_key="key",
                                 consequential_arguments={"slot": "11"},
                                 known_argument_digests={})
    with pytest.raises(IdempotencyError):
        classify_idempotency(idempotency_key="key",
                             consequential_arguments={"slot": "12"},
                             known_argument_digests={"key": first.argument_digest})
    observation = ToolResultObserved(operation_id="op", provider_request_id="request",
                                     outcome="SUCCEEDED", result={"slot": "11"})
    accepted = classify_callback(observation, callback_dedupe_key="callback",
                                 known_observation_digests={})
    duplicate = classify_callback(
        observation, callback_dedupe_key="callback",
        known_observation_digests={"callback": accepted.observation_digest},
    )
    conflict = classify_callback(
        observation.model_copy(update={"result": {"slot": "12"}}),
        callback_dedupe_key="callback",
        known_observation_digests={"callback": accepted.observation_digest},
    )
    assert duplicate.status == CallbackStatus.DUPLICATE
    assert conflict.status == CallbackStatus.CONFLICT
    assert conflict.requires_verification


def test_t_idm_01_t_inv_i5_p_t_inv_i5_n_retries_create_one_physical_effect():
    from interlock.providers.fake_tools import create_fake_tool_transport

    adapter, provider = create_fake_tool_transport()
    invocation = ToolInvocation(
        operation_id="op", dispatch_requested_event_id="dispatch",
        tool_name="appointment.book", descriptor_capability_hash="sha256:hash",
        arguments={"center_id": "ctr-01",
                   "requested_slot": "2030-01-15T12:00:00+05:30",
                   "idempotency_key": "stable-key"},
        logical_action_id="action", idempotency_key="stable-key",
        timeout_ms=5000, deadline_ms=None, cancellation_token="cancel",
        speculative=False, attempt=1,
    )

    first = asyncio.run(adapter.invoke(invocation))
    retry = asyncio.run(adapter.invoke(invocation))
    assert first.observation == retry.observation
    assert first.observation.provider_effect_id == "apt-12"
    observed = ToolResultObserved(
        operation_id=invocation.operation_id,
        provider_request_id=first.observation.provider_request_id,
        outcome=first.observation.outcome,
        result=first.observation.result,
        provider_effect_id=first.observation.provider_effect_id,
    )
    accepted = classify_callback(
        observed, callback_dedupe_key=first.observation.callback_dedupe_key,
        known_observation_digests={},
    )
    duplicate = classify_callback(
        observed, callback_dedupe_key=retry.observation.callback_dedupe_key,
        known_observation_digests={
            first.observation.callback_dedupe_key: accepted.observation_digest
        },
    )
    assert duplicate.status == CallbackStatus.DUPLICATE
    assert provider.physical_action_count == 1
    assert list(provider.bookings) == ["apt-12"]
