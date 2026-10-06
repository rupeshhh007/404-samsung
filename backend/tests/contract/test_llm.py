"""T-LLM-01: structured provider rejects policy violations and timeouts."""

import asyncio

from interlock.providers.base import (
    ProviderFailure, ProviderFailureKind, ProviderRequest, ProviderSuccess,
    ProviderTask, ProviderUnavailableError,
)
from interlock.providers.llm import StructuredModelProvider


def _request():
    return ProviderRequest(
        task=ProviderTask.CONTROL_V1, prompt_version="1",
        payload={"candidate_ids": []}, correlation_id="correlation",
        timeout_ms=100,
    )


def test_t_llm_01_invalid_control_cannot_invent_authorization():
    calls = []

    async def transport(request, *, repair, previous_output):
        calls.append(repair)
        return {"kind": "DELETE_BOOKING", "confidence": 1.0,
                "consequential": True, "target_refs": [],
                "clarification": None}

    result = asyncio.run(StructuredModelProvider(transport).invoke(_request()))
    assert isinstance(result, ProviderFailure)
    assert result.kind == ProviderFailureKind.INVALID_OUTPUT
    assert calls == [False]


def test_t_llm_01_timeout_is_typed_and_unrepaired():
    async def transport(request, *, repair, previous_output):
        raise asyncio.TimeoutError()

    result = asyncio.run(StructuredModelProvider(transport).invoke(_request()))
    assert result.kind == ProviderFailureKind.TIMEOUT
    assert not result.repair_attempted


def test_t_llm_01_valid_output_is_accepted_without_action_or_repair():
    calls = []

    async def transport(request, *, repair, previous_output):
        calls.append((repair, previous_output))
        return {"kind": "BACKCHANNEL", "confidence": 1.0, "consequential": False,
                "target_refs": [], "clarification": None}

    result = asyncio.run(StructuredModelProvider(transport).invoke(_request()))
    assert isinstance(result, ProviderSuccess)
    assert result.data["kind"] == "BACKCHANNEL"
    assert result.repaired is False
    assert calls == [(False, None)]
    assert not hasattr(result, "commands")


def test_t_llm_01_repair_once_then_fail_closed_and_unavailable_is_typed():
    calls = []

    async def malformed(request, *, repair, previous_output):
        calls.append((repair, previous_output))
        return "not-json" if not repair else {"kind": "BACKCHANNEL", "extra": True}

    invalid = asyncio.run(StructuredModelProvider(malformed).invoke(_request()))
    assert invalid.kind == ProviderFailureKind.INVALID_OUTPUT
    assert invalid.repair_attempted is True
    assert [repair for repair, _ in calls] == [False, True]

    async def unavailable(request, *, repair, previous_output):
        raise ProviderUnavailableError()

    unavailable_result = asyncio.run(
        StructuredModelProvider(unavailable).invoke(_request())
    )
    assert unavailable_result.kind == ProviderFailureKind.UNAVAILABLE
    assert unavailable_result.repair_attempted is False

    absent = asyncio.run(StructuredModelProvider(None).invoke(_request()))
    assert absent.kind == ProviderFailureKind.UNAVAILABLE
    assert absent.repair_attempted is False
