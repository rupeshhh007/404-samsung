"""T-SEC-01: strict boundaries reject hostile fields and avoid secret leaks."""

import asyncio

import pytest
from pydantic import ValidationError

from interlock.adapters.protocol import AdapterProtocolError, strict_object
from interlock.providers.base import ProviderRequest, ProviderTask
from interlock.providers.llm import StructuredModelProvider


def test_t_sec_01_unknown_wire_fields_and_non_json_model_payload_rejected():
    with pytest.raises(AdapterProtocolError):
        strict_object({"allowed": 1, "authorize": True}, field="input",
                      allowed={"allowed"}, required={"allowed"})
    with pytest.raises(ValidationError):
        ProviderRequest(
            task=ProviderTask.CONTROL_V1, prompt_version="1",
            payload={"unsafe": {1, 2}}, correlation_id="c", timeout_ms=100,
        )


def test_t_sec_01_transport_exception_message_is_redacted():
    async def transport(request, *, repair, previous_output):
        raise RuntimeError("SECRET_TOKEN_123")

    request = ProviderRequest(
        task=ProviderTask.CONTROL_V1, prompt_version="1",
        payload={"candidate_ids": []}, correlation_id="c", timeout_ms=100,
    )
    result = asyncio.run(StructuredModelProvider(transport).invoke(request))
    assert "SECRET_TOKEN_123" not in result.message
