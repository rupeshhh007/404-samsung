"""T-CON-01, T-CON-02 and I11: simultaneous ingress has one legal order."""

import asyncio

from interlock.domain.enums import EventSource, RuntimeMode
from interlock.runtime.journal import EventCandidate, EventJournal
from interlock.runtime.reducer import Reducer
from interlock.runtime.session import SessionRegistry


def test_t_con_01_t_inv_i11_p_t_inv_i11_n_contiguous_acceptance_and_replay():
    async def run():
        journal = EventJournal(SessionRegistry())
        await journal.append(EventCandidate(
            session_id="s", event_type="SessionStarted",
            source=EventSource.SYSTEM, payload={"mode": "TEST"},
        ))
        accepted = await asyncio.gather(*(
            journal.append(EventCandidate(
                session_id="s", event_type="UserInputObserved",
                source=EventSource.USER,
                payload={"evidence_id": f"e-{index}", "modality": "TEXT",
                         "content_ref": f"input-{index}"},
                dedupe_key=f"input-{index}",
            )) for index in range(20)
        ))
        assert len({event.event_id for event in accepted}) == 20
        events = journal.read_events("s")
        assert [event.sequence for event in events] == list(range(1, 22))
        state = None
        for event in events:
            state, commands = Reducer.reduce(state, event, mode=RuntimeMode.REPLAY)
            assert commands == []
        assert state.last_sequence == 21
    asyncio.run(run())


