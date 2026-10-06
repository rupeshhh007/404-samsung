"""T-ISO-01: fresh benchmark scenario and per-scenario isolation contract."""

from __future__ import annotations

import asyncio
from typing import Any, Mapping
import pytest

from interlock.adapters.fdb_v3 import FdbScenarioAdapter
from interlock.domain.enums import OperationState


def test_reused_scenario_id_starts_with_clean_slate() -> None:
    """Reusing the same scenario identity yields no leftover operations, evidence, or effects."""
    async def case() -> None:
        def tool_runner(name: str, args: Mapping[str, Any]) -> dict[str, Any]:
            return {"user": args["user"], "token": f"tok-{args['user']}"}

        tools = [
            {
                "name": "login_user",
                "parameters": {
                    "type": "object",
                    "properties": {"user": {"type": "string"}},
                    "required": ["user"],
                },
            }
        ]

        scenario_id = "reused-scenario-001"

        # ---------------- Run 1 ----------------
        adapter1 = FdbScenarioAdapter(
            scenario_id, tools=tools, tool_executor=tool_runner
        )
        await adapter1.start(logical_time=1)

        ev1 = await adapter1.execute_tool(
            tool_name="login_user",
            arguments={"user": "alice"},
            operation_id="op-1",
            idempotency_key="ik-shared-key",
        )
        assert ev1 is not None
        snap1 = adapter1.application.snapshot(scenario_id)
        assert len(snap1.operations) == 1
        assert "op-1" in snap1.operations
        assert len(adapter1.transport.invocations) == 1

        final1 = await adapter1.close()
        assert final1.operations["op-1"].state == OperationState.SUCCEEDED

        # ---------------- Run 2 (Same Scenario ID) ----------------
        adapter2 = FdbScenarioAdapter(
            scenario_id, tools=tools, tool_executor=tool_runner
        )
        snap2_initial = await adapter2.start(logical_time=1)

        # Fresh scenario state verification
        assert snap2_initial.last_sequence == 1
        assert len(snap2_initial.operations) == 0
        assert len(snap2_initial.evidence) == 0
        assert len(snap2_initial.effects) == 0
        assert len(snap2_initial.claims) == 0
        assert len(snap2_initial.intents) == 0
        assert len(snap2_initial.revisions) == 0
        assert len(snap2_initial.speech) == 0
        assert len(adapter2.transport.invocations) == 0

        # Operation with the same operation_id and idempotency_key must succeed cleanly
        ev2 = await adapter2.execute_tool(
            tool_name="login_user",
            arguments={"user": "bob"},
            operation_id="op-1",
            idempotency_key="ik-shared-key",
        )
        assert ev2 is not None
        assert ev2.payload["result"]["user"] == "bob"

        snap2_final = adapter2.application.snapshot(scenario_id)
        assert len(snap2_final.operations) == 1
        assert snap2_final.operations["op-1"].args["user"] == "bob"
        assert len(adapter2.transport.invocations) == 1

        await adapter2.close()

    asyncio.run(case())


