"""FDB-v3 generic benchmark tool adapter and isolated scenario runtime.

Maps benchmark tool declarations, arguments, and invocations generically to
INTERLOCK ToolDescriptors and ToolRuntime commands, enforcing per-scenario
session isolation without hardcoded benchmark fixtures or cross-scenario leaks.
"""

from __future__ import annotations

import asyncio
from copy import deepcopy
from dataclasses import dataclass
import importlib
import inspect
import json
import os
from pathlib import Path
import sys
import time
from typing import Any, Awaitable, Callable, Collection, Mapping, Sequence

from interlock.config import Settings
from interlock.domain.enums import (
    ActionType,
    Authorization,
    CancellationPolicy,
    EffectClassification,
    EventSource,
    IntentMaturity,
    OperationState,
    SafePointName,
    ToolOutcome,
)
from interlock.domain.models import (
    DependencyBinding,
    EventEnvelope,
    IntentRevision,
    OperationRecord,
    SessionState,
    ToolDescriptor,
)
from interlock.execution.descriptors import ToolRegistry
from interlock.execution.operations import OperationError, OperationManager
from interlock.execution.tools import (
    ProviderCancellationRequest,
    ProviderCancellationResult,
    ProviderCancellationStatus,
    ProviderObservation,
    ProviderResponse,
    ToolInvocation,
    ToolProviderTransport,
)
from interlock.intelligence.intent_graph import (
    DependencySnapshot,
    bind_dependencies,
    dependency_fingerprint,
)
from interlock.main import Application, RuntimeDependencies
from interlock.providers.llm import StructuredProvider
from interlock.runtime.journal import EventCandidate


FdbToolExecutor = Callable[[str, Mapping[str, Any]], Any | Awaitable[Any]]
ApplicationFactory = Callable[[ToolRegistry, ToolProviderTransport], Application]


class FdbLiveKitToolBridge:
    """Expose official LiveKit tool schemas through one INTERLOCK scenario.

    LiveKit remains the model-selection surface.  The selected generic call is
    then authorized and executed by the existing FDB scenario/ToolRuntime path;
    this bridge owns no authoritative state and contains no scenario answers.
    """

    def __init__(
        self,
        adapter: "FdbScenarioAdapter",
        declarations: Sequence[Mapping[str, Any]],
        *,
        room_name: str,
        telemetry_path: Path = Path("/tmp/agent_tool_calls.log"),
    ) -> None:
        if not isinstance(adapter, FdbScenarioAdapter):
            raise TypeError("adapter must be an FdbScenarioAdapter")
        if not room_name:
            raise ValueError("room_name must be nonempty")
        self._adapter = adapter
        self._declarations = tuple(deepcopy(dict(item)) for item in declarations)
        self._room_name = room_name
        self._telemetry_path = telemetry_path
        self._call_lock = asyncio.Lock()
        self._next_operation = 0

    def livekit_tools(self) -> list[Any]:
        """Build raw-schema LiveKit tools without hardcoded benchmark names."""

        from livekit.agents import llm

        tools: list[Any] = []
        for declaration in self._declarations:
            function = declaration.get("function")
            if declaration.get("type") != "function" or not isinstance(function, dict):
                raise ValueError("official tool declaration must use function format")
            raw_schema = deepcopy(function)
            name = raw_schema.get("name")
            if not isinstance(name, str) or not name:
                raise ValueError("official tool name must be nonempty")

            async def invoke(
                raw_arguments: dict[str, object], *, _name: str = name
            ) -> str:
                return await self._invoke(_name, raw_arguments)

            tools.append(llm.function_tool(raw_schema=raw_schema)(invoke))
        return tools

    async def _invoke(self, tool_name: str, arguments: Mapping[str, Any]) -> str:
        started = time.time()
        async with self._call_lock:
            self._next_operation += 1
            operation_id = f"fdb-livekit-{self._next_operation}"
            try:
                event = await self._adapter.execute_tool(
                    tool_name=tool_name,
                    arguments=dict(arguments),
                    operation_id=operation_id,
                )
            finally:
                ended = time.time()
                self._record_call(tool_name, arguments, started, ended)
        if event is None:
            raise RuntimeError("INTERLOCK produced no terminal tool observation")
        if event.event_type != "ToolResultObserved":
            raise RuntimeError("INTERLOCK tool outcome is unresolved")
        return json.dumps(event.payload["result"], sort_keys=True, ensure_ascii=False)

    def _record_call(
        self,
        tool_name: str,
        arguments: Mapping[str, Any],
        started: float,
        ended: float,
    ) -> None:
        entry = {
            "room": self._room_name,
            "call": {
                "function": tool_name,
                "args": deepcopy(dict(arguments)),
                "timestamp_start": started,
                "timestamp_end": ended,
            },
        }
        self._telemetry_path.parent.mkdir(parents=True, exist_ok=True)
        with self._telemetry_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(entry, sort_keys=True, ensure_ascii=False) + "\n")


