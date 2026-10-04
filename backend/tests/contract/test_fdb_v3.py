"""T-FDB-01: generic FDB-v3 tool mapping and execution contract."""

from __future__ import annotations

import asyncio
from typing import Any, Mapping
import pytest

from interlock.adapters.fdb_v3 import (
    FdbScenarioAdapter,
    normalize_fdb_tool_declaration,
)
from interlock.domain.enums import (
    ActionType,
    EffectClassification,
    OperationState,
)
from interlock.execution.operations import OperationError, OperationErrorCode


def test_generic_tool_declaration_normalization() -> None:
    """Arbitrary tool declarations normalize safely without scenario-specific rules."""
    # 1. OpenAI function-calling schema
    openai_tool = {
        "type": "function",
        "function": {
            "name": "search_database",
            "description": "Search records by query and category",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1},
                },
                "required": ["query"],
            },
        },
        "read_only": True,
    }
    manifest1 = normalize_fdb_tool_declaration(openai_tool)
    assert manifest1["tool_name"] == "search_database"
    assert manifest1["argument_schema"]["required"] == ["query"]
    assert manifest1["effect_classification"] == EffectClassification.NONE.value
    assert manifest1["action_type"] == ActionType.READ_ONLY.value

    # 2. Direct tool schema with state modification
    action_tool = {
        "tool_name": "transfer_funds",
        "description": "Transfer amount between accounts",
        "argument_schema": {
            "type": "object",
            "properties": {
                "source": {"type": "string"},
                "destination": {"type": "string"},
                "amount": {"type": "number", "exclusiveMinimum": 0},
            },
            "required": ["source", "destination", "amount"],
        },
        "read_only": False,
    }
    manifest2 = normalize_fdb_tool_declaration(action_tool)
    assert manifest2["tool_name"] == "transfer_funds"
    assert manifest2["effect_classification"] == EffectClassification.EXTERNAL_STATE_CHANGE.value
    assert manifest2["action_type"] == ActionType.REVERSIBLE.value
    assert manifest2["safe_points"] == ["BEFORE_PROVIDER_DISPATCH"]


def test_generic_tool_execution_end_to_end() -> None:
    """Tool invocation, arguments, and results map through validated descriptors."""
    async def case() -> None:
        def tool_runner(name: str, args: Mapping[str, Any]) -> dict[str, Any]:
            if name == "compute_score":
                return {"score": args["base"] * 2 + args.get("bonus", 0)}
            raise ValueError(f"Unknown tool: {name}")

        tools = [
            {
                "name": "compute_score",
                "description": "Compute a score from base and bonus",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "base": {"type": "integer"},
                        "bonus": {"type": "integer"},
                    },
                    "required": ["base"],
                },
                "read_only": True,
            }
        ]

        adapter = FdbScenarioAdapter(
            "scenario-exec-1", tools=tools, tool_executor=tool_runner
        )
        await adapter.start(logical_time=1)

        result_event = await adapter.execute_tool(
            tool_name="compute_score",
            arguments={"base": 21, "bonus": 5},
            operation_id="op-score-1",
        )
        assert result_event is not None
        assert result_event.event_type == "ToolResultObserved"
        assert result_event.payload["outcome"] == "SUCCEEDED"
        assert result_event.payload["result"] == {"score": 47}

        state = adapter.application.snapshot("scenario-exec-1")
        assert state.operations["op-score-1"].state == OperationState.SUCCEEDED
        assert len(adapter.transport.invocations) == 1

        await adapter.close()

    asyncio.run(case())


def test_chained_tool_calls() -> None:
    """Chained calls execute in sequence with dependency progression."""
    async def case() -> None:
        def tool_runner(name: str, args: Mapping[str, Any]) -> dict[str, Any]:
            if name == "get_customer":
                return {"customer_id": args["id"], "tier": "premium"}
            if name == "calculate_discount":
                rate = 0.20 if args["tier"] == "premium" else 0.05
                return {"discount": args["price"] * rate}
            raise ValueError(name)

        tools = [
            {
                "name": "get_customer",
                "parameters": {
                    "type": "object",
                    "properties": {"id": {"type": "string"}},
                    "required": ["id"],
                },
                "read_only": True,
            },
            {
                "name": "calculate_discount",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "tier": {"type": "string"},
                        "price": {"type": "number"},
                    },
                    "required": ["tier", "price"],
                },
                "read_only": True,
            },
        ]

        adapter = FdbScenarioAdapter(
            "scenario-chain-1", tools=tools, tool_executor=tool_runner
        )
        await adapter.start(logical_time=1)

        # Step 1: Look up customer
        ev1 = await adapter.execute_tool(
            tool_name="get_customer",
            arguments={"id": "cust-99"},
            operation_id="op-cust-1",
        )
        assert ev1 is not None
        tier = ev1.payload["result"]["tier"]
        assert tier == "premium"

        # Step 2: Use result to calculate discount
        ev2 = await adapter.execute_tool(
            tool_name="calculate_discount",
            arguments={"tier": tier, "price": 100.0},
            operation_id="op-disc-1",
        )
        assert ev2 is not None
        assert ev2.payload["result"]["discount"] == 20.0

        assert len(adapter.transport.invocations) == 2
        await adapter.close()

    asyncio.run(case())