def test_concurrent_scenarios_have_no_cross_leakage() -> None:
    """Concurrent benchmark scenarios maintain completely isolated execution scopes."""
    async def case() -> None:
        def runner_a(name: str, args: Mapping[str, Any]) -> dict[str, Any]:
            return {"scope": "A", "val": args["x"]}

        def runner_b(name: str, args: Mapping[str, Any]) -> dict[str, Any]:
            return {"scope": "B", "val": args["x"]}

        tools = [
            {
                "name": "echo",
                "parameters": {
                    "type": "object",
                    "properties": {"x": {"type": "integer"}},
                    "required": ["x"],
                },
                "read_only": True,
            }
        ]

        adapter_a = FdbScenarioAdapter(
            "scenario-A", tools=tools, tool_executor=runner_a
        )
        adapter_b = FdbScenarioAdapter(
            "scenario-B", tools=tools, tool_executor=runner_b
        )

        await adapter_a.start(logical_time=1)
        await adapter_b.start(logical_time=1)

        # Execute operations with overlapping IDs across both scenarios concurrently
        res_a, res_b = await asyncio.gather(
            adapter_a.execute_tool(
                tool_name="echo", arguments={"x": 10}, operation_id="op-shared"
            ),
            adapter_b.execute_tool(
                tool_name="echo", arguments={"x": 20}, operation_id="op-shared"
            ),
        )

        assert res_a is not None and res_a.payload["result"] == {"scope": "A", "val": 10}
        assert res_b is not None and res_b.payload["result"] == {"scope": "B", "val": 20}

        # Validate scenario A
        snap_a = adapter_a.application.snapshot("scenario-A")
        assert len(snap_a.operations) == 1
        assert snap_a.operations["op-shared"].args["x"] == 10
        assert len(adapter_a.transport.invocations) == 1
        assert adapter_a.transport.invocations[0].arguments["x"] == 10

        # Validate scenario B
        snap_b = adapter_b.application.snapshot("scenario-B")
        assert len(snap_b.operations) == 1
        assert snap_b.operations["op-shared"].args["x"] == 20
        assert len(adapter_b.transport.invocations) == 1
        assert adapter_b.transport.invocations[0].arguments["x"] == 20

        await asyncio.gather(adapter_a.close(), adapter_b.close())

    asyncio.run(case())


def test_closed_scenario_rejects_further_dispatch() -> None:
    """A closed scenario rejects operations and intake fail-closed."""
    async def case() -> None:
        adapter = FdbScenarioAdapter(
            "scenario-closed-1",
            tools=[{"name": "test_tool", "parameters": {"type": "object", "properties": {}}}],
        )
        await adapter.start(logical_time=1)
        await adapter.close()

        with pytest.raises(RuntimeError, match="scenario is not active"):
            await adapter.execute_tool(tool_name="test_tool", arguments={})

        with pytest.raises(RuntimeError, match="scenario is not active"):
            await adapter.drain()

        with pytest.raises(RuntimeError, match="scenario cannot be started twice"):
            await adapter.start()

    asyncio.run(case())


class FakeSpeechHandle:
    def __init__(self, *, auto_start: bool = True, auto_finish: bool = True) -> None:
        self.interrupted = False
        self._done = asyncio.Event()
        self._started = asyncio.Event()
        if auto_start:
            self._started.set()
        if auto_finish:
            self._done.set()

    def start(self) -> None:
        self._started.set()

    async def wait_for_start(self) -> None:
        await self._started.wait()

    def done(self) -> bool:
        return self._done.is_set()

    def interrupt(self, *, force: bool = False, source: str = "programmatic") -> "FakeSpeechHandle":
        del force, source
        self.interrupted = True
        self._done.set()
        return self

    async def wait_for_playout(self) -> None:
        await self._done.wait()

    def exception(self) -> None:
        return None

    def finish(self) -> None:
        self._done.set()


class _FakeAgentSession:
    """Minimal LiveKit agent session mock for composed integration contract."""

    def __init__(self, *, auto_start_speech: bool = True, auto_finish_speech: bool = True) -> None:
        self.auto_start_speech = auto_start_speech
        self.auto_finish_speech = auto_finish_speech
        self.listeners: dict[str, list[Callable[[Any], None]]] = {}
        self.spoken: list[tuple[str, bool, bool]] = []
        self.handles: list[FakeSpeechHandle] = []
        self.closed = False
        self.agent_state = "idle"

    def on(self, event: str, callback: Callable[[Any], None] | None = None):
        def register(listener: Callable[[Any], None]):
            self.listeners.setdefault(event, []).append(listener)
            return listener

        return register(callback) if callback is not None else register

    def off(self, event: str, callback: Callable[[Any], None]) -> None:
        self.listeners.get(event, []).remove(callback)

    def say(self, text: str, *, allow_interruptions: bool, add_to_chat_ctx: bool):
        self.spoken.append((text, allow_interruptions, add_to_chat_ctx))
        handle = FakeSpeechHandle(auto_start=self.auto_start_speech, auto_finish=self.auto_finish_speech)
        self.handles.append(handle)
        return handle

    @property
    def current_speech(self) -> FakeSpeechHandle | None:
        for handle in reversed(self.handles):
            if handle._started.is_set() and not handle.done():
                return handle
        return None

    async def aclose(self) -> None:
        self.closed = True


