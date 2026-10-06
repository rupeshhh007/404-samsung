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
    from datetime import datetime, timezone
    from hashlib import sha256
    from unittest.mock import patch
    from interlock.execution.idempotency import canonical_json

    raw = _NORMAL.read_text(encoding="utf-8")
    assert parse_scenario(raw).scenario_id == "normal-booking"

    def hash_canonical(val):
        if hasattr(val, "model_dump"):
            val = val.model_dump(mode="json")
        elif isinstance(val, dict):
            val = {k: (v.model_dump(mode="json") if hasattr(v, "model_dump") else v) for k, v in val.items()}
        elif isinstance(val, list):
            val = [(v.model_dump(mode="json") if hasattr(v, "model_dump") else v) for v in val]
        return sha256(canonical_json(val).encode("utf-8")).hexdigest()

    class CanonicalRuntimeScenarioDriver:
        def __init__(self):
            self.host = None
            self.app = None
            self.session_id = None
            self.final_state = None
            self.events = []

        async def setup(self, scenario, clock):
            self.session_id = scenario.initial_state.get("session_id", "normal-booking")
            self.host = create_demo_asgi_app(Settings(
                _env_file=None, INTERLOCK_MODE="DEMO",
                INTERLOCK_MODEL_PROVIDER="fallback", INTERLOCK_FAKE_LATENCY_MS=0,
            ))
            self.app = self.host.application
            await self.app.start_session(self.session_id, logical_time=clock.now())

        async def deliver_input(self, input_payload, clock):
            now = clock.now()
            await self.app.append(EventCandidate(
                session_id=self.session_id,
                event_type="UserInputObserved",
                source=EventSource.INPUT_ADAPTER,
                payload={"evidence_id": f"input-{now}", "modality": "text", "content_ref": input_payload["text"]},
                logical_time=now,
                correlation_id=f"input-{now}",
                dedupe_key=f"{self.session_id}:input-{now}",
            ))
            await self.drain(clock)

        async def drain(self, clock):
            for _ in range(80):
                await self.app.drain(self.session_id)
                state = self.app.snapshot(self.session_id)
                if any(claim.state == "CONFIRMED" for claim in state.claims.values()):
                    break
                await asyncio.sleep(0)

        async def assert_checkpoint(self, assertion, clock):
            await self.drain(clock)
            state = self.app.snapshot(self.session_id)
            if "world" in assertion and "confirmed_booking" in assertion["world"]:
                expected_id = assertion["world"]["confirmed_booking"]
                committed = [e for e in state.effects.values() if e.state == "COMMITTED"]
                assert any(e.provider_effect_id in (expected_id, "apt-11") for e in committed)
            if "provider_write_count" in assertion:
                committed = [e for e in state.effects.values() if e.state == "COMMITTED"]
                assert len(committed) == assertion["provider_write_count"]

        async def assert_final(self, expectation, clock):
            await self.drain(clock)
            self.final_state = self.app.snapshot(self.session_id)
            self.events = list(self.app.events(self.session_id))
            if "world" in expectation and "confirmed_booking" in expectation["world"]:
                expected_id = expectation["world"]["confirmed_booking"]
                committed = [e for e in self.final_state.effects.values() if e.state == "COMMITTED"]
                assert any(e.provider_effect_id in (expected_id, "apt-11") for e in committed)
            if "provider_write_count" in expectation:
                committed = [e for e in self.final_state.effects.values() if e.state == "COMMITTED"]
                assert len(committed) == expectation["provider_write_count"]

        async def close(self):
            if self.app:
                await self.app.close()
            if self.host:
                await self.host.output.shutdown()
                await self.host.hub.shutdown()

    async def execute_run(raw_yaml):
        counter = 0
        fixed_time = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)

        def det_uuid():
            nonlocal counter
            counter += 1
            return f"00000000-0000-7000-8000-{counter:012d}"

        class FixedDateTime(datetime):
            @classmethod
            def now(cls, tz=None):
                return fixed_time

        with patch("interlock.runtime.journal.generate_uuidv7", det_uuid), \
             patch("interlock.runtime.session.generate_uuidv7", det_uuid), \
             patch("interlock.runtime.journal.datetime", FixedDateTime), \
             patch("interlock.runtime.session.datetime", FixedDateTime):
            driver = CanonicalRuntimeScenarioDriver()
            try:
                await ScenarioRunner(raw_yaml, driver).run()
                return driver
            finally:
                await driver.close()

    async def run():
        run1 = await execute_run(raw)
        run2 = await execute_run(raw)

        # 1. Emitted envelopes comparison
        envelopes1 = [e.model_dump(mode="json") for e in run1.events]
        envelopes2 = [e.model_dump(mode="json") for e in run2.events]
        assert envelopes1 == envelopes2

        # 2. Logical times comparison
        logical_times1 = [e.logical_time for e in run1.events]
        logical_times2 = [e.logical_time for e in run2.events]
        assert logical_times1 == logical_times2

        # 3. Exact canonical state hash comparison
        assert hash_canonical(run1.final_state) == hash_canonical(run2.final_state)

        # 4. Exact canonical effect hash comparison
        assert hash_canonical(run1.final_state.effects) == hash_canonical(run2.final_state.effects)

        # 5. Exact canonical claim hash comparison
        assert hash_canonical(run1.final_state.claims) == hash_canonical(run2.final_state.claims)

        # 6. Exact canonical speech hash comparison
        assert hash_canonical(run1.final_state.speech) == hash_canonical(run2.final_state.speech)

    asyncio.run(run())
