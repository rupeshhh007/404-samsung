"""T-LLM-01: structured provider rejects policy violations and timeouts."""

import asyncio

from interlock.providers.base import ProviderFailure, ProviderFailureKind, ProviderRequest, ProviderTask
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