def official_fdb_tool_declarations(tool_context: Any) -> tuple[dict[str, Any], ...]:
    """Derive declarations from the pinned benchmark's actual LiveKit tools."""

    from livekit.agents import llm
    from livekit.agents.llm.utils import build_legacy_openai_schema

    tools = llm.find_function_tools(tool_context)
    if not tools:
        raise RuntimeError("official FDB tool surface is empty")
    return tuple(build_legacy_openai_schema(tool) for tool in tools)


def normalize_fdb_tool_declaration(
    raw: Mapping[str, Any],
    *,
    default_effect: EffectClassification = EffectClassification.EXTERNAL_STATE_CHANGE,
    default_action: ActionType = ActionType.REVERSIBLE,
) -> dict[str, Any]:
    """Convert an arbitrary OpenAI- or JSONSchema-style tool declaration into an INTERLOCK manifest."""
    declaration = dict(raw)

    # Handle OpenAI function-wrapped format: {"type": "function", "function": {...}}
    if declaration.get("type") == "function" and isinstance(declaration.get("function"), dict):
        func_def = dict(declaration["function"])
        name = func_def.get("name")
        params = func_def.get("parameters", {})
    else:
        name = declaration.get("tool_name") or declaration.get("name")
        params = declaration.get("argument_schema") or declaration.get("parameters", {})

    if not name or not isinstance(name, str):
        raise ValueError("Tool declaration must have a nonempty string name")

    if not isinstance(params, dict):
        params = {"type": "object", "properties": {}}

    arg_schema = deepcopy(params)
    if "type" not in arg_schema:
        arg_schema["type"] = "object"
    if "properties" not in arg_schema:
        arg_schema["properties"] = {}

    result_schema = deepcopy(declaration.get("result_schema") or {"type": "object"})

    # Determine effect and action classification conservatively
    effect = declaration.get("effect_classification")
    if effect is None:
        if declaration.get("read_only") is True:
            effect = EffectClassification.NONE.value
            action = ActionType.READ_ONLY.value
            cancel_policy = CancellationPolicy.IMMEDIATE.value
        else:
            effect = default_effect.value
            action = default_action.value
            cancel_policy = CancellationPolicy.AT_SAFEPOINT.value
    else:
        effect = str(effect)
        action = str(declaration.get("action_type", default_action.value))
        cancel_policy = str(
            declaration.get("cancellation_policy", CancellationPolicy.AT_SAFEPOINT.value)
        )

    # Confirmation semantics: read-only tools default to empty, consequential tools default to COMPLETED commit
    if declaration.get("confirmation_semantics") is not None:
        conf_semantics = deepcopy(declaration["confirmation_semantics"])
    elif effect == EffectClassification.NONE.value and action == ActionType.READ_ONLY.value:
        conf_semantics = {}
    else:
        conf_semantics = {
            "acknowledgement": "REQUEST_RECEIVED",
            "commit": "COMPLETED",
            "unknown": "OUTCOME_UNKNOWN",
            "authoritative_fields": [],
        }

    manifest: dict[str, Any] = {
        "tool_name": name,
        "manifest_version": 1,
        "argument_schema": arg_schema,
        "result_schema": result_schema,
        "effect_classification": effect,
        "action_type": action,
        "cancellation_policy": cancel_policy,
        "safe_points": [SafePointName.BEFORE_PROVIDER_DISPATCH.value],
        "timeout_ms": int(declaration.get("timeout_ms", 5000)),
        "retry_policy": deepcopy(
            declaration.get("retry_policy", {"max_attempts": 1, "retry_on": []})
        ),
        "idempotency": deepcopy(
            declaration.get(
                "idempotency",
                {"supported": True, "scope": "PROVIDER", "key_field": "idempotency_key"},
            )
        ),
        "compensation": deepcopy(declaration.get("compensation", {"supported": False})),
        "confirmation_semantics": conf_semantics,
    }
    return manifest


