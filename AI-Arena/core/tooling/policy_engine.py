"""Deterministic policy checks applied before every governed tool execution."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any
from jsonschema import Draft202012Validator, FormatChecker

from models.capability import (
    ExecutionContext,
    PolicyDecision,
    PolicyDecisionType,
    RiskLevel,
    ToolDefinitionSpec,
)
from models.agent import AgentToolGovernance


_FORBIDDEN_ARGUMENT_KEYS = {
    "access_token", "api_key", "client_secret", "password", "private_key",
    "refresh_token", "secret", "token",
}
_RESERVED_CONTEXT_KEYS = {
    "agent_id", "role", "scopes", "tenant_id", "trace_id", "user_id",
}


# Designed and implemented by Rajadurai R.
# Every governed tool reaches this deterministic fail-closed decision point.
class PolicyEngine:
    @staticmethod
    def evaluate(
        spec: ToolDefinitionSpec,
        context: ExecutionContext,
        arguments: dict[str, Any],
        *,
        allowed_file_paths: list[str] | None = None,
        agent_governance: AgentToolGovernance | None = None,
    ) -> PolicyDecision:
        now = datetime.now(timezone.utc)
        schema_errors = list(
            Draft202012Validator(
                spec.input_schema, format_checker=FormatChecker()
            ).iter_errors(arguments)
        )
        if schema_errors:
            return PolicyDecision(
                decision=PolicyDecisionType.DENY,
                policy_refs=spec.policy_refs,
                reason="Tool arguments do not match the approved input schema",
                evaluated_at=now,
            )
        keys = {str(key).strip().lower() for key in arguments}
        if keys & (_FORBIDDEN_ARGUMENT_KEYS | _RESERVED_CONTEXT_KEYS):
            return PolicyDecision(
                decision=PolicyDecisionType.DENY,
                policy_refs=spec.policy_refs,
                reason="Tool arguments must not contain credentials or raw secrets",
                evaluated_at=now,
            )
        # Designed and implemented by Rajadurai R.
        # Authorization is enforced by authenticated ownership plus exact agent-tool
        # assignment. ``allowed_roles`` remains readable for older catalog records only.
        supplied_path = arguments.get("file_path")
        if supplied_path is not None:
            allowed = {os.path.realpath(path) for path in (allowed_file_paths or [])}
            if os.path.realpath(str(supplied_path)) not in allowed:
                return PolicyDecision(
                    decision=PolicyDecisionType.DENY,
                    policy_refs=spec.policy_refs,
                    reason="File path is outside the request authorization boundary",
                    evaluated_at=now,
                )
        if spec.supports_files and not context.file_ids and supplied_path:
            return PolicyDecision(
                decision=PolicyDecisionType.DENY,
                policy_refs=spec.policy_refs,
                reason="File execution requires an authorized file ID",
                evaluated_at=now,
            )
        if spec.requires_approval or spec.risk_level in {RiskLevel.WRITE, RiskLevel.DESTRUCTIVE} or (
            agent_governance is not None and agent_governance.confirmation_required
        ):
            return PolicyDecision(
                decision=PolicyDecisionType.APPROVAL_REQUIRED,
                policy_refs=spec.policy_refs,
                reason=(
                    "Tool policy requires explicit user approval"
                    if spec.requires_approval or spec.risk_level in {RiskLevel.WRITE, RiskLevel.DESTRUCTIVE}
                    else "Agent owner requires confirmation for this tool"
                ),
                evaluated_at=now,
            )
        return PolicyDecision(
            decision=PolicyDecisionType.ALLOW,
            policy_refs=spec.policy_refs,
            reason="Policy checks passed",
            evaluated_at=now,
        )