def test_composed_livekit_and_fdb_share_application_and_sequence_space() -> None:
    """LiveKit voice adapter and FDB tool adapter compose on one Application/session."""
    async def case() -> None:
        fake_livekit = _FakeAgentSession()
        tools = [
            {
                "name": "query_database",
                "parameters": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
                "read_only": True,
            }
        ]

        scenario_id = "scenario-composed-001"
        fdb_adapter, livekit_adapter = FdbScenarioAdapter.create_composed(
            scenario_id,
            tools=tools,
            tool_executor=lambda name, args: {"rows": [{"id": 1, "val": args["query"]}]},
            livekit=fake_livekit,
        )

        # 1. Proves single authoritative Application instance shared across both adapters
        assert fdb_adapter.application is livekit_adapter.application

        # 2. Start session via LiveKit then synchronize FDB adapter
        state_lk = await asyncio.wait_for(livekit_adapter.start(logical_time=1), timeout=2.0)
        state_fdb = await asyncio.wait_for(fdb_adapter.start(logical_time=1), timeout=2.0)
        assert state_lk.session_id == scenario_id
        assert state_fdb.session_id == scenario_id
        assert state_lk.last_sequence == 1
        assert state_fdb.last_sequence == 1

        # 3. Ingress user voice transcript through LiveKit
        trans_ev = await asyncio.wait_for(
            livekit_adapter.accept_transcript(
                transcript="Search database for alpha",
                final=True,
                item_id="turn-1",
            ),
            timeout=2.0,
        )
        await asyncio.wait_for(livekit_adapter.application.drain(scenario_id), timeout=2.0)
        assert trans_ev.sequence == 2
        assert trans_ev.event_type == "TranscriptHypothesisObserved"

        # 4. Ingress tool execution through FDB adapter on the exact same session
        tool_ev = await asyncio.wait_for(
            fdb_adapter.execute_tool(
                tool_name="query_database",
                arguments={"query": "alpha"},
                operation_id="op-comp-1",
            ),
            timeout=2.0,
        )
        assert tool_ev is not None
        assert tool_ev.event_type == "ToolResultObserved"
        # Tool sequence numbers strictly advance in the SAME sequence space
        assert tool_ev.sequence > trans_ev.sequence

        # 5. Verify entire unified session event journal
        events = fdb_adapter.application.events(scenario_id)
        event_types = [e.event_type for e in events]
        assert "SessionStarted" in event_types
        assert "TranscriptHypothesisObserved" in event_types
        assert "ControlIntentInterpreted" in event_types
        assert "OperationCreated" in event_types
        assert "ToolResultObserved" in event_types

        # Monotonically contiguous sequence space: exactly 1..len(events)
        sequences = [e.sequence for e in events]
        assert sequences == list(range(1, len(events) + 1))

        # 6. Snapshot reflects both voice-transcribed evidence and tool execution
        snap = fdb_adapter.application.snapshot(scenario_id)
        assert "op-comp-1" in snap.operations
        assert len(snap.evidence) >= 1

        # 7. Clean teardown across composed adapters
        await asyncio.wait_for(fdb_adapter.close(), timeout=2.0)
        await asyncio.wait_for(livekit_adapter.close(), timeout=2.0)
        assert fdb_adapter._closed
        assert livekit_adapter._closed
        assert fake_livekit.closed

    asyncio.run(case())
