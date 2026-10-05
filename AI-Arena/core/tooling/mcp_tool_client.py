"""MCP client adapter that normalizes protocol results for the Broker."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from mcp import Client

from models.capability import ToolError, ToolResult, ToolResultStatus
from models.capability import ExecutionContext, McpServerDefinitionSpec, McpServerPurpose


logger = logging.getLogger(__name__)


def _external_provider_error(response: Any) -> ToolError:
    """Map provider text to a safe category without returning the raw payload."""

    text = " ".join(
        str(getattr(item, "text", "")) for item in (getattr(response, "content", None) or [])
    ).casefold()
    if any(marker in text for marker in ("plan or higher", "plan required", "upgrade required")):
        return ToolError(
            code="external_mcp_entitlement_required",
            message="This MCP tool is unavailable for the connected provider account",
            retryable=False,
        )
    if any(marker in text for marker in ("rate limit", "too many requests")):
        return ToolError(
            code="external_mcp_rate_limited",
            message="The external MCP provider temporarily limited this request",
            retryable=True,
        )
    if any(marker in text for marker in ("unauthorized", "authentication required", "token expired")):
        return ToolError(
            code="external_mcp_authentication_required",
            message="The external MCP connection must be reconnected",
            retryable=False,
        )
    return ToolError(
        code="external_mcp_tool_rejected",
        message="The external MCP provider rejected this tool request",
        retryable=False,
    )


# Designed and implemented by Rajadurai R.
# This adapter is the final protocol boundary used by the Execution Broker.
class McpToolClient:
    @staticmethod
    async def call_internal(
        operation: str,
        arguments: dict[str, Any],
        *,
        trace_id: str,
        execution_id: str,
        timeout_seconds: int,
    ) -> ToolResult:
        from core.tooling.native_mcp_server import mcp

        try:
            async def invoke():
                async with Client(mcp, raise_exceptions=False) as client:
                    return await client.call_tool(operation, arguments)

            response = await asyncio.wait_for(invoke(), timeout=timeout_seconds)
            structured = response.structured_content
            if structured:
                result = ToolResult.model_validate(structured)
                return result.model_copy(
                    update={"trace_id": trace_id, "tool_execution_id": execution_id}
                )
            return ToolResult(
                status=ToolResultStatus.ERROR,
                trace_id=trace_id,
                tool_execution_id=execution_id,
                error=ToolError(code="invalid_mcp_result", message="MCP server returned an invalid result"),
            )
        except asyncio.TimeoutError:
            logger.warning(
                "Internal MCP tool timed out operation=%s trace_id=%s execution_id=%s",
                operation,
                trace_id,
                execution_id,
            )
            return ToolResult(
                status=ToolResultStatus.ERROR,
                trace_id=trace_id,
                tool_execution_id=execution_id,
                error=ToolError(
                    code="local_model_timeout",
                    message="The local model timed out while executing the MCP tool",
                    retryable=True,
                ),
            )
        except Exception as exc:
            logger.warning(
                "Internal MCP tool failed operation=%s error_type=%s trace_id=%s execution_id=%s",
                operation,
                type(exc).__name__,
                trace_id,
                execution_id,
            )
            return ToolResult(
                status=ToolResultStatus.ERROR,
                trace_id=trace_id,
                tool_execution_id=execution_id,
                error=ToolError(code="mcp_unavailable", message="MCP tool service is unavailable"),
            )

    @staticmethod
    async def call_external(
        server_spec: McpServerDefinitionSpec,
        operation: str,
        arguments: dict[str, Any],
        *,
        trace_id: str,
        execution_id: str,
        timeout_seconds: int,
        context: ExecutionContext,
    ) -> ToolResult:
        from core.tooling.external_mcp import managed_mcp_client, resolve_config_endpoint

        # SAFE ERROR BOUNDARY
        # -------------------
        # Provider responses may contain account IDs, workspace URLs, request
        # payloads, or OAuth details. The API receives only a stable category
        # and an actionable sentence. Server logs retain trace/execution IDs and
        # exception classes for operators, never credentials or raw arguments.
        try:
            import json
            from config import settings

            # Templates describe setup choices; only owner-created connections execute.
            if server_spec.purpose != McpServerPurpose.CONNECTION:
                return ToolResult(
                    status=ToolResultStatus.REJECTED,
                    trace_id=trace_id,
                    tool_execution_id=execution_id,
                    error=ToolError(
                        code="mcp_template_not_executable",
                        message="MCP templates cannot execute tools",
                    ),
                )

            # Enforce the reviewed allowlist even when the server exposes more tools.
            if operation not in server_spec.allowed_tool_names:
                return ToolResult(
                    status=ToolResultStatus.REJECTED,
                    trace_id=trace_id,
                    tool_execution_id=execution_id,
                    error=ToolError(
                        code="mcp_tool_not_approved",
                        message="MCP operation is not approved for this server version",
                    ),
                )
            if len(json.dumps(arguments, default=str).encode("utf-8")) > settings.MCP_MAX_REQUEST_BYTES:
                return ToolResult(
                    status=ToolResultStatus.ERROR,
                    trace_id=trace_id,
                    tool_execution_id=execution_id,
                    error=ToolError(
                        code="mcp_request_too_large",
                        message="MCP tool request exceeded the approved size limit",
                    ),
                )
            endpoint = resolve_config_endpoint(server_spec.endpoint_ref or "")

            async def invoke():
                async with managed_mcp_client(
                    endpoint,
                    server_spec,
                    user_id=context.user_id,
                ) as client:
                    return await client.call_tool(operation, arguments)

            response = await asyncio.wait_for(invoke(), timeout=timeout_seconds)
            if getattr(response, "is_error", False):
                error = _external_provider_error(response)
                logger.warning(
                    "External MCP provider rejected request category=%s trace_id=%s execution_id=%s",
                    error.code,
                    trace_id,
                    execution_id,
                )
                return ToolResult(
                    status=ToolResultStatus.ERROR,
                    trace_id=trace_id,
                    tool_execution_id=execution_id,
                    error=error,
                )
            data = response.structured_content or {
                "content": [
                    getattr(item, "text", str(item)) for item in (response.content or [])
                ]
            }
            if len(json.dumps(data, default=str).encode("utf-8")) > settings.MCP_MAX_RESPONSE_BYTES:
                return ToolResult(
                    status=ToolResultStatus.ERROR,
                    trace_id=trace_id,
                    tool_execution_id=execution_id,
                    error=ToolError(
                        code="mcp_response_too_large",
                        message="MCP tool response exceeded the approved size limit",
                    ),
                )
            return ToolResult(
                status=ToolResultStatus.SUCCESS,
                data=data if isinstance(data, dict) else {"result": data},
                trace_id=trace_id,
                tool_execution_id=execution_id,
            )
        except asyncio.TimeoutError:
            logger.warning(
                "External MCP request timed out trace_id=%s execution_id=%s",
                trace_id,
                execution_id,
            )
            return ToolResult(
                status=ToolResultStatus.ERROR,
                trace_id=trace_id,
                tool_execution_id=execution_id,
                error=ToolError(
                    code="external_mcp_timeout",
                    message="The external MCP provider did not respond in time",
                    retryable=True,
                ),
            )
        except ValueError as exc:
            exception_type = type(exc).__name__
            logger.warning(
                "External MCP authentication or configuration failure type=%s trace_id=%s execution_id=%s",
                exception_type,
                trace_id,
                execution_id,
            )
            return ToolResult(
                status=ToolResultStatus.ERROR,
                trace_id=trace_id,
                tool_execution_id=execution_id,
                error=ToolError(
                    code="external_mcp_connection_invalid",
                    message="The external MCP connection must be validated or reconnected",
                    retryable=False,
                ),
            )
        except Exception as exc:
            exception_type = type(exc).__name__
            logger.warning(
                "External MCP transport failure type=%s trace_id=%s execution_id=%s",
                exception_type,
                trace_id,
                execution_id,
            )
            return ToolResult(
                status=ToolResultStatus.ERROR,
                trace_id=trace_id,
                tool_execution_id=execution_id,
                error=ToolError(
                    code="external_mcp_unavailable",
                    message="The external MCP provider is temporarily unavailable",
                    retryable=True,
                ),
            )
