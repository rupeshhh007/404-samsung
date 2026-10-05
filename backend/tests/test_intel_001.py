"""Focused regression and safety tests for Owner-B ticket INTEL-001."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from interlock.config import Settings
from interlock.domain.enums import ControlKind, EventSource, OperationState
from interlock.intelligence.control import ControlInterpreter, InterpretationRequest
from interlock.main import create_demo_asgi_app
from interlock.providers.base import (
    ProviderFailure,
    ProviderFailureKind,
    ProviderRequest,
    ProviderTask,
)
from interlock.providers.llm import StructuredModelProvider
from interlock.runtime.journal import EventCandidate


class SequenceTransport:
    """Deterministic injected transport that records every attempted call."""

    def __init__(self, outputs: list[Any]) -> None:
        self.outputs = list(outputs)
        self.calls: list[bool] = []
        self.requests: list[ProviderRequest] = []

    async def __call__(
        self,
        request: ProviderRequest,
        *,
        repair: bool,
        previous_output: Any,
    ) -> Any:
        self.calls.append(repair)
        self.requests.append(request)
        output = self.outputs.pop(0)
        if isinstance(output, BaseException):
            raise output
        return output


def run(coroutine: Any) -> Any:
    return asyncio.run(coroutine)


def settings(*, mode: str = "DEMO", provider: str = "fallback") -> Settings:
    values: dict[str, Any] = {
        "INTERLOCK_MODE": mode,
        "INTERLOCK_MODEL_PROVIDER": provider,
    }
    if mode == "LIVE" and provider == "configured":
        values["INTERLOCK_MODEL_API_KEY"] = "test-only"
    return Settings(**values)


def interpretation_request(
    text: str,
    *,
    candidate_target_ids: list[str] | None = None,
    active_intent_id: str | None = "intent-1",
    context: dict[str, Any] | None = None,
    final: bool = True,
) -> InterpretationRequest:
    return InterpretationRequest(
        control_id="control-1",
        raw_evidence_id="evidence-1",
        text=text,
        final=final,
        correlation_id="correlation-1",
        candidate_target_ids=candidate_target_ids or [],
        active_intent_id=active_intent_id,
        context=context or {},
        timeout_ms=20,
    )


def provider_request(task: ProviderTask, payload: dict[str, Any]) -> ProviderRequest:
    return ProviderRequest(
        task=task,
        prompt_version="1",
        payload=payload,
        correlation_id="correlation-1",
        timeout_ms=20,
    )


def control_output(
    kind: str,
    *,
    confidence: float = 0.96,
    consequential: bool = True,
    target_refs: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "kind": kind,
        "confidence": confidence,
        "consequential": consequential,
        "target_refs": target_refs or [],
        "clarification": None,
    }


def delta_output(confidence: float, value: Any = 12) -> dict[str, Any]:
    return {
        "target_intent_id": "intent-1",
        "set_fields": {"time": value},
        "unset_fields": [],
        "add_goals": [],
        "retract_goals": [],
        "confidence": confidence,
    }


def configured_interpreter(
    transport: SequenceTransport,
    *,
    mode: str = "DEMO",
) -> ControlInterpreter:
    return ControlInterpreter(
        settings(mode=mode, provider="configured"),
        configured_provider=StructuredModelProvider(transport),
    )


def test_active_intent_is_trusted_when_candidate_targets_are_empty() -> None:
    candidates: list[str] = []
    request = interpretation_request(
        "Actually make it 12",
        candidate_target_ids=candidates,
        context={"correction_field": "time"},
    )

    result = run(ControlInterpreter(settings()).interpret(request))

    assert candidates == []
    assert result.control.kind == ControlKind.CORRECT
    assert result.control.target_refs == ["intent-1"]
    assert result.intent_delta is not None
    assert result.intent_delta.target_intent_id == "intent-1"


def test_configured_control_receives_ordered_unique_trusted_targets() -> None:
    candidates = ["candidate-1", "intent-1", "candidate-1"]
    transport = SequenceTransport(
        [control_output("BACKCHANNEL", consequential=False)]
    )
    request = interpretation_request(
        "okay",
        candidate_target_ids=candidates,
    )

    result = run(configured_interpreter(transport).interpret(request))

    assert result.control.kind == ControlKind.BACKCHANNEL
    assert candidates == ["candidate-1", "intent-1", "candidate-1"]
    assert transport.requests[0].payload["candidate_ids"] == [
        "candidate-1",
        "intent-1",
    ]


def test_fabricated_target_still_fails_closed() -> None:
    transport = SequenceTransport(
        [control_output("REFER", target_refs=["fabricated-intent"])]
    )
    request = interpretation_request(
        "that one",
        candidate_target_ids=[],
        active_intent_id="intent-1",
    )

    result = run(configured_interpreter(transport, mode="LIVE").interpret(request))

    assert transport.calls == [False]
    assert result.control.kind == ControlKind.CLARIFY
    assert result.intent_delta is None
    assert result.provider_failure is not None
    assert result.provider_failure.kind == ProviderFailureKind.INVALID_OUTPUT


@pytest.mark.parametrize(
    ("delta_confidence", "expected_kind", "has_delta"),
    [
        pytest.param(0.20, ControlKind.CLARIFY, False, id="below-threshold"),
        pytest.param(0.85, ControlKind.CORRECT, True, id="at-threshold"),
    ],
)
def test_intent_delta_uses_consequential_confidence_threshold(
    delta_confidence: float,
    expected_kind: ControlKind,
    has_delta: bool,
) -> None:
    transport = SequenceTransport(
        [
            control_output("CORRECT", confidence=0.99, target_refs=["intent-1"]),
            delta_output(delta_confidence),
        ]
    )
    request = interpretation_request(
        "Change time to 12",
        candidate_target_ids=[],
        context={"correction_field": "time"},
    )

    result = run(configured_interpreter(transport).interpret(request))

    assert transport.calls == [False, False]
    assert result.control.kind == expected_kind
    assert (result.intent_delta is not None) is has_delta


def test_refer_is_nonconsequential_for_fallback_and_configured_paths() -> None:
    request = interpretation_request(
        "that one",
        candidate_target_ids=["reference-1"],
        active_intent_id=None,
    )
    fallback_result = run(ControlInterpreter(settings()).interpret(request))

    transport = SequenceTransport(
        [control_output("REFER", consequential=True, target_refs=["reference-1"])]
    )
    configured_result = run(configured_interpreter(transport).interpret(request))

    assert fallback_result.control.kind == ControlKind.REFER
    assert configured_result.control.kind == ControlKind.REFER
    assert fallback_result.control.consequential is False
    assert configured_result.control.consequential is False


def test_stop_explaining_only_cancels_speech() -> None:
    result = run(
        ControlInterpreter(settings()).interpret(
            interpretation_request("Stop explaining.")
        )
    )

    assert result.control.kind == ControlKind.CANCEL_SPEECH
    assert result.intent_delta is None


def test_ambiguous_stop_clarifies() -> None:
    result = run(
        ControlInterpreter(settings()).interpret(interpretation_request("Stop it."))
    )

    assert result.control.kind == ControlKind.CLARIFY
    assert result.intent_delta is None


def test_booking_retraction_uses_only_trusted_booking_goal_id() -> None:
    result = run(
        ControlInterpreter(settings()).interpret(
            interpretation_request(
                "No, don't book it",
                context={"retractable_goal_ids": {"booking": "goal-booking"}},
            )
        )
    )

    assert result.control.kind == ControlKind.RETRACT_GOAL
    assert result.intent_delta is not None
    assert result.intent_delta.target_intent_id == "intent-1"
    assert result.intent_delta.retract_goals == ["goal-booking"]
    assert "intent-1" not in result.intent_delta.retract_goals


def test_missing_booking_goal_id_clarifies_without_delta() -> None:
    result = run(
        ControlInterpreter(settings()).interpret(
            interpretation_request("No, don't book it")
        )
    )

    assert result.control.kind == ControlKind.CLARIFY
    assert result.intent_delta is None


def test_fallback_correction_with_trusted_context_produces_delta() -> None:
    result = run(
        ControlInterpreter(settings()).interpret(
            interpretation_request(
                "Actually make it 12",
                candidate_target_ids=["intent-1"],
                context={"correction_field": "time"},
            )
        )
    )

    assert result.control.kind == ControlKind.CORRECT
    assert result.intent_delta is not None
    assert result.intent_delta.set_fields == {"time": "12"}
    assert result.intent_delta.confidence > 0.85


def test_low_confidence_consequential_control_clarifies() -> None:
    transport = SequenceTransport(
        [control_output("PAUSE", confidence=0.50, consequential=True)]
    )

    result = run(
        configured_interpreter(transport).interpret(
            interpretation_request("pause", active_intent_id=None)
        )
    )

    assert result.control.kind == ControlKind.CLARIFY
    assert result.intent_delta is None


def test_model_cannot_downgrade_canonical_consequential_control() -> None:
    transport = SequenceTransport(
        [
            control_output(
                "CORRECT",
                consequential=False,
                target_refs=["intent-1"],
            ),
            delta_output(0.96),
        ]
    )

    result = run(
        configured_interpreter(transport).interpret(
            interpretation_request("Change time to 12")
        )
    )

    assert result.control.kind == ControlKind.CORRECT
    assert result.control.consequential is True
    assert result.intent_delta is not None


def test_malformed_json_receives_only_one_format_repair() -> None:
    transport = SequenceTransport(
        ["{malformed", control_output("BACKCHANNEL", consequential=False)]
    )
    request = provider_request(ProviderTask.CONTROL_V1, {"candidate_ids": []})

    result = run(StructuredModelProvider(transport).invoke(request))

    assert not isinstance(result, ProviderFailure)
    assert result.repaired is True
    assert transport.calls == [False, True]


def test_timeout_receives_zero_repair_attempts() -> None:
    transport = SequenceTransport([asyncio.TimeoutError()])
    request = provider_request(ProviderTask.CONTROL_V1, {"candidate_ids": []})

    result = run(StructuredModelProvider(transport).invoke(request))

    assert isinstance(result, ProviderFailure)
    assert result.kind == ProviderFailureKind.TIMEOUT
    assert result.repair_attempted is False
    assert transport.calls == [False]


def test_invalid_control_kind_is_policy_failure_without_repair() -> None:
    transport = SequenceTransport([control_output("DELETE_BOOKING")])
    request = provider_request(ProviderTask.CONTROL_V1, {"candidate_ids": []})

    result = run(StructuredModelProvider(transport).invoke(request))

    assert isinstance(result, ProviderFailure)
    assert result.kind == ProviderFailureKind.INVALID_OUTPUT
    assert result.repair_attempted is False
    assert transport.calls == [False]


def test_extra_authorization_field_is_rejected_without_repair() -> None:
    output = control_output("PAUSE")
    output["authorized"] = True
    transport = SequenceTransport([output])
    request = provider_request(ProviderTask.CONTROL_V1, {"candidate_ids": []})

    result = run(StructuredModelProvider(transport).invoke(request))

    assert isinstance(result, ProviderFailure)
    assert result.kind == ProviderFailureKind.INVALID_OUTPUT
    assert result.repair_attempted is False
    assert transport.calls == [False]


@pytest.mark.parametrize(
    "bad_value",
    [
        pytest.param(b"raw", id="bytes"),
        pytest.param({1, 2}, id="set"),
        pytest.param(object(), id="object"),
        pytest.param(float("nan"), id="nan"),
        pytest.param(float("inf"), id="positive-infinity"),
        pytest.param(float("-inf"), id="negative-infinity"),
        pytest.param({1: "non-string-key"}, id="non-string-key"),
    ],
)
def test_non_json_model_output_fails_closed_without_repair(bad_value: Any) -> None:
    transport = SequenceTransport([delta_output(0.95, bad_value)])
    request = provider_request(
        ProviderTask.DELTA_V1,
        {"allowed_target_intent_ids": ["intent-1"]},
    )

    result = run(StructuredModelProvider(transport).invoke(request))

    assert isinstance(result, ProviderFailure)
    assert result.kind == ProviderFailureKind.INVALID_OUTPUT
    assert result.repair_attempted is False
    assert transport.calls == [False]


def test_ext001_demo_retains_late_world_effect_after_correction() -> None:
    async def scenario() -> None:
        host = create_demo_asgi_app(Settings(
            INTERLOCK_MODE="DEMO",
            INTERLOCK_MODEL_PROVIDER="fallback",
            INTERLOCK_FAKE_LATENCY_MS=150,
        ))
        application = host.application
        session_id = "ext001-regression"
        await application.start_session(session_id)
        try:
            await application.append(EventCandidate(
                session_id=session_id,
                event_type="UserInputObserved",
                source=EventSource.INPUT_ADAPTER,
                payload={
                    "evidence_id": "input-11",
                    "modality": "text",
                    "content_ref": "Book 11:00.",
                },
                correlation_id="input-11",
                dedupe_key="test:input-11",
            ))
            for _ in range(100):
                operations = application.snapshot(session_id).operations.values()
                if any(operation.state == OperationState.DISPATCHED for operation in operations):
                    break
                await asyncio.sleep(0.005)
            else:
                pytest.fail("demo operation did not cross SAFEPOINT")

            await application.append(EventCandidate(
                session_id=session_id,
                event_type="UserInputObserved",
                source=EventSource.INPUT_ADAPTER,
                payload={
                    "evidence_id": "input-12",
                    "modality": "text",
                    "content_ref": "Actually, make it 12:00.",
                },
                correlation_id="input-12",
                dedupe_key="test:input-12",
            ))
            await asyncio.sleep(0.2)
            await application.drain(session_id)
            await asyncio.sleep(0)
            await application.drain(session_id)
            state = application.snapshot(session_id)
            active = state.revisions[state.intents[state.active_intent_id].active_revision_id]
            assert active.values["requested_slot"] == "2030-01-15T12:00:00+05:30"
            assert any(
                effect.parameters["confirmed_slot"] == "2030-01-15T11:00:00+05:30"
                for effect in state.effects.values()
            )
            assert any(operation.cancellation_state == "TOO_LATE"
                       for operation in state.operations.values())
            assert len(state.divergences) == 1
            assert any(
                claim.intent_revision_id == active.revision_id and claim.state == "PENDING"
                for claim in state.claims.values()
            )
            assert all(speech.heard is False for speech in state.speech.values())
        finally:
            await application.close()
            await host.output.shutdown()
            await host.hub.shutdown()

    run(scenario())


def test_ext001_demo_divergence_detected_when_correction_arrives_after_world_effect() -> None:
    async def scenario() -> None:
        host = create_demo_asgi_app(Settings(
            INTERLOCK_MODE="DEMO",
            INTERLOCK_MODEL_PROVIDER="fallback",
            INTERLOCK_FAKE_LATENCY_MS=50,
        ))
        application = host.application
        session_id = "ext001-case-b-regression"
        await application.start_session(session_id)
        try:
            await application.append(EventCandidate(
                session_id=session_id,
                event_type="UserInputObserved",
                source=EventSource.INPUT_ADAPTER,
                payload={
                    "evidence_id": "input-11",
                    "modality": "text",
                    "content_ref": "Book 11:00.",
                },
                correlation_id="input-11",
                dedupe_key="test:input-11",
            ))
            await asyncio.sleep(0.1)
            await application.drain(session_id)
            state1 = application.snapshot(session_id)
            assert any(
                effect.parameters.get("confirmed_slot") == "2030-01-15T11:00:00+05:30"
                for effect in state1.effects.values()
            )
            assert len(state1.divergences) == 0

            await application.append(EventCandidate(
                session_id=session_id,
                event_type="UserInputObserved",
                source=EventSource.INPUT_ADAPTER,
                payload={
                    "evidence_id": "input-12",
                    "modality": "text",
                    "content_ref": "Actually, make it 12:00.",
                },
                correlation_id="input-12",
                dedupe_key="test:input-12",
            ))
            await asyncio.sleep(0.1)
            await application.drain(session_id)
            state2 = application.snapshot(session_id)
            active = state2.revisions[state2.intents[state2.active_intent_id].active_revision_id]
            assert active.values["requested_slot"] == "2030-01-15T12:00:00+05:30"
            assert any(
                effect.parameters.get("confirmed_slot") == "2030-01-15T11:00:00+05:30"
                for effect in state2.effects.values()
            )
            assert len(state2.divergences) == 1
            divergence = next(iter(state2.divergences.values()))
            assert divergence.state == "OPEN"
            assert any(
                claim.intent_revision_id == active.revision_id and claim.state == "PENDING"
                for claim in state2.claims.values()
            )
            assert any(
                speech.act_type == "UNCERTAINTY"
                for speech in state2.speech.values()
            )
        finally:
            await application.close()
            await host.output.shutdown()
            await host.hub.shutdown()

    run(scenario())


def test_ext001_demo_reset_clears_provider_state_and_allows_rebooking() -> None:
    async def scenario() -> None:
        from httpx import ASGITransport, AsyncClient

        host = create_demo_asgi_app(Settings(
            INTERLOCK_MODE="DEMO",
            INTERLOCK_MODEL_PROVIDER="fallback",
            INTERLOCK_FAKE_LATENCY_MS=50,
        ))
        transport = ASGITransport(app=host)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            res = await client.post("/api/v1/sessions", json={"mode": "DEMO", "client_request_id": "req-a"})
            assert res.status_code == 201
            session_a_id = res.json()["session_id"]

            res = await client.post(
                f"/api/v1/sessions/{session_a_id}/inputs",
                json={"modality": "TEXT", "content": "Book 11:00.", "client_request_id": "in-a-1"},
            )
            assert res.status_code == 202
            await asyncio.sleep(0.1)
            await host.application.drain(session_a_id)

            assert any(
                b.get("confirmed_slot") == "2030-01-15T11:00:00+05:30"
                for b in host.provider.bookings.values()
            )

            res = await client.post(
                f"/api/v1/sessions/{session_a_id}/demo/reset",
                json={"fixture_id": "samsung-demo-v1", "client_request_id": "reset-1"},
            )
            assert res.status_code == 200
            session_b_id = res.json()["session_id"]
            assert session_b_id != session_a_id

            assert len(host.provider.bookings) == 0

            res = await client.post(
                f"/api/v1/sessions/{session_b_id}/inputs",
                json={"modality": "TEXT", "content": "Book 11:00.", "client_request_id": "in-b-1"},
            )
            assert res.status_code == 202
            await asyncio.sleep(0.1)
            await host.application.drain(session_b_id)

            state_b = host.application.snapshot(session_b_id)
            assert any(
                op.tool_name == "appointment.book" and op.state == OperationState.SUCCEEDED
                for op in state_b.operations.values()
            )
            assert any(
                effect.parameters.get("confirmed_slot") == "2030-01-15T11:00:00+05:30"
                for effect in state_b.effects.values()
            )

            bad_reset = await client.post(
                f"/api/v1/sessions/{session_b_id}/demo/reset",
                json={"fixture_id": "unknown-fixture", "client_request_id": "bad-reset-1"},
            )
            assert bad_reset.status_code == 422

        await host.application.close()
        await host.output.shutdown()
        await host.hub.shutdown()

    run(scenario())


def test_normal_booking_claim_confirmed_with_canonical_evidence_and_truth_gated_speech() -> None:
    async def scenario() -> None:
        host = create_demo_asgi_app(Settings(
            INTERLOCK_MODE="DEMO",
            INTERLOCK_MODEL_PROVIDER="fallback",
            INTERLOCK_FAKE_LATENCY_MS=50,
        ))
        application = host.application
        session_id = "normal-booking-p0-regression"
        await application.start_session(session_id)
        try:
            await application.append(EventCandidate(
                session_id=session_id,
                event_type="UserInputObserved",
                source=EventSource.INPUT_ADAPTER,
                payload={
                    "evidence_id": "input-11",
                    "modality": "text",
                    "content_ref": "Book 11:00.",
                },
                correlation_id="input-11",
                dedupe_key="test:input-11",
            ))

            # Wait for operation to execute and settle
            await asyncio.sleep(0.15)
            await application.drain(session_id)

            state = application.snapshot(session_id)
            active_node = state.intents.get(state.active_intent_id)
            assert active_node is not None
            active_rev = state.revisions.get(active_node.active_revision_id)
            assert active_rev is not None
            assert active_rev.values["requested_slot"] == "2030-01-15T11:00:00+05:30"

            # 1. Operation SUCCEEDED
            assert any(
                op.tool_name == "appointment.book" and op.state == OperationState.SUCCEEDED
                for op in state.operations.values()
            )

            # 2. Authoritative COMMITTED effect exists for exact 11
            effects = [
                eff for eff in state.effects.values()
                if eff.effect_type == "appointment.booking"
                and eff.state == "COMMITTED"
                and eff.authority == "AUTHORITATIVE"
                and eff.parameters.get("confirmed_slot") == "2030-01-15T11:00:00+05:30"
            ]
            assert len(effects) >= 1

            # 3. appointment_booked claim for active revision becomes CONFIRMED with canonical evidence
            active_claims = [
                claim for claim in state.claims.values()
                if claim.intent_revision_id == active_rev.revision_id
                and claim.predicate == "appointment_booked"
            ]
            assert len(active_claims) == 1
            claim = active_claims[0]
            assert claim.state == "CONFIRMED"
            assert len(claim.supporting_evidence_ids) > 0
            assert all(eid in state.evidence for eid in claim.supporting_evidence_ids)

            # 4. TRUTHLOCK-approved RESULT speech exists with exact template wording
            result_speeches = [
                s for s in state.speech.values()
                if s.act_type == "RESULT" and claim.claim_id in s.claim_ids
            ]
            assert len(result_speeches) == 1
            speech = result_speeches[0]
            assert speech.state in ("APPROVED", "QUEUED", "EMITTING", "EMITTED")
            assert speech.rendered_text == "Confirmed — your 11:00 appointment is booked."
        finally:
            await application.close()
            await host.output.shutdown()
            await host.hub.shutdown()

    run(scenario())


def test_race_11_to_12_never_produces_confirmed_12_speech() -> None:
    async def scenario() -> None:
        host = create_demo_asgi_app(Settings(
            INTERLOCK_MODE="DEMO",
            INTERLOCK_MODEL_PROVIDER="fallback",
            INTERLOCK_FAKE_LATENCY_MS=50,
        ))
        application = host.application
        session_id = "race-11-12-regression"
        await application.start_session(session_id)
        try:
            # 1. User requests 11:00
            await application.append(EventCandidate(
                session_id=session_id,
                event_type="UserInputObserved",
                source=EventSource.INPUT_ADAPTER,
                payload={
                    "evidence_id": "input-11",
                    "modality": "text",
                    "content_ref": "Book 11:00.",
                },
                correlation_id="input-11",
                dedupe_key="test:input-11",
            ))
            await asyncio.sleep(0.1)
            await application.drain(session_id)

            # 2. Interruption with 12:00 arrives
            await application.append(EventCandidate(
                session_id=session_id,
                event_type="UserInputObserved",
                source=EventSource.INPUT_ADAPTER,
                payload={
                    "evidence_id": "input-12",
                    "modality": "text",
                    "content_ref": "Actually, make it 12:00.",
                },
                correlation_id="input-12",
                dedupe_key="test:input-12",
            ))

            await asyncio.sleep(0.1)
            await application.drain(session_id)

            state = application.snapshot(session_id)
            active_node = state.intents.get(state.active_intent_id)
            assert active_node is not None
            active_rev = state.revisions.get(active_node.active_revision_id)
            assert active_rev is not None
            assert active_rev.values["requested_slot"] == "2030-01-15T12:00:00+05:30"

            # Claim for 12:00 must NEVER be CONFIRMED without 12:00 evidence
            claim_12 = [
                c for c in state.claims.values()
                if c.intent_revision_id == active_rev.revision_id
                and c.predicate == "appointment_booked"
            ]
            assert len(claim_12) == 1
            assert claim_12[0].state == "PENDING"

            # No speech asserting 12:00 confirmed can exist
            confirmed_12_speeches = [
                s for s in state.speech.values()
                if s.act_type == "RESULT" and "12:00" in (s.rendered_text or "")
            ]
            assert len(confirmed_12_speeches) == 0

            # Active divergence exists
            assert len(state.divergences) >= 1
        finally:
            await application.close()
            await host.output.shutdown()
            await host.hub.shutdown()

    run(scenario())


def test_claims_match_slot_strict_canonical_equality() -> None:
    from interlock.truth.claims import _match_slot, ClaimEvaluator
    from interlock.domain.models import ClaimRecord, EffectRecord
    from interlock.domain.enums import ClaimState, EffectState, EvidenceAuthority

    # 1. Bare time string "11:00" must NEVER match full ISO datetime
    assert not _match_slot("11:00", "2030-01-15T11:00:00+05:30")
    assert not _match_slot("2030-01-15T11:00:00+05:30", "11:00")

    # 2. Same time-of-day on a different date must NEVER match
    assert not _match_slot("2030-01-15T11:00:00+05:30", "2030-01-16T11:00:00+05:30")
    assert not _match_slot("2030-01-16T11:00:00+05:30", "2030-01-15T11:00:00+05:30")

    # 3. Same time-of-day on a different timezone offset must NEVER match (different instant)
    assert not _match_slot("2030-01-15T11:00:00+05:30", "2030-01-15T11:00:00+00:00")
    assert not _match_slot("2030-01-15T11:00:00+05:30", "2030-01-15T11:00:00-05:00")

    # 4. Offset-naive vs offset-aware must fail closed
    assert not _match_slot("2030-01-15T11:00:00", "2030-01-15T11:00:00+05:30")

    # 5. Positive canonical controls
    assert _match_slot("2030-01-15T11:00:00+05:30", "2030-01-15T11:00:00+05:30")
    assert _match_slot("2030-01-15T05:30:00Z", "2030-01-15T11:00:00+05:30")

    # 6. Integration: ClaimEvaluator must NOT confirm a claim when world effect has same time on different date
    evaluator = ClaimEvaluator()
    claim = ClaimRecord(
        claim_id="claim-test-slot-mismatch",
        predicate="appointment_booked",
        subject={"center_id": "center-1"},
        object={
            "requested_slot": "2030-01-15T11:00:00+05:30",
            "provider_booking_id": "booking-99",
        },
        state=ClaimState.PROPOSED,
        required_evidence_rule="appointment_booked",
        intent_revision_id="rev-1",
        updated_by_event_id="ev-1",
    )
    from datetime import datetime, timezone

    mismatched_effect = EffectRecord(
        effect_id="eff-slot-mismatch",
        operation_id="op-1",
        logical_action_id="action-1",
        provider_effect_id="prov-eff-1",
        effect_type="appointment.booking",
        subject={"center_id": "center-1"},
        parameters={
            "confirmed_slot": "2030-01-16T11:00:00+05:30",
            "provider_booking_id": "booking-99",
        },
        state=EffectState.COMMITTED,
        observed_at=datetime(2030, 1, 16, 11, 0, tzinfo=timezone.utc),
        authority=EvidenceAuthority.AUTHORITATIVE,
        evidence_ids=["ev-1"],
    )
    events = evaluator.evaluate(
        claim,
        effects={"eff-slot-mismatch": mismatched_effect},
        evidence={},
        active_intent_revision_id="rev-1",
    )
    assert not any(event.to_state in (ClaimState.CONFIRMED, "CONFIRMED") for event in events)
    assert any(event.to_state in (ClaimState.PENDING, "PENDING") for event in events)


def test_truthlock_controlled_template_slot_formatting_and_identity() -> None:
    from interlock.truth.truthlock import (
        _format_display_slot,
        _speech_slot_matches_claim,
        _render_template,
        CONTROLLED_TEMPLATES,
    )

    # 1. Format canonical ISO slot to human display time
    assert _format_display_slot("2030-01-15T11:00:00+05:30") == "11:00"
    assert _format_display_slot("11:00") == "11:00"

    # 2. Speech slot validation accepts canonical identity or display time matching approved claim
    assert _speech_slot_matches_claim("2030-01-15T11:00:00+05:30", "2030-01-15T11:00:00+05:30")
    assert _speech_slot_matches_claim("11:00", "2030-01-15T11:00:00+05:30")
    assert not _speech_slot_matches_claim("12:00", "2030-01-15T11:00:00+05:30")
    assert not _speech_slot_matches_claim("2030-01-16T11:00:00+05:30", "2030-01-15T11:00:00+05:30")

    # 3. Controlled template renders approved slot formatted for display
    tmpl = CONTROLLED_TEMPLATES["tmpl_booking_confirmed"]
    rendered = _render_template(tmpl, {"slot": "2030-01-15T11:00:00+05:30"}, supported_slot="2030-01-15T11:00:00+05:30")
    assert rendered == "Confirmed — your 11:00 appointment is booked."


def test_g03_correction_after_commit_emits_open_divergence_when_authorization_not_requested() -> None:
    """TST-003 G-03: committed correction changes desired state after world effect commits.

    Verifies points A-F:
    A. effect 11 exists first (committed, authoritative)
    B. child revision 12 commits directly with authorization NOT_REQUESTED
    C. OPEN divergence is emitted (DESIRED_SLOT_DIFFERS_FROM_CONFIRMED_SLOT)
    D. no new booking dispatch for 12
    E. no confirmed-12 claim/speech, safe uncertainty speech only
    F. world 11 remains authoritative, no 12 effect fabricated
    """
    from interlock.domain.enums import (
        Authorization,
        ClaimState,
        DivergenceState,
        EffectState,
        EvidenceAuthority,
        IntentMaturity,
        SpeechActType,
    )
    from interlock.domain.models import IntentRevision
    from interlock.intelligence.intent_graph import bind_dependencies, dependency_fingerprint
    from interlock.main import _identity

    async def scenario() -> None:
        host = create_demo_asgi_app(Settings(
            INTERLOCK_MODE="DEMO",
            INTERLOCK_MODEL_PROVIDER="fallback",
            INTERLOCK_FAKE_LATENCY_MS=50,
        ))
        application = host.application
        session_id = "tst003-g03-regression"
        await application.start_session(session_id)
        try:
            # 1. Normal booking for 11:00 completes and world effect 11:00 is committed
            await application.append(EventCandidate(
                session_id=session_id,
                event_type="UserInputObserved",
                source=EventSource.INPUT_ADAPTER,
                payload={
                    "evidence_id": "input-11",
                    "modality": "text",
                    "content_ref": "Book 11:00.",
                },
                correlation_id="input-11",
                dedupe_key="test:input-11",
            ))
            await asyncio.sleep(0.1)
            await application.drain(session_id)

            # Point A: Effect 11 exists first, committed and authoritative
            state1 = application.snapshot(session_id)
            effects_11 = [
                e for e in state1.effects.values()
                if e.state == EffectState.COMMITTED
                and e.authority == EvidenceAuthority.AUTHORITATIVE
                and (e.parameters.get("confirmed_slot") == "2030-01-15T11:00:00+05:30"
                     or e.parameters.get("requested_slot") == "2030-01-15T11:00:00+05:30")
            ]
            assert len(effects_11) >= 1
            effect_11 = effects_11[0]
            assert len(state1.divergences) == 0

            # Root revision that was active
            active_intent = state1.intents[state1.active_intent_id]
            root_rev = state1.revisions[active_intent.active_revision_id]

            # Point B: Child revision 12 commits directly with authorization NOT_REQUESTED
            # (No IntentAuthorizationChanged is emitted, matching TST-003 G-03 contract)
            rev12_id = "rev-child-12-unauthorized"
            rev12_values = {
                "goal_type": "appointment_booking",
                "center_id": "ctr-01",
                "requested_slot": "2030-01-15T12:00:00+05:30",
            }
            rev12_fingerprint = dependency_fingerprint(
                bind_dependencies(rev12_values, sorted(rev12_values))
            )
            child_revision = IntentRevision(
                revision_id=rev12_id,
                intent_id=root_rev.intent_id,
                parent_revision_id=root_rev.revision_id,
                values=rev12_values,
                maturity=IntentMaturity.COMMITTED,
                authorization=Authorization.NOT_REQUESTED,
                created_by_event_id="evt-commit-12",
                dependency_fingerprint=rev12_fingerprint,
            )
            await application.append(EventCandidate(
                session_id=session_id,
                event_type="IntentRevisionCommitted",
                source=EventSource.MODEL,
                payload={"revision": child_revision.model_dump(mode="json")},
                correlation_id="input-12",
                identity=_identity(rev12_id, "commit"),
            ))
            await asyncio.sleep(0.1)
            await application.drain(session_id)

            state2 = application.snapshot(session_id)
            active_rev = state2.revisions[state2.intents[state2.active_intent_id].active_revision_id]
            assert active_rev.revision_id == rev12_id
            assert active_rev.authorization == Authorization.NOT_REQUESTED
            assert active_rev.values["requested_slot"] == "2030-01-15T12:00:00+05:30"

            # Point C: OPEN divergence is emitted
            assert len(state2.divergences) == 1
            divergence = next(iter(state2.divergences.values()))
            assert divergence.state == DivergenceState.OPEN
            assert divergence.kind == "DESIRED_SLOT_DIFFERS_FROM_CONFIRMED_SLOT"
            assert effect_11.effect_id in divergence.observed_effect_ids
            assert divergence.desired_fingerprint == rev12_fingerprint

            # Point D: No new booking dispatch for 12
            ops_12 = [
                op for op in state2.operations.values()
                if op.intent_revision_id == rev12_id
            ]
            assert len(ops_12) == 0

            # Point E: No confirmed-12 claim / speech
            claims_12_confirmed = [
                c for c in state2.claims.values()
                if c.intent_revision_id == rev12_id and c.state == ClaimState.CONFIRMED
            ]
            assert len(claims_12_confirmed) == 0

            speech_12_confirmed = [
                s for s in state2.speech.values()
                if s.act_type == SpeechActType.RESULT and "12:00" in (s.rendered_text or "")
            ]
            assert len(speech_12_confirmed) == 0

            # Safe uncertainty speech is proposed instead
            uncertainty_speeches = [
                s for s in state2.speech.values()
                if s.act_type == SpeechActType.UNCERTAINTY
            ]
            assert len(uncertainty_speeches) >= 1

            # Point F: World 11 remains authoritative
            current_effect_11 = state2.effects.get(effect_11.effect_id)
            assert current_effect_11 is not None
            assert current_effect_11.state == EffectState.COMMITTED
            assert current_effect_11.authority == EvidenceAuthority.AUTHORITATIVE
            assert (current_effect_11.parameters.get("confirmed_slot") == "2030-01-15T11:00:00+05:30"
                    or current_effect_11.parameters.get("requested_slot") == "2030-01-15T11:00:00+05:30")

            # No 12:00 world effect was fabricated
            effects_12 = [
                e for e in state2.effects.values()
                if (e.parameters.get("confirmed_slot") == "2030-01-15T12:00:00+05:30"
                    or e.parameters.get("requested_slot") == "2030-01-15T12:00:00+05:30")
            ]
            assert len(effects_12) == 0
        finally:
            await application.close()
            await host.output.shutdown()
            await host.hub.shutdown()

    run(scenario())
