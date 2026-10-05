"""End-to-end Broker decision tests with isolated persistence and MCP boundaries."""

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from core.tooling.execution_broker import ExecutionBroker
from models.capability import (
    ExecutionContext, ExecutionTarget, ExecutionTargetKind, RiskLevel,
    ToolDefinitionSpec, ToolExecutionStatus, ToolRef, ToolResult,
    ToolResultStatus, VersionedCapabilityRef,
)
from models.agent import AgentToolGovernance


def _capability(risk):
    return {"spec": ToolDefinitionSpec(
        category="test", risk_level=risk,
        input_schema={"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"], "additionalProperties": False},
        output_schema={
            "type": "object",
            "properties": {"summary": {"type": "string"}},
            "required": ["summary"],
        },
        execution_target=ExecutionTarget(
            kind=ExecutionTargetKind.NATIVE_MCP,
            target_ref=VersionedCapabilityRef(capability_id="meridian_native_tools", version="1.0.0"),
            operation="summarize_content",
        ),
    ).model_dump(mode="json")}


def _context():
    return ExecutionContext(user_id="u", tenant_id="t", agent_id="a", role="agent", trace_id="trace")


class _Store:
    transitions = []

    @classmethod
    async def create(
        cls, tool_ref, context, arguments, idempotency_key=None, agent_governance=None
    ):
        cls.transitions = []
        return {"tool_execution_id": "tex-1", "status": ToolExecutionStatus.CREATED.value}

    @classmethod
    async def transition(cls, execution_id, **kwargs):
        cls.transitions.append(kwargs["to_status"])
        return {"tool_execution_id": execution_id}


def test_read_tool_runs_after_policy_check(monkeypatch):
    from core.tooling import execution_broker
    async def get_active(ref): return _capability(RiskLevel.READ_ONLY)
    async def resolve(context, ref): return AgentToolGovernance()
    async def call(*args, **kwargs):
        return ToolResult(status=ToolResultStatus.SUCCESS, data={"summary": "ok"}, trace_id="trace", tool_execution_id="tex-1")
    monkeypatch.setattr(execution_broker.CapabilityCatalog, "get_active_tool", staticmethod(get_active))
    monkeypatch.setattr(execution_broker.AgentToolPolicy, "resolve", staticmethod(resolve))
    monkeypatch.setattr(execution_broker, "ToolExecutionStore", _Store)
    monkeypatch.setattr(execution_broker.McpToolClient, "call_internal", staticmethod(call))
    result = asyncio.run(ExecutionBroker.execute(
        ToolRef(tool_id="summarize_content", version="1.0.0"), {"text": "hello"}, _context()
    ))
    assert result.status == ToolResultStatus.SUCCESS
    assert _Store.transitions == [
        ToolExecutionStatus.POLICY_CHECK,
        ToolExecutionStatus.RUNNING,
        ToolExecutionStatus.SUCCESS,
    ]


def test_write_tool_pauses_before_mcp_call(monkeypatch):
    from core.tooling import execution_broker
    async def get_active(ref): return _capability(RiskLevel.WRITE)
    async def resolve(context, ref): return AgentToolGovernance()
    called = False
    async def call(*args, **kwargs):
        nonlocal called
        called = True
    monkeypatch.setattr(execution_broker.CapabilityCatalog, "get_active_tool", staticmethod(get_active))
    monkeypatch.setattr(execution_broker.AgentToolPolicy, "resolve", staticmethod(resolve))
    monkeypatch.setattr(execution_broker, "ToolExecutionStore", _Store)
    monkeypatch.setattr(execution_broker.McpToolClient, "call_internal", staticmethod(call))
    result = asyncio.run(ExecutionBroker.execute(
        ToolRef(tool_id="summarize_content", version="1.0.0"), {"text": "hello"}, _context()
    ))
    assert result.status == ToolResultStatus.PENDING_APPROVAL
    assert called is False
    assert _Store.transitions[-1] == ToolExecutionStatus.PENDING_APPROVAL


def test_unassigned_tool_is_audited_and_rejected_before_catalog_or_mcp(monkeypatch):
    from core.tooling import execution_broker
    from core.tooling.agent_tool_policy import AgentToolNotAssigned

    async def reject_assignment(context, ref):
        raise AgentToolNotAssigned("not assigned")

    async def must_not_run(*args, **kwargs):
        raise AssertionError("unassigned tool crossed the agent boundary")

    monkeypatch.setattr(
        execution_broker.AgentToolPolicy, "resolve", staticmethod(reject_assignment)
    )
    monkeypatch.setattr(
        execution_broker.CapabilityCatalog, "get_active_tool", staticmethod(must_not_run)
    )
    monkeypatch.setattr(execution_broker, "ToolExecutionStore", _Store)
    monkeypatch.setattr(
        execution_broker.McpToolClient, "call_internal", staticmethod(must_not_run)
    )
    result = asyncio.run(ExecutionBroker.execute(
        ToolRef(tool_id="summarize_content", version="1.0.0"),
        {"text": "hello"},
        _context(),
    ))
    assert result.status == ToolResultStatus.REJECTED
    assert _Store.transitions == [
        ToolExecutionStatus.POLICY_CHECK,
        ToolExecutionStatus.REJECTED,
    ]