class FdbToolTransport(ToolProviderTransport):
    """Generic tool provider transport executing benchmark tool functions."""

    def __init__(
        self,
        executor: FdbToolExecutor | None = None,
        *,
        registry: ToolRegistry | None = None,
    ) -> None:
        self.executor = executor
        self.registry = registry
        self.invocations: list[ToolInvocation] = []
        self.cancellations: list[ProviderCancellationRequest] = []

    async def invoke(self, invocation: ToolInvocation) -> ProviderResponse:
        self.invocations.append(invocation)
        req_id = f"fdb-{invocation.operation_id}-{invocation.attempt}"
        dedupe_key = f"fdb:{invocation.operation_id}:{invocation.attempt}"

        if self.executor is None:
            return ProviderResponse(
                provider_request_id=req_id,
                observation=ProviderObservation(
                    provider_request_id=req_id,
                    callback_dedupe_key=dedupe_key,
                    outcome=ToolOutcome.SUCCEEDED,
                    result={"status": "COMPLETED", "arguments": invocation.arguments},
                ),
            )

        try:
            raw_result = self.executor(invocation.tool_name, invocation.arguments)
            if inspect.isawaitable(raw_result):
                raw_result = await raw_result

            if isinstance(raw_result, dict):
                norm_result = dict(raw_result)
            else:
                norm_result = {"output": raw_result}

            outcome = ToolOutcome.SUCCEEDED
            if norm_result.get("error") is not None or norm_result.get("failed") is True:
                outcome = ToolOutcome.FAILED

            if outcome == ToolOutcome.SUCCEEDED and self.registry is not None:
                try:
                    desc = self.registry.get(invocation.tool_name)
                    if desc.confirmation_semantics.commit is not None:
                        norm_result.setdefault("status", desc.confirmation_semantics.commit)
                except Exception:
                    pass

            return ProviderResponse(
                provider_request_id=req_id,
                observation=ProviderObservation(
                    provider_request_id=req_id,
                    callback_dedupe_key=dedupe_key,
                    outcome=outcome,
                    result=norm_result,
                ),
            )
        except Exception as exc:
            return ProviderResponse(
                provider_request_id=req_id,
                observation=ProviderObservation(
                    provider_request_id=req_id,
                    callback_dedupe_key=dedupe_key,
                    outcome=ToolOutcome.FAILED,
                    result={"error": str(exc), "error_type": type(exc).__name__},
                    retry_category="PROVIDER_EXECUTION_ERROR",
                ),
            )

    async def cancel(
        self, request: ProviderCancellationRequest
    ) -> ProviderCancellationResult:
        self.cancellations.append(request)
        return ProviderCancellationResult(
            status=ProviderCancellationStatus.CANCEL_ACCEPTED,
            reason="CANCELLED_BY_CLIENT",
        )


