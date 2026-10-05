"""Agent assignment and stricter-only governance tests."""

import asyncio

import pytest

from core.tooling.agent_tool_policy import AgentToolNotAssigned, AgentToolPolicy
from models.agent import AgentToolGovernance
from models.capability import (
    ExecutionContext, ExecutionTarget, ExecutionTargetKind, RiskLevel,
    ToolDefinitionSpec, ToolRef, VersionedCapabilityRef,
)


def _context():
    return ExecutionContext(
        user_id="user-1", tenant_id="audit-only", agent_id="custom-1",
        role="agent", trace_id="trace-1",
    )


def _spec():
    return ToolDefinitionSpec(
        category="search", risk_level=RiskLevel.READ_ONLY,
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "max_results": {"type": "integer", "minimum": 1, "maximum": 50},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
        output_schema={"type": "object"},
        execution_target=ExecutionTarget(
            kind=ExecutionTargetKind.EXTERNAL_MCP,
            target_ref=VersionedCapabilityRef(
                capability_id="search_mcp", version="1.0.0"
            ),
            operation="search",
        ),
        timeout_seconds=30,
    )


class _Collection:
    def __init__(self, document):
        self.document = document
        self.query = None

    async def find_one(self, query, projection=None):
        self.query = query
        return self.document


def test_exact_current_agent_assignment_is_queried(monkeypatch):
    collection = _Collection({
        "tool_governance": {
            "web.search": {"confirmation_required": True, "timeout_seconds": 10}
        }
    })
    monkeypatch.setattr(AgentToolPolicy, "collection", staticmethod(lambda: collection))
    governance = asyncio.run(
        AgentToolPolicy.resolve(
            _context(), ToolRef(tool_id="web.search", version="1.2.0")
        )
    )
    assert governance.confirmation_required is True
    assert collection.query["agent_id"] == "custom-1"
    assert collection.query["user_id"] == "user-1"
    assert collection.query["tool_refs"]["$elemMatch"] == {
        "tool_id": "web.search", "version": "1.2.0"
    }


def test_missing_assignment_fails_closed(monkeypatch):
    monkeypatch.setattr(
        AgentToolPolicy, "collection", staticmethod(lambda: _Collection(None))
    )
    with pytest.raises(AgentToolNotAssigned):
        asyncio.run(
            AgentToolPolicy.resolve(
                _context(), ToolRef(tool_id="web.search", version="1.2.0")
            )
        )


def test_user_governance_can_only_reduce_platform_limits():
    spec = _spec()
    governance = AgentToolGovernance(timeout_seconds=10, max_results=5)
    AgentToolPolicy.validate_governance(governance, spec)
    effective = AgentToolPolicy.effective_spec(spec, governance)
    arguments = AgentToolPolicy.effective_arguments(
        {"query": "mcp", "max_results": 20}, governance, effective
    )
    assert effective.timeout_seconds == 10
    assert arguments["max_results"] == 5
    with pytest.raises(ValueError, match="platform maximum"):
        AgentToolPolicy.validate_governance(
            AgentToolGovernance(timeout_seconds=31), spec
        )


def test_defaults_cannot_inject_credentials_or_unknown_fields():
    spec = _spec()
    with pytest.raises(ValueError, match="identity or credential"):
        AgentToolPolicy.validate_governance(
            AgentToolGovernance(default_parameters={"access_token": "secret"}), spec
        )
    with pytest.raises(ValueError, match="outside the approved schema"):
        AgentToolPolicy.validate_governance(
            AgentToolGovernance(default_parameters={"project": "unknown"}), spec
        )


def test_result_limit_is_rejected_when_tool_contract_cannot_enforce_it():
    spec = _spec().model_copy(
        update={
            "input_schema": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            }
        }
    )
    with pytest.raises(ValueError, match="requires an approved max_results"):
        AgentToolPolicy.validate_governance(
            AgentToolGovernance(max_results=5), spec
        )
