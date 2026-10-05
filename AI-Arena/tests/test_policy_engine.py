"""Policy decisions for secrets, files, roles, and writes."""

from core.tooling.policy_engine import PolicyEngine
from models.agent import AgentToolGovernance
from models.capability import (
    ExecutionContext, ExecutionTarget, ExecutionTargetKind, PolicyDecisionType,
    RiskLevel, ToolDefinitionSpec, VersionedCapabilityRef,
)


def _spec(risk=RiskLevel.READ_ONLY, supports_files=False):
    return ToolDefinitionSpec(
        category="test", risk_level=risk, input_schema={"type": "object"},
        output_schema={"type": "object"}, supports_files=supports_files,
        execution_target=ExecutionTarget(
            kind=ExecutionTargetKind.NATIVE_MCP,
            target_ref=VersionedCapabilityRef(capability_id="meridian_native_tools", version="1.0.0"),
            operation="summarize_content",
        ),
    )


def _context(file_ids=None):
    return ExecutionContext(
        user_id="u", tenant_id="t", agent_id="a", role="analyst", trace_id="trace",
        file_ids=file_ids or [],
    )


def test_policy_rejects_model_supplied_secret():
    decision = PolicyEngine.evaluate(_spec(), _context(), {"access_token": "secret"})
    assert decision.decision == PolicyDecisionType.DENY


def test_policy_rejects_file_outside_authorized_paths(tmp_path):
    allowed = tmp_path / "allowed.txt"
    other = tmp_path / "other.txt"
    decision = PolicyEngine.evaluate(
        _spec(supports_files=True), _context(["file-1"]),
        {"file_path": str(other)}, allowed_file_paths=[str(allowed)],
    )
    assert decision.decision == PolicyDecisionType.DENY


def test_write_requires_approval():
    decision = PolicyEngine.evaluate(_spec(RiskLevel.WRITE), _context(), {})
    assert decision.decision == PolicyDecisionType.APPROVAL_REQUIRED


def test_agent_owner_can_require_confirmation_for_read_tool():
    decision = PolicyEngine.evaluate(
        _spec(RiskLevel.READ_ONLY),
        _context(),
        {},
        agent_governance=AgentToolGovernance(confirmation_required=True),
    )
    assert decision.decision == PolicyDecisionType.APPROVAL_REQUIRED


def test_catalog_approval_flag_is_enforced_for_uncertain_tool():
    spec = _spec(RiskLevel.SENSITIVE_READ).model_copy(
        update={"requires_approval": True}
    )
    decision = PolicyEngine.evaluate(spec, _context(), {})
    assert decision.decision == PolicyDecisionType.APPROVAL_REQUIRED