def test_malformed_arguments_rejected_before_dispatch() -> None:
    """Invalid arguments fail safely before provider boundary."""
    async def case() -> None:
        dispatched = False

        def tool_runner(name: str, args: Mapping[str, Any]) -> dict[str, Any]:
            nonlocal dispatched
            dispatched = True
            return {"status": "ok"}

        tools = [
            {
                "name": "strict_tool",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "account_id": {"type": "string"},
                        "amount": {"type": "number", "minimum": 1},
                    },
                    "required": ["account_id", "amount"],
                },
            }
        ]

        adapter = FdbScenarioAdapter(
            "scenario-malformed-1", tools=tools, tool_executor=tool_runner
        )
        await adapter.start(logical_time=1)

        # Missing required field 'amount'
        with pytest.raises(OperationError) as exc_info:
            await adapter.execute_tool(
                tool_name="strict_tool",
                arguments={"account_id": "acc-1"},
            )
        assert exc_info.value.code == OperationErrorCode.INVALID_ARGUMENTS

        # Wrong type for 'amount'
        with pytest.raises(OperationError) as exc_info2:
            await adapter.execute_tool(
                tool_name="strict_tool",
                arguments={"account_id": "acc-1", "amount": "invalid_number"},
            )
        assert exc_info2.value.code == OperationErrorCode.INVALID_ARGUMENTS

        # Provider must NOT have been called
        assert not dispatched
        assert len(adapter.transport.invocations) == 0

        await adapter.close()

    asyncio.run(case())


def test_self_correction_after_malformed_arguments() -> None:
    """Failed malformed attempt allows subsequent valid self-correction."""
    async def case() -> None:
        def tool_runner(name: str, args: Mapping[str, Any]) -> dict[str, Any]:
            return {"confirmed_slot": args["slot"]}

        tools = [
            {
                "name": "book_slot",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "slot": {"type": "string", "minLength": 5},
                    },
                    "required": ["slot"],
                },
            }
        ]

        adapter = FdbScenarioAdapter(
            "scenario-correct-1", tools=tools, tool_executor=tool_runner
        )
        await adapter.start(logical_time=1)

        # Attempt 1: Malformed (too short)
        with pytest.raises(OperationError):
            await adapter.execute_tool(
                tool_name="book_slot",
                arguments={"slot": "10"},
                operation_id="op-attempt-1",
            )
        assert len(adapter.transport.invocations) == 0

        # Attempt 2: Self-corrected valid argument
        event = await adapter.execute_tool(
            tool_name="book_slot",
            arguments={"slot": "10:00 AM"},
            operation_id="op-attempt-2",
        )
        assert event is not None
        assert event.payload["outcome"] == "SUCCEEDED"
        assert event.payload["result"]["confirmed_slot"] == "10:00 AM"
        assert len(adapter.transport.invocations) == 1

        await adapter.close()

    asyncio.run(case())


def test_stale_dispatch_pin_fails_safely() -> None:
    """A stale safepoint pin does not dispatch to provider transport."""
    async def case() -> None:
        tool_called = False

        def tool_runner(name: str, args: Mapping[str, Any]) -> dict[str, Any]:
            nonlocal tool_called
            tool_called = True
            return {"result": "ok"}

        tools = [
            {
                "name": "safe_action",
                "parameters": {"type": "object", "properties": {}},
            }
        ]

        adapter = FdbScenarioAdapter(
            "scenario-stale-1", tools=tools, tool_executor=tool_runner
        )
        await adapter.start(logical_time=1)

        # Pass a stale sequence pin (1 is before current sequence at preparation)
        result = await adapter.execute_tool(
            tool_name="safe_action",
            arguments={},
            operation_id="op-stale-1",
            validated_through_sequence=1,
        )

        # Stale dispatch pin was rejected by reducer; tool was NOT dispatched
        assert result is None
        assert not tool_called
        assert len(adapter.transport.invocations) == 0

        # Operation remains in READY state, never dispatched
        state = adapter.application.snapshot("scenario-stale-1")
        assert state.operations["op-stale-1"].state == OperationState.READY

        await adapter.close()

    asyncio.run(case())


def test_speculation_rules_enforced() -> None:
    """Non-read-only tools reject speculation before dispatch."""
    async def case() -> None:
        tools = [
            {
                "name": "write_tool",
                "parameters": {"type": "object", "properties": {}},
                "read_only": False,
            },
            {
                "name": "read_tool",
                "parameters": {"type": "object", "properties": {}},
                "read_only": True,
            },
        ]

        adapter = FdbScenarioAdapter("scenario-spec-1", tools=tools)
        await adapter.start(logical_time=1)

        # Write tool cannot be speculative
        with pytest.raises(OperationError) as exc_info:
            await adapter.execute_tool(
                tool_name="write_tool",
                arguments={},
                speculative=True,
            )
        assert exc_info.value.code == OperationErrorCode.SPECULATION_FORBIDDEN

        # Read tool CAN be speculative
        read_event = await adapter.execute_tool(
            tool_name="read_tool",
            arguments={},
            speculative=True,
            operation_id="op-read-spec",
        )
        assert read_event is not None
        assert read_event.payload["outcome"] == "SUCCEEDED"

        await adapter.close()

    asyncio.run(case())