def test_t_con_02_t_inv_i1_p_t_inv_i1_n_stale_read_race_completes_historical_only():
    from interlock.adapters.websocket import project_state
    from interlock.config import Settings
    from interlock.domain.enums import (
        Authorization, EvidenceAuthority, IntentMaturity, OperationState, ToolOutcome,
    )
    from interlock.domain.models import IntentRevision
    from interlock.execution.descriptors import ToolRegistry
    from interlock.execution.tools import ProviderObservation, ProviderResponse
    from interlock.intelligence.intent_graph import assess_impact, bind_dependencies
    from interlock.main import Application, RuntimeDependencies
    from interlock.testing.fixtures import register_tool_manifests

    async def run():
        read_started = asyncio.Event()
        read_gate = asyncio.Event()

        class ControlledTransport:
            async def invoke(self, invocation):
                read_started.set()
                await read_gate.wait()
                obs = ProviderObservation(
                    provider_request_id="req-avail-1",
                    callback_dedupe_key="cb-avail-1",
                    outcome=ToolOutcome.SUCCEEDED,
                    result={
                        "phase": "FINAL",
                        "status": "AVAILABILITY_FOUND",
                        "provider_request_id": "req-avail-1",
                        "center_id": "ctr-01",
                        "available_slots": ["2030-01-15T11:00:00+05:30"],
                    },
                )
                return ProviderResponse(provider_request_id="req-avail-1", observation=obs)

            async def cancel(self, request):
                pass

        registry = ToolRegistry()
        register_tool_manifests(registry)
        app = Application(
            Settings(_env_file=None, INTERLOCK_MODE="TEST"),
            registry=registry,
            dependencies=RuntimeDependencies(tool_transport=ControlledTransport()),
        )
        await app.start_session("s")

        # 1. Older read/query begins for slot 11:00
        r1 = IntentRevision(
            revision_id="r1", intent_id="intent", parent_revision_id=None,
            values={"slot": "2030-01-15T11:00:00+05:30", "center_id": "ctr-01"},
            maturity=IntentMaturity.COMMITTED, authorization=Authorization.NOT_REQUESTED,
            created_by_event_id="e-start",
            dependency_fingerprint="dummy-fp-1",
        )
        await app.append(EventCandidate(
            session_id="s", event_type="IntentRevisionCommitted", source=EventSource.POLICY,
            payload={"revision": r1.model_dump(mode="json")},
        ))
        await app.append(EventCandidate(
            session_id="s", event_type="IntentAuthorizationChanged", source=EventSource.POLICY,
            payload={"revision_id": "r1", "authorization": "AUTHORIZED", "evidence_id": "e-auth-1"},
        ))

        bindings = bind_dependencies(r1.values, ["center_id", "slot"])
        op1 = app._sessions["s"].operations.create_operation(
            operation_id="op-read-1", session_id="s", intent_goal_id="intent",
            intent_revision=r1, bindings=bindings, tool_name="appointment.availability",
            arguments={"center_id": "ctr-01"},
            existing_operation_ids=set(), known_idempotency_digests={},
        )
        await app.append(EventCandidate(
            session_id="s", event_type="OperationCreated", source=EventSource.POLICY,
            payload={"operation": op1.model_dump(mode="json")},
        ))
        for _ in range(20):
            await asyncio.sleep(0.01)
            if app.snapshot("s").operations["op-read-1"].state == OperationState.READY:
                break

        prep_seq = app.snapshot("s").last_sequence
        await app.append(EventCandidate(
            session_id="s", event_type="ToolDispatchRequested", source=EventSource.POLICY,
            payload={"operation_id": "op-read-1", "validated_through_sequence": prep_seq},
        ))

        # Wait until older read begins and is outstanding at provider boundary
        await read_started.wait()

        # 2. User corrects intent/binding to 12:00 while older read is outstanding
        r2 = IntentRevision(
            revision_id="r2", intent_id="intent", parent_revision_id="r1",
            values={"slot": "2030-01-15T12:00:00+05:30", "center_id": "ctr-01"},
            maturity=IntentMaturity.COMMITTED, authorization=Authorization.NOT_REQUESTED,
            created_by_event_id="e-corr",
            dependency_fingerprint="dummy-fp-2",
        )
        await app.append(EventCandidate(
            session_id="s", event_type="IntentRevisionCommitted", source=EventSource.POLICY,
            payload={"revision": r2.model_dump(mode="json")},
        ))
        await app.append(EventCandidate(
            session_id="s", event_type="IntentAuthorizationChanged", source=EventSource.POLICY,
            payload={"revision_id": "r2", "authorization": "AUTHORIZED", "evidence_id": "e-auth-2"},
        ))

        mid_proj = project_state(app.snapshot("s"))
        assert mid_proj["intent"]["active_revision"]["values"]["slot"] == "2030-01-15T12:00:00+05:30"

        # 3. Old read completes LAST
        read_gate.set()
        for _ in range(50):
            await app.drain("s")
            if any(ev.kind == "tool_read_result" for ev in app.snapshot("s").evidence.values()):
                break
            await asyncio.sleep(0.01)

        # 4. Old read result is retained as historical evidence
        final_state = app.snapshot("s")
        read_evidence = [ev for ev in final_state.evidence.values() if ev.kind == "tool_read_result"]
        assert len(read_evidence) == 1
        assert read_evidence[0].authority == EvidenceAuthority.NON_AUTHORITATIVE

        # 5. Stale evidence does NOT overwrite current active projection
        final_proj = project_state(final_state)
        assert final_proj["intent"]["active_revision"]["values"]["slot"] == "2030-01-15T12:00:00+05:30"

        # 6. Corrected binding remains authoritative, impact assessment marks stale
        impact = assess_impact(r1, r2, bind_dependencies(r1.values, ["slot"]))
        assert impact.stale is True
        assert impact.eligible_for_active_result is False
        assert impact.affected_paths == ("slot",)

        # No spurious effects committed
        assert len(final_state.effects) == 0

        # Deterministic replay reproduces exact state and emits zero commands
        replay_state = None
        for ev in app._sessions["s"].journal.read_events("s"):
            replay_state, cmds = Reducer.reduce(replay_state, ev, mode=RuntimeMode.REPLAY)
            assert cmds == []
        assert replay_state.last_sequence == final_state.last_sequence

        await app.close()

    asyncio.run(run())