def test_agent_confirmation_makes_read_tool_pause(monkeypatch):
    from core.tooling import execution_broker

    async def get_active(ref): return _capability(RiskLevel.READ_ONLY)
    async def resolve(context, ref):
        return AgentToolGovernance(confirmation_required=True)
    async def must_not_run(*args, **kwargs):
        raise AssertionError("confirmation-required tool executed before approval")

    monkeypatch.setattr(
        execution_broker.CapabilityCatalog, "get_active_tool", staticmethod(get_active)
    )
    monkeypatch.setattr(
        execution_broker.AgentToolPolicy, "resolve", staticmethod(resolve)
    )
    monkeypatch.setattr(execution_broker, "ToolExecutionStore", _Store)
    monkeypatch.setattr(
        execution_broker.McpToolClient, "call_internal", staticmethod(must_not_run)
    )
    result = asyncio.run(ExecutionBroker.execute(
        ToolRef(tool_id="summarize_content", version="1.0.0"),
        {"text": "hello"},
        _context(),
    ))
    assert result.status == ToolResultStatus.PENDING_APPROVAL


def test_resume_rejects_governance_changed_after_approval(monkeypatch):
    from core.tooling import execution_broker

    class _ResumeStore:
        @classmethod
        async def get_owned(cls, execution_id, user_id, tenant_id):
            return {
                "tool_ref": {"tool_id": "summarize_content", "version": "1.0.0"},
                "agent_governance": {},
                "approval": {
                    "required": True,
                    "status": "approved",
                    "requested_at": datetime.now(timezone.utc),
                    "expires_at": datetime.now(timezone.utc) + timedelta(minutes=5),
                },
            }

    async def changed_governance(context, ref):
        return AgentToolGovernance(confirmation_required=True)

    monkeypatch.setattr(execution_broker, "ToolExecutionStore", _ResumeStore)
    monkeypatch.setattr(
        execution_broker.AgentToolPolicy,
        "resolve",
        staticmethod(changed_governance),
    )
    with pytest.raises(ValueError, match="governance changed"):
        asyncio.run(
            ExecutionBroker.resume_approved(
                "tex-1", {"text": "hello"}, _context()
            )
        )


def test_resume_accepts_mongodb_naive_utc_expiration(monkeypatch):
    """Motor's default BSON decoding must not break an approved resume."""

    from core.tooling import execution_broker

    arguments = {"text": "hello"}

    class _NaiveResumeStore:
        transitions = []

        @staticmethod
        def hash_arguments(value):
            return "matching-hash" if value == arguments else "different-hash"

        @classmethod
        async def get_owned(cls, execution_id, user_id, tenant_id):
            return {
                "tool_ref": {"tool_id": "summarize_content", "version": "1.0.0"},
                "agent_governance": AgentToolGovernance().model_dump(
                    mode="json", exclude_none=True
                ),
                "input_hash": "matching-hash",
                "approval": {
                    "required": True,
                    "status": "approved",
                    "requested_at": datetime.now(timezone.utc).replace(tzinfo=None),
                    "expires_at": (
                        datetime.now(timezone.utc) + timedelta(minutes=5)
                    ).replace(tzinfo=None),
                },
            }

        @classmethod
        async def transition(cls, execution_id, **kwargs):
            cls.transitions.append(kwargs["to_status"])
            return {"tool_execution_id": execution_id}

    async def resolve(context, ref):
        return AgentToolGovernance()

    async def get_active(ref):
        return _capability(RiskLevel.READ_ONLY)

    async def dispatch(*args, **kwargs):
        return ToolResult(
            status=ToolResultStatus.SUCCESS,
            data={"summary": "ok"},
            trace_id="trace",
            tool_execution_id="tex-1",
        )

    monkeypatch.setattr(execution_broker, "ToolExecutionStore", _NaiveResumeStore)
    monkeypatch.setattr(
        execution_broker.AgentToolPolicy, "resolve", staticmethod(resolve)
    )
    monkeypatch.setattr(
        execution_broker.CapabilityCatalog, "get_active_tool", staticmethod(get_active)
    )
    monkeypatch.setattr(
        execution_broker.ExecutionBroker, "_safe_dispatch", staticmethod(dispatch)
    )

    result = asyncio.run(
        ExecutionBroker.resume_approved("tex-1", arguments, _context())
    )

    assert result.status == ToolResultStatus.SUCCESS
    assert _NaiveResumeStore.transitions == [
        ToolExecutionStatus.RUNNING,
        ToolExecutionStatus.SUCCESS,
    ]


def test_native_normalized_envelope_contract_is_validated(monkeypatch):
    """Legacy native seeds describe ToolResult, not only result.data."""

    from core.tooling import execution_broker

    capability = _capability(RiskLevel.READ_ONLY)
    capability["spec"]["output_schema"] = {
        "type": "object",
        "properties": {
            "status": {"type": "string"},
            "data": {"type": "object"},
            "artifacts": {"type": "array"},
            "citations": {"type": "array"},
        },
        "required": ["status", "data"],
        "additionalProperties": False,
    }

    async def get_active(ref):
        return capability

    async def resolve(context, ref):
        return AgentToolGovernance()

    async def call(*args, **kwargs):
        return ToolResult(
            status=ToolResultStatus.SUCCESS,
            data={"summary": "ok"},
            trace_id="trace",
            tool_execution_id="tex-1",
        )

    monkeypatch.setattr(
        execution_broker.CapabilityCatalog, "get_active_tool", staticmethod(get_active)
    )
    monkeypatch.setattr(
        execution_broker.AgentToolPolicy, "resolve", staticmethod(resolve)
    )
    monkeypatch.setattr(execution_broker, "ToolExecutionStore", _Store)
    monkeypatch.setattr(
        execution_broker.McpToolClient, "call_internal", staticmethod(call)
    )

    result = asyncio.run(
        ExecutionBroker.execute(
            ToolRef(tool_id="summarize_content", version="1.0.0"),
            {"text": "hello"},
            _context(),
        )
    )

    assert result.status == ToolResultStatus.SUCCESS
