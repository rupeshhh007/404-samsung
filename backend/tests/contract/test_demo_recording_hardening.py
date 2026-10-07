"""Recording-day regressions for DEMO failure handling."""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import uuid4

from interlock.adapters.voice_transport import VoiceTransportRegistry
from interlock.config import Settings
from interlock.domain.enums import ClaimState, EffectState
from interlock.main import create_demo_asgi_app


class _AutoPlayout:
    def __init__(self, registry: VoiceTransportRegistry, binding: Any) -> None:
        self.registry = registry
        self.binding = binding
        self.tasks: set[asyncio.Task[Any]] = set()

    async def send_json(self, message: dict[str, Any]) -> None:
        if message.get("type") != "SPEAK":
            return

        async def complete() -> None:
            await self.registry.accept(self.binding, self.binding.generation, {
                "type": "PLAYOUT_STARTED",
                "worker_event_id": uuid4().hex,
                "speech_id": message["speech_id"],
            })
            await self.registry.accept(self.binding, self.binding.generation, {
                "type": "PLAYOUT_FINISHED",
                "worker_event_id": uuid4().hex,
                "speech_id": message["speech_id"],
                "heard": True,
            })

        task = asyncio.create_task(complete())
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)


def test_demo_post_dispatch_timeout_stays_unknown_without_protocol_violation() -> None:
    async def case() -> None:
        # The fake provider acts before the scripted response delay.  This
        # intentionally creates a post-dispatch timeout with an unknown outcome.
        host = create_demo_asgi_app(Settings(
            INTERLOCK_MODE="DEMO",
            INTERLOCK_TOOL_TIMEOUT_MS=100,
            INTERLOCK_FAKE_LATENCY_MS=250,
        ))
        registry: VoiceTransportRegistry = host.voice_registry
        binding, _, _ = await registry.create()
        socket = _AutoPlayout(registry, binding)
        await registry.connect(binding, socket)  # type: ignore[arg-type]

        await registry.accept(binding, binding.generation, {
            "type": "TRANSCRIPT",
            "worker_event_id": uuid4().hex,
            "item_id": uuid4().hex,
            "text": "Twelve please.",
            "final": True,
            "created_at": None,
        })

        await asyncio.sleep(0.35)
        await asyncio.wait_for(host.application.drain(binding.session_id), timeout=5)
        if socket.tasks:
            await asyncio.gather(*tuple(socket.tasks))

        events = host.application.events(binding.session_id)
        state = host.application.snapshot(binding.session_id)
        operation = next(iter(state.operations.values()))

        assert binding.provider.physical_action_count == 1
        assert any(event.event_type == "ToolTimedOut" for event in events)
        assert not any(event.event_type == "ProtocolViolationObserved" for event in events)
        assert operation.effect_state == EffectState.OUTCOME_UNKNOWN
        assert not any(claim.state == ClaimState.CONFIRMED for claim in state.claims.values())

        registry.disconnect(binding, binding.generation)
        await host.application.close()
        await host.hub.shutdown()

    asyncio.run(case())
