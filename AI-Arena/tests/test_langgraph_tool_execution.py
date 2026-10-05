import asyncio

import pytest

from config import settings
from core.orchestration.executor import AgentExecutor
from core.orchestration.executor_nodes import execution
from models.capability import ToolError, ToolResult, ToolResultStatus


def _state(tool_id: str) -> dict:
    return {
        "blueprint": {
            "tool_refs": [{"tool_id": tool_id, "version": "1.0.0"}],
            "tool_governance": {},
            "crew_roles": [],
        },
        "query": "Run the assigned tool",
        "user_id": "user-1",
        "tenant_id": "user-1",
        "agent_id": "agent-1",
        "trace_id": "trace-1",
        "thread_id": "thread-1",
        "file_ids": [],
        "file_paths": [],
        "blackboard": {},
        "sub_agent_histories": {},
        "executed_steps": [],
        "agent_config": {"sub_agents": [], "executor_policy": {}},
    }


def test_governed_tool_is_awaited_and_returns_success(monkeypatch):
    tool_id = "governed_test_tool"

    async def fake_execute(*_args, **_kwargs):
        return ToolResult(
            status=ToolResultStatus.SUCCESS,
            data={"summary": "done"},
            trace_id="trace-1",
            tool_execution_id="tex-1",
        )

    monkeypatch.setattr(settings, "ENABLE_GOVERNED_TOOL_RUNTIME", True)
    monkeypatch.setattr(
        "core.tooling.execution_broker.ExecutionBroker.execute", fake_execute
    )
    output = asyncio.run(
        execution._call_tool(
            tool_id,
            {"step": 1, "task": "Run", "resolved_input": {"text": "input"}},
            {"query": "Run"},
            _state(tool_id),
        )
    )

    assert '"summary": "done"' in output


@pytest.mark.parametrize(
    ("result", "expected_error"),
    [
        (
            ToolResult(
                status=ToolResultStatus.REJECTED,
                metadata={"reason": "Policy rejected the tool"},
                trace_id="trace-1",
                tool_execution_id="tex-rejected",
            ),
            "TOOL_EXECUTION_REJECTED",
        ),
        (
            ToolResult(
                status=ToolResultStatus.ERROR,
                error=ToolError(
                    code="tool_failed", message="Tool execution failed", retryable=False
                ),
                trace_id="trace-1",
                tool_execution_id="tex-error",
            ),
            "TOOL_EXECUTION_FAILED",
        ),
    ],
)
def test_governed_failure_stops_remaining_graph_steps(
    monkeypatch, result, expected_error
):
    calls = []

    async def fake_call(*_args, **_kwargs):
        calls.append(1)
        if result.status == ToolResultStatus.REJECTED:
            raise execution.GovernedToolRejected(result.metadata["reason"])
        raise execution.GovernedToolFailed(result.error.message)

    state = _state("governed_test_tool")
    state["structured_plan"] = [
        {"step": 1, "tool": "governed_test_tool", "task": "First", "input": {}},
        {"step": 2, "tool": "governed_test_tool", "task": "Must not run", "input": {}},
    ]
    monkeypatch.setattr(execution, "_call_tool", fake_call)

    output = asyncio.run(execution.execution_node(state))

    assert output["error"] == expected_error
    assert len(calls) == 1
    assert output["crew_output"] == ""


def test_approval_pauses_graph_and_preserves_execution_id(monkeypatch):
    async def fake_call(*_args, **_kwargs):
        raise execution.ToolApprovalRequired("tex-pending")

    state = _state("governed_test_tool")
    state["structured_plan"] = [
        {"step": 1, "tool": "governed_test_tool", "task": "Approve", "input": {}}
    ]
    monkeypatch.setattr(execution, "_call_tool", fake_call)

    output = asyncio.run(execution.execution_node(state))

    assert output["error"] == "HITL_REQUIRED"
    assert output["tool_execution_id"] == "tex-pending"
    assert output["blackboard"]["pending_tool_execution_id"] == "tex-pending"


def test_async_executor_uses_langgraph_ainvoke(monkeypatch):
    calls = {"ainvoke": 0}

    class FakeGraph:
        async def ainvoke(self, state):
            calls["ainvoke"] += 1
            return {**state, "final_response": "completed"}

    monkeypatch.setattr(AgentExecutor, "build_executor", lambda: FakeGraph())
    result = asyncio.run(
        AgentExecutor.run_async(
            blueprint={}, query="hello", trace_id="trace-async"
        )
    )

    assert calls["ainvoke"] == 1
    assert result["status"] == "success"
    assert result["message"] == "completed"


def test_async_executor_exposes_pending_tool_execution_id(monkeypatch):
    class FakeGraph:
        async def ainvoke(self, state):
            return {
                **state,
                "error": "HITL_REQUIRED",
                "validation_feedback": "Tool approval is required",
                "tool_execution_id": "tex-pending-123",
                "blackboard": {"pending_tool_execution_id": "tex-pending-123"},
                "structured_plan": [{"step": 1, "tool": "notion.search"}],
            }

    monkeypatch.setattr(AgentExecutor, "build_executor", lambda: FakeGraph())

    result = asyncio.run(
        AgentExecutor.run_async(
            blueprint={}, query="search notion", trace_id="trace-pending"
        )
    )

    assert result["hitl_pending"] is True
    assert result["approval_type"] == "tool"
    assert result["tool_execution_id"] == "tex-pending-123"


def test_async_executor_distinguishes_plan_approval_without_execution_id(monkeypatch):
    class FakeGraph:
        async def ainvoke(self, state):
            return {
                **state,
                "error": "HITL_REQUIRED",
                "final_response": "Review this flight plan",
                "structured_plan": [{"step": 1, "tool": "notion.search"}],
            }

    monkeypatch.setattr(AgentExecutor, "build_executor", lambda: FakeGraph())

    result = asyncio.run(
        AgentExecutor.run_async(
            blueprint={}, query="search notion", trace_id="trace-plan"
        )
    )

    assert result["hitl_pending"] is True
    assert result["approval_type"] == "plan"
    assert result["message"] == "Review this flight plan"
    assert "tool_execution_id" not in result