class FdbScenarioAdapter:
    """Manages one benchmark scenario session with strict lifecycle isolation."""

    def __init__(
        self,
        scenario_id: str,
        *,
        tools: Sequence[Mapping[str, Any]] | None = None,
        tool_executor: FdbToolExecutor | None = None,
        registry: ToolRegistry | None = None,
        transport: FdbToolTransport | None = None,
        application: Application | None = None,
        application_factory: ApplicationFactory | None = None,
        settings: Settings | None = None,
        model: StructuredProvider | None = None,
        owns_session_lifecycle: bool | None = None,
    ) -> None:
        if not scenario_id or not isinstance(scenario_id, str):
            raise ValueError("scenario_id must be a nonempty string")
        self.scenario_id = scenario_id
        self.registry = registry if registry is not None else ToolRegistry()
        self.transport = (
            transport
            if transport is not None
            else FdbToolTransport(tool_executor, registry=self.registry)
        )
        self.settings = settings or Settings(INTERLOCK_MODE="TEST")
        self._tools_declared: list[ToolDescriptor] = []

        if tools:
            for tool_decl in tools:
                manifest = normalize_fdb_tool_declaration(tool_decl)
                try:
                    desc = self.registry.get(manifest["tool_name"])
                except KeyError:
                    desc = self.registry.register(manifest)
                self._tools_declared.append(desc)

        if application is not None:
            self.application = application
        else:
            factory = application_factory or (
                lambda reg, trans: Application(
                    settings=self.settings,
                    registry=reg,
                    dependencies=RuntimeDependencies(tool_transport=trans, model=model),
                )
            )
            self.application = factory(self.registry, self.transport)

        if owns_session_lifecycle is not None:
            self._owns_session_lifecycle = owns_session_lifecycle
        else:
            self._owns_session_lifecycle = application is None

        self._operation_manager = OperationManager(self.registry)
        self._started = False
        self._closed = False
        self._last_state: SessionState | None = None

    @classmethod
    def create_composed(
        cls,
        scenario_id: str,
        *,
        tools: Sequence[Mapping[str, Any]] | None = None,
        tool_executor: FdbToolExecutor | None = None,
        livekit: Any,
        settings: Settings | None = None,
        model: StructuredProvider | None = None,
    ) -> tuple[FdbScenarioAdapter, Any]:
        """Compose FdbScenarioAdapter and LiveKitSessionAdapter on a single shared Application."""
        from interlock.adapters.livekit_agent import LiveKitSessionAdapter
        from interlock.truth.speech import OutputPort

        registry = ToolRegistry()
        transport = FdbToolTransport(tool_executor, registry=registry)
        effective_settings = settings or Settings(INTERLOCK_MODE="TEST")

        def _factory(output: OutputPort) -> Application:
            return Application(
                settings=effective_settings,
                registry=registry,
                dependencies=RuntimeDependencies(
                    output=output,
                    tool_transport=transport,
                    model=model,
                ),
            )

        livekit_adapter = LiveKitSessionAdapter(
            livekit,
            session_id=scenario_id,
            application_factory=_factory,
        )
        fdb_adapter = cls(
            scenario_id,
            tools=tools,
            registry=registry,
            transport=transport,
            application=livekit_adapter.application,
            settings=effective_settings,
            model=model,
        )
        return fdb_adapter, livekit_adapter

    async def start(self, *, logical_time: int = 0) -> SessionState:
        if self._started or self._closed:
            raise RuntimeError("scenario cannot be started twice")
        if self._owns_session_lifecycle:
            state = await self.application.start_session(
                self.scenario_id, logical_time=logical_time
            )
        else:
            if self.scenario_id not in getattr(self.application, "_sessions", {}):
                raise RuntimeError(
                    f"scenario session '{self.scenario_id}' has not been started by the lifecycle owner"
                )
            state = self.application.snapshot(self.scenario_id)
        self._started = True
        self._last_state = state
        return state

    async def drain(self) -> None:
        """Drain the underlying application session if active."""
        if not self._started or self._closed:
            raise RuntimeError("scenario is not active")
        await self.application.drain(self.scenario_id)

    async def _ensure_active_intent(self, intent_id: str) -> IntentRevision:
        """Ensure an active intent revision exists for operation linkage."""
        state = self.application.snapshot(self.scenario_id)
        if intent_id in state.intents:
            intent = state.intents[intent_id]
            if intent.active_revision_id and intent.active_revision_id in state.revisions:
                return state.revisions[intent.active_revision_id]

        deps = bind_dependencies(
            {"goal_type": "benchmark_task"},
            ["goal_type"],
        )
        fingerprint = dependency_fingerprint(deps)
        revision = IntentRevision(
            revision_id=f"rev-{intent_id}",
            intent_id=intent_id,
            values={"goal_type": "benchmark_task"},
            maturity=IntentMaturity.COMMITTED,
            authorization=Authorization.NOT_REQUESTED,
            created_by_event_id="fdb-init",
            dependency_fingerprint=fingerprint,
        )
        await self.application.append(
            EventCandidate(
                session_id=self.scenario_id,
                event_type="IntentRevisionCommitted",
                source=EventSource.POLICY,
                payload={"revision": revision.model_dump(mode="json")},
                correlation_id=self.scenario_id,
                dedupe_key=f"fdb:intent:{intent_id}",
            )
        )
        await self.application.append(
            EventCandidate(
                session_id=self.scenario_id,
                event_type="IntentAuthorizationChanged",
                source=EventSource.POLICY,
                payload={
                    "revision_id": revision.revision_id,
                    "authorization": Authorization.AUTHORIZED.value,
                    "evidence_id": f"ev-auth-{intent_id}",
                },
                correlation_id=self.scenario_id,
                dedupe_key=f"fdb:auth:{intent_id}",
            )
        )
        await self.application.drain(self.scenario_id)
        state_after = self.application.snapshot(self.scenario_id)
        return state_after.revisions[revision.revision_id]

    async def execute_tool(
        self,
        *,
        tool_name: str,
        arguments: Mapping[str, Any],
        intent_id: str = "fdb-task",
        operation_id: str | None = None,
        idempotency_key: str | None = None,
        bindings: Sequence[DependencyBinding | DependencySnapshot] | None = None,
        speculative: bool = False,
        validated_through_sequence: int | None = None,
    ) -> EventEnvelope | None:
        """Create, prepare, safepoint-pin, and dispatch one tool call end-to-end."""
        if not self._started or self._closed:
            raise RuntimeError("scenario is not active")

        revision = await self._ensure_active_intent(intent_id)
        state = self.application.snapshot(self.scenario_id)
        op_id = operation_id or f"op-{len(state.operations) + 1}"

        if bindings is None:
            dep_snaps = bind_dependencies(revision, ["goal_type"])
            effective_bindings: Sequence[DependencyBinding | DependencySnapshot] = [
                d.as_domain() for d in dep_snaps
            ]
        else:
            effective_bindings = bindings

        known_digests: dict[str, str] = {}
        for existing_op in state.operations.values():
            if existing_op.idempotency_key:
                known_digests[existing_op.idempotency_key] = existing_op.fingerprint

        # 1. Create operation via OperationManager (validates schema, speculation, args)
        op = self._operation_manager.create_operation(
            operation_id=op_id,
            session_id=self.scenario_id,
            intent_goal_id=intent_id,
            intent_revision=revision,
            bindings=effective_bindings,
            tool_name=tool_name,
            arguments=arguments,
            existing_operation_ids=set(state.operations.keys()),
            known_idempotency_digests=known_digests,
            speculative=speculative,
        )

        # 2. Append OperationCreated
        await self.application.append(
            EventCandidate(
                session_id=self.scenario_id,
                event_type="OperationCreated",
                source=EventSource.MODEL,
                payload={"operation": op.model_dump(mode="json")},
                correlation_id=self.scenario_id,
                dedupe_key=f"fdb:op-created:{op_id}",
            )
        )

        # 3. Drain session -> ToolRuntime prepares operation -> READY
        await self.application.drain(self.scenario_id)
        state_after_prepare = self.application.snapshot(self.scenario_id)
        curr_op = state_after_prepare.operations.get(op_id)
        if curr_op is None or curr_op.state != OperationState.READY:
            return None

        # 4. SafePoint: Append ToolDispatchRequested
        pin = (
            validated_through_sequence
            if validated_through_sequence is not None
            else state_after_prepare.last_sequence
        )
        await self.application.append(
            EventCandidate(
                session_id=self.scenario_id,
                event_type="ToolDispatchRequested",
                source=EventSource.POLICY,
                payload={
                    "operation_id": op_id,
                    "validated_through_sequence": pin,
                },
                correlation_id=self.scenario_id,
                dedupe_key=f"fdb:dispatch:{op_id}:{pin}",
            )
        )

        # 5. Drain session -> DispatchTool -> ToolProviderTransport.invoke -> ToolResultObserved
        await self.application.drain(self.scenario_id)

        # 6. Find and return the terminal ToolResultObserved or ToolTimedOut event
        events = self.application.events(self.scenario_id)
        for event in reversed(events):
            if (
                event.event_type in ("ToolResultObserved", "ToolTimedOut")
                and event.payload.get("operation_id") == op_id
            ):
                return event
        return None

    async def execute_chained_tools(
        self,
        calls: Sequence[tuple[str, Mapping[str, Any]]],
        *,
        intent_id: str = "fdb-task",
    ) -> list[EventEnvelope]:
        """Execute a sequence of chained tool calls within the scenario."""
        results: list[EventEnvelope] = []
        for tool_name, args in calls:
            event = await self.execute_tool(
                tool_name=tool_name, arguments=args, intent_id=intent_id
            )
            if event is not None:
                results.append(event)
        return results

    async def close(self) -> SessionState:
        """Quiesce and retire all scenario state, ensuring clean benchmark isolation."""
        if not self._started or self._closed:
            raise RuntimeError("scenario is not active")
        self._closed = True
        if self._owns_session_lifecycle:
            final_state = await self.application.close_session(self.scenario_id)
            self._last_state = final_state
        else:
            if self.scenario_id in getattr(self.application, "_sessions", {}):
                final_state = self.application.snapshot(self.scenario_id)
            else:
                final_state = self._last_state or SessionState(session_id=self.scenario_id)
            self._last_state = final_state
        return final_state


