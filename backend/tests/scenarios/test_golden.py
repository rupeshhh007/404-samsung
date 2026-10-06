"""T-OFF-01, T-OBS-01, T-SCN-01, T-E2E-01, T-INV-I6-P,
T-INV-I9-P: credential-free normal booking and trace.
"""

import asyncio
from pathlib import Path
import pytest

from interlock.config import Settings
from interlock.domain.enums import EventSource
from interlock.main import create_demo_asgi_app
from interlock.runtime.journal import EventCandidate
from interlock.testing.scenario import ScenarioRunner, parse_scenario


_NORMAL = Path(__file__).resolve().parents[2] / "scenarios" / "normal.yaml"


@pytest.mark.parametrize("slot", ["11:00", "12:00"])
def test_t_off_01_t_e2e_01_normal_booking_uses_real_offline_runtime(slot):
    async def run():
        host = create_demo_asgi_app(Settings(
            _env_file=None, INTERLOCK_MODE="DEMO",
            INTERLOCK_MODEL_PROVIDER="fallback", INTERLOCK_FAKE_LATENCY_MS=0,
        ))
        app = host.application
        await app.start_session("golden")
        try:
            await app.append(EventCandidate(
                session_id="golden", event_type="UserInputObserved",
                source=EventSource.INPUT_ADAPTER,
                payload={"evidence_id": "input", "modality": "text",
                         "content_ref": f"Book {slot}."},
                correlation_id="input", dedupe_key="golden:input",
            ))
            for _ in range(80):
                await app.drain("golden")
                state = app.snapshot("golden")
                if any(claim.state == "CONFIRMED" for claim in state.claims.values()):
                    break
                await asyncio.sleep(0)
            else:
                raise AssertionError("normal booking did not reach confirmed claim")
            committed = [
                effect for effect in state.effects.values()
                if effect.state == "COMMITTED"
            ]
            assert len(committed) == 1
            assert committed[0].authority == "AUTHORITATIVE"
            assert committed[0].parameters["requested_slot"].endswith(
                f"T{slot}:00+05:30"
            )
            assert committed[0].parameters["confirmed_slot"].endswith(
                f"T{slot}:00+05:30"
            )
            if slot == "12:00":
                assert committed[0].provider_effect_id == "apt-12"
            confirmed_claims = [
                claim for claim in state.claims.values()
                if claim.state == "CONFIRMED"
            ]
            assert confirmed_claims
            assert all(
                evidence_id in state.evidence
                for claim in confirmed_claims
                for evidence_id in claim.supporting_evidence_ids
            )
            assert any(speech.rendered_text
                       and speech.rendered_text.startswith("Confirmed")
                       and f"{slot} appointment is booked." in speech.rendered_text
                       for speech in state.speech.values())
            event_types = [event.event_type for event in app.events("golden")]
            events = app.events("golden")
            confirmed = next(
                index for index, event in enumerate(events)
                if event.event_type == "ClaimStateChanged"
                and event.payload.get("to_state") == "CONFIRMED"
            )
            ordered = [
                "UserInputObserved", "IntentRevisionCommitted",
                "IntentAuthorizationChanged", "OperationPrepared",
                "ToolDispatchRequested", "ToolDispatchAccepted",
                "ToolResultObserved", "WorldEffectObserved",
            ]
            positions = [event_types.index(kind) for kind in ordered]
            positions.extend([confirmed, event_types.index("SpeechActApproved")])
            assert positions == sorted(positions)
            assert event_types.index("WorldEffectObserved") < confirmed
            assert confirmed < event_types.index("SpeechActApproved")
            event_ids = {event.event_id for event in events}
            assert all(event.causation_id in event_ids for event in events
                       if event.causation_id is not None)
            by_id = {event.event_id: event for event in events}
            current = next(e for e in reversed(events) if e.event_type == "SpeechEmissionFinished")
            trace_types = []
            while current and current.causation_id:
                current = by_id.get(current.causation_id)
                if current:
                    trace_types.append(current.event_type)
            assert "UserInputObserved" in trace_types
            assert "IntentAuthorizationChanged" in trace_types
            assert "OperationCreated" in trace_types
            assert "OperationPrepared" in trace_types
            assert "ToolDispatchRequested" in trace_types
            assert "ToolResultObserved" in trace_types
            assert "WorldEffectObserved" in trace_types
            assert "ClaimStateChanged" in trace_types
        finally:
            await app.close()
            await host.output.shutdown()
            await host.hub.shutdown()
    asyncio.run(run())


def test_t_scn_01_same_scenario_uses_same_virtual_input_and_checkpoint_order():
    raw = _NORMAL.read_text(encoding="utf-8")
    assert parse_scenario(raw).scenario_id == "normal-booking"

    async def execute():
        observed = []

        class Driver:
            def setup(self, scenario, clock):
                observed.append(("setup", scenario.scenario_id, clock.now()))

            def deliver_input(self, input_payload, clock):
                observed.append(("input", input_payload["text"], clock.now()))

            def assert_checkpoint(self, assertion, clock):
                observed.append(("checkpoint", assertion["provider_write_count"], clock.now()))

            def assert_final(self, expectation, clock):
                observed.append(("final", expectation["provider_write_count"], clock.now()))

        await ScenarioRunner(raw, Driver()).run()
        return observed

    first = asyncio.run(execute())
    second = asyncio.run(execute())
    assert first == second
    assert first[-1] == ("final", 1, 300)
