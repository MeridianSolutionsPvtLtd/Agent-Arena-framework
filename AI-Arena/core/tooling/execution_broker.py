"""Governed routing boundary between agents and tool execution targets."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from jsonschema import Draft202012Validator

from core.tooling.capability_catalog import CapabilityCatalog
from core.tooling.mcp_tool_client import McpToolClient
from core.tooling.policy_engine import PolicyEngine
from core.tooling.tool_execution_store import ToolExecutionStore
from core.tooling.agent_tool_policy import AgentToolPolicy, AgentToolPolicyError
from models.agent import AgentToolGovernance
from models.capability import (
    ApprovalState,
    ApprovalStatus,
    ExecutionContext,
    ExecutionTargetKind,
    PolicyDecisionType,
    ToolDefinitionSpec,
    ToolExecutionStatus,
    ToolRef,
    ToolResult,
    ToolResultStatus,
    CapabilityKind,
    CapabilityStatus,
    McpServerDefinitionSpec,
    ToolError,
    ConnectorDefinitionSpec,
)


def _as_utc(value: datetime) -> datetime:
    """Normalize MongoDB's timezone-naive UTC datetimes before comparison."""

    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


# Designed and implemented by Rajadurai R.
# Single governed boundary for assignment, policy, approval, dispatch, and audit.
class ExecutionBroker:
    @staticmethod
    async def _dispatch(
        spec: ToolDefinitionSpec,
        arguments: dict[str, Any],
        *,
        trace_id: str,
        execution_id: str,
        context: ExecutionContext,
    ) -> ToolResult:
        # Dispatch only after the caller has resolved an exact active tool version.
        if spec.execution_target.kind == ExecutionTargetKind.NATIVE_MCP:
            return await McpToolClient.call_internal(
                spec.execution_target.operation, arguments, trace_id=trace_id,
                execution_id=execution_id, timeout_seconds=spec.timeout_seconds,
            )
        if spec.execution_target.kind == ExecutionTargetKind.EXTERNAL_MCP:
            server = await CapabilityCatalog.get(
                CapabilityKind.MCP_SERVER,
                spec.execution_target.target_ref.capability_id,
                spec.execution_target.target_ref.version,
                allowed_statuses={CapabilityStatus.ACTIVE},
            )
            return await McpToolClient.call_external(
                McpServerDefinitionSpec.model_validate(server["spec"]),
                spec.execution_target.operation, arguments, trace_id=trace_id,
                execution_id=execution_id, timeout_seconds=spec.timeout_seconds,
                context=context,
            )
        if spec.execution_target.kind == ExecutionTargetKind.CONNECTOR:
            from core.tooling.connector_runtime import ConnectorRuntime

            connector_record = await CapabilityCatalog.get(
                CapabilityKind.CONNECTOR,
                spec.execution_target.target_ref.capability_id,
                spec.execution_target.target_ref.version,
                allowed_statuses={CapabilityStatus.ACTIVE},
            )
            return await ConnectorRuntime.execute(
                spec.execution_target.target_ref.capability_id,
                spec.execution_target.target_ref.version,
                spec.execution_target.operation,
                arguments,
                context,
                ConnectorDefinitionSpec.model_validate(connector_record["spec"]),
            )
        return ToolResult(
            status=ToolResultStatus.ERROR,
            trace_id=trace_id,
            tool_execution_id=execution_id,
            error={"code": "target_not_enabled", "message": "Execution target is not enabled"},
        )

    @classmethod
    async def _safe_dispatch(
        cls,
        spec: ToolDefinitionSpec,
        arguments: dict[str, Any],
        *,
        trace_id: str,
        execution_id: str,
        context: ExecutionContext,
    ) -> ToolResult:
        try:
            result = await cls._dispatch(
                spec, arguments, trace_id=trace_id, execution_id=execution_id,
                context=context,
            )
            if result.status == ToolResultStatus.SUCCESS:
                # Older code-owned native contracts describe the normalized
                # ToolResult envelope, while promoted external MCP contracts
                # describe only the remote operation payload. Support both
                # explicit contract shapes without weakening either schema.
                schema_properties = spec.output_schema.get("properties") or {}
                schema_required = set(spec.output_schema.get("required") or [])
                normalized_envelope = (
                    isinstance(schema_properties, dict)
                    and {"status", "data"}.issubset(schema_properties)
                    and {"status", "data"}.issubset(schema_required)
                )
                validation_value = (
                    {
                        "status": result.status.value,
                        "data": result.data,
                        "artifacts": [item.model_dump(mode="json") for item in result.artifacts],
                        "citations": [item.model_dump(mode="json") for item in result.citations],
                    }
                    if normalized_envelope
                    else result.data
                )
                errors = list(
                    Draft202012Validator(spec.output_schema).iter_errors(
                        validation_value
                    )
                )
                if errors:
                    return ToolResult(
                        status=ToolResultStatus.ERROR,
                        trace_id=trace_id,
                        tool_execution_id=execution_id,
                        error=ToolError(
                            code="invalid_tool_output",
                            message="Tool output did not match its approved contract",
                        ),
                    )
            return result
        except Exception:
            return ToolResult(
                status=ToolResultStatus.ERROR,
                trace_id=trace_id,
                tool_execution_id=execution_id,
                error=ToolError(
                    code="execution_target_failed",
                    message="Execution target failed",
                    retryable=False,
                ),
            )

    @classmethod
    async def execute(
        cls,
        tool_ref: ToolRef,
        arguments: dict[str, Any],
        context: ExecutionContext,
        *,
        idempotency_key: Optional[str] = None,
        allowed_file_paths: Optional[list[str]] = None,
    ) -> ToolResult:
        try:
            governance = await AgentToolPolicy.resolve(context, tool_ref)
        except AgentToolPolicyError:
            execution = await ToolExecutionStore.create(
                tool_ref,
                context,
                arguments,
                idempotency_key=None,
                agent_governance=AgentToolGovernance(),
            )
            execution_id = execution["tool_execution_id"]
            await ToolExecutionStore.transition(
                execution_id,
                from_status=ToolExecutionStatus.CREATED,
                to_status=ToolExecutionStatus.POLICY_CHECK,
            )
            result = ToolResult(
                status=ToolResultStatus.REJECTED,
                trace_id=context.trace_id,
                tool_execution_id=execution_id,
                metadata={"reason": "Tool is not assigned to the current agent"},
            )
            await ToolExecutionStore.transition(
                execution_id,
                from_status=ToolExecutionStatus.POLICY_CHECK,
                to_status=ToolExecutionStatus.REJECTED,
                result=result,
            )
            return result
        capability = await CapabilityCatalog.get_active_tool(tool_ref)
        spec = ToolDefinitionSpec.model_validate(capability["spec"])
        AgentToolPolicy.validate_governance(governance, spec)
        effective_spec = AgentToolPolicy.effective_spec(spec, governance)
        effective_arguments = AgentToolPolicy.effective_arguments(
            arguments, governance, effective_spec
        )
        execution = await ToolExecutionStore.create(
            tool_ref,
            context,
            effective_arguments,
            idempotency_key=idempotency_key,
            agent_governance=governance,
        )
        execution_id = execution["tool_execution_id"]
        if execution.get("_deduplicated"):
            stored_result = execution.get("result")
            if stored_result:
                return ToolResult.model_validate(stored_result)
            if execution["status"] == ToolExecutionStatus.PENDING_APPROVAL.value:
                return ToolResult(
                    status=ToolResultStatus.PENDING_APPROVAL,
                    trace_id=context.trace_id,
                    tool_execution_id=execution_id,
                    metadata={"deduplicated": True},
                )
            return ToolResult(
                status=ToolResultStatus.ERROR,
                trace_id=context.trace_id,
                tool_execution_id=execution_id,
                error=ToolError(
                    code="execution_already_in_progress",
                    message="An execution with this idempotency key already exists",
                    retryable=True,
                ),
                metadata={"deduplicated": True, "existing_status": execution["status"]},
            )

        await ToolExecutionStore.transition(
            execution_id,
            from_status=ToolExecutionStatus.CREATED,
            to_status=ToolExecutionStatus.POLICY_CHECK,
        )
        decision = PolicyEngine.evaluate(
            effective_spec,
            context,
            effective_arguments,
            allowed_file_paths=allowed_file_paths,
            agent_governance=governance,
        )
        if decision.decision == PolicyDecisionType.DENY:
            result = ToolResult(
                status=ToolResultStatus.REJECTED,
                trace_id=context.trace_id,
                tool_execution_id=execution_id,
                metadata={"reason": decision.reason},
            )
            await ToolExecutionStore.transition(
                execution_id,
                from_status=ToolExecutionStatus.POLICY_CHECK,
                to_status=ToolExecutionStatus.REJECTED,
                result=result,
            )
            return result
        if decision.decision == PolicyDecisionType.APPROVAL_REQUIRED:
            now = datetime.now(timezone.utc)
            approval = ApprovalState(
                required=True,
                status=ApprovalStatus.PENDING,
                requested_at=now,
                expires_at=now + timedelta(minutes=15),
            )
            await ToolExecutionStore.transition(
                execution_id,
                from_status=ToolExecutionStatus.POLICY_CHECK,
                to_status=ToolExecutionStatus.PENDING_APPROVAL,
                approval=approval,
            )
            return ToolResult(
                status=ToolResultStatus.PENDING_APPROVAL,
                trace_id=context.trace_id,
                tool_execution_id=execution_id,
                metadata={"expires_at": approval.expires_at.isoformat()},
            )

        await ToolExecutionStore.transition(
            execution_id,
            from_status=ToolExecutionStatus.POLICY_CHECK,
            to_status=ToolExecutionStatus.RUNNING,
        )
        result = await cls._safe_dispatch(
            effective_spec, effective_arguments, trace_id=context.trace_id, execution_id=execution_id,
            context=context,
        )
        final_status = (
            ToolExecutionStatus.SUCCESS
            if result.status == ToolResultStatus.SUCCESS
            else ToolExecutionStatus.ERROR
        )
        await ToolExecutionStore.transition(
            execution_id,
            from_status=ToolExecutionStatus.RUNNING,
            to_status=final_status,
            result=result,
        )
        return result

    @classmethod
    async def resume_approved(
        cls,
        execution_id: str,
        arguments: Optional[dict[str, Any]],
        context: ExecutionContext,
        *,
        allowed_file_paths: Optional[list[str]] = None,
    ) -> ToolResult:
        execution = await ToolExecutionStore.get_owned(
            execution_id, context.user_id, context.tenant_id
        )
        tool_ref = ToolRef.model_validate(execution["tool_ref"])
        try:
            governance = await AgentToolPolicy.resolve(context, tool_ref)
        except AgentToolPolicyError as exc:
            raise ValueError("Tool is no longer assigned to the current agent") from exc
        current_governance = governance.model_dump(mode="json", exclude_none=True)
        if current_governance != (execution.get("agent_governance") or {}):
            raise ValueError("Agent tool governance changed after approval; start a new execution")
        approved_arguments = arguments or ToolExecutionStore.decrypt_arguments(
            execution.get("payload_ciphertext") or ""
        )
        if execution.get("input_hash") != ToolExecutionStore.hash_arguments(approved_arguments):
            raise ValueError("Resubmitted arguments do not match the approved request")
        approval = ApprovalState.model_validate(execution.get("approval") or {})
        if approval.status != ApprovalStatus.APPROVED:
            raise ValueError("Execution has not been approved")
        if approval.expires_at and _as_utc(approval.expires_at) <= datetime.now(timezone.utc):
            await ToolExecutionStore.transition(
                execution_id,
                from_status=ToolExecutionStatus.PENDING_APPROVAL,
                to_status=ToolExecutionStatus.EXPIRED,
            )
            raise ValueError("Approval has expired")
        capability = await CapabilityCatalog.get_active_tool(tool_ref)
        spec = ToolDefinitionSpec.model_validate(capability["spec"])
        AgentToolPolicy.validate_governance(governance, spec)
        effective_spec = AgentToolPolicy.effective_spec(spec, governance)
        path_decision = PolicyEngine.evaluate(
            effective_spec,
            context,
            approved_arguments,
            allowed_file_paths=allowed_file_paths,
            agent_governance=governance,
        )
        if path_decision.decision == PolicyDecisionType.DENY:
            raise ValueError(path_decision.reason)
        await ToolExecutionStore.transition(
            execution_id,
            from_status=ToolExecutionStatus.PENDING_APPROVAL,
            to_status=ToolExecutionStatus.RUNNING,
            approval=approval,
        )
        result = await cls._safe_dispatch(
            effective_spec, approved_arguments, trace_id=context.trace_id, execution_id=execution_id,
            context=context,
        )
        final_status = ToolExecutionStatus.SUCCESS if result.status == ToolResultStatus.SUCCESS else ToolExecutionStatus.ERROR
        await ToolExecutionStore.transition(
            execution_id,
            from_status=ToolExecutionStatus.RUNNING,
            to_status=final_status,
            result=result,
        )
        return result