def run_official_fdb_livekit_agent(fdb_v3_dir: Path) -> None:
    """Run the pinned official FDB voice surface with INTERLOCK-owned tools."""

    directory = fdb_v3_dir.resolve()
    required = ("lk_agent_tool.py", "mock_apis.py", "benchmark_data_v2.json")
    if not directory.is_dir() or any(not (directory / name).is_file() for name in required):
        raise RuntimeError("FDB-v3 directory is incomplete")
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))
    official_agent = importlib.import_module("lk_agent_tool")
    official_apis = importlib.import_module("mock_apis")
    for module in (official_agent, official_apis):
        module_path = Path(getattr(module, "__file__", "")).resolve()
        if directory not in module_path.parents:
            raise RuntimeError("official FDB module resolved outside the pinned checkout")

    from livekit import agents
    from livekit.agents import Agent, AgentServer, AgentSession

    server = AgentServer()

    @server.rtc_session()
    async def entrypoint(ctx: agents.JobContext) -> None:
        # Every room is a benchmark example and receives entirely fresh mutable
        # state: provider registry, model context/session, Application, runtime
        # correlation, callback dedupe, and idempotency registries.
        tracker = official_agent.LatencyTracker()
        official_context = official_agent.AssistantFnc(tracker, ctx.room.name)
        declarations = official_fdb_tool_declarations(official_context)
        provider = official_apis.MockAPIRegistry(
            latency_profile=os.environ.get("FDB_V3_LATENCY_PROFILE", "instant")
        )

        def execute(tool_name: str, arguments: Mapping[str, Any]) -> dict[str, Any]:
            provider_arguments = {
                key: value for key, value in arguments.items() if key != "idempotency_key"
            }
            result = provider.call(tool_name, **provider_arguments)
            normalized = dict(result) if isinstance(result, Mapping) else {"output": result}
            provider_status = normalized.pop("status", None)
            if provider_status == "error":
                return {
                    "error": normalized.pop("message", "FDB provider failed"),
                    "provider_status": provider_status,
                    **normalized,
                }
            if provider_status is not None:
                normalized["provider_status"] = provider_status
            return normalized

        model = official_agent.get_realtime_model()
        session = AgentSession(llm=model)
        fdb_adapter, livekit_adapter = FdbScenarioAdapter.create_composed(
            ctx.room.name,
            tools=declarations,
            tool_executor=execute,
            livekit=session,
            settings=Settings(INTERLOCK_MODE="LIVE"),
        )
        await livekit_adapter.start(logical_time=0)
        await fdb_adapter.start(logical_time=0)
        bridge = FdbLiveKitToolBridge(
            fdb_adapter,
            declarations,
            room_name=ctx.room.name,
        )
        agent = Agent(
            instructions=official_agent.VoiceAgent().instructions,
            tools=bridge.livekit_tools(),
        )
        closed = False

        async def cleanup(_: str = "") -> None:
            nonlocal closed
            if closed:
                return
            closed = True
            try:
                await fdb_adapter.close()
            finally:
                await livekit_adapter.close()

        ctx.add_shutdown_callback(cleanup)
        await session.start(room=ctx.room, agent=agent)

    agents.cli.run_app(server)


def _command_line(argv: Sequence[str] | None = None) -> int:
    """Minimal delivery entrypoint; LiveKit owns all trailing CLI arguments."""

    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] != "benchmark-agent":
        raise SystemExit("usage: python -m interlock.adapters.fdb_v3 benchmark-agent --fdb-v3-dir PATH start")
    try:
        option = args.index("--fdb-v3-dir")
        directory = Path(args[option + 1])
    except (ValueError, IndexError) as exc:
        raise SystemExit("benchmark-agent requires --fdb-v3-dir PATH") from exc
    livekit_args = args[1:option] + args[option + 2:]
    if not livekit_args:
        livekit_args = ["start"]
    sys.argv = [sys.argv[0], *livekit_args]
    run_official_fdb_livekit_agent(directory)
    return 0


__all__ = [
    "FdbLiveKitToolBridge",
    "FdbScenarioAdapter",
    "FdbToolExecutor",
    "FdbToolTransport",
    "normalize_fdb_tool_declaration",
    "official_fdb_tool_declarations",
    "run_official_fdb_livekit_agent",
]


if __name__ == "__main__":
    raise SystemExit(_command_line())
