"""In-process native MCP execution boundary used by the Broker and MCP server."""

from __future__ import annotations

import asyncio
from typing import Any

from core.orchestration.registry import registry
from models.capability import ToolError, ToolResult, ToolResultStatus


# Designed and implemented by Rajadurai R.
# Prevent native MCP calls from bypassing the explicit runtime registry.
class NativeToolGateway:
    """Dispatch only explicitly registered operations and normalize responses."""

    @staticmethod
    async def call(
        operation: str,
        arguments: dict[str, Any],
        *,
        trace_id: str,
        execution_id: str,
        timeout_seconds: int,
    ) -> ToolResult:
        tool = registry.get_tool(operation)
        if tool is None:
            return ToolResult(
                status=ToolResultStatus.ERROR,
                trace_id=trace_id,
                tool_execution_id=execution_id,
                error=ToolError(code="tool_not_registered", message="Tool is not available"),
            )

        def invoke() -> Any:
            if hasattr(tool, "invoke"):
                return tool.invoke(arguments)
            if hasattr(tool, "_run"):
                return tool._run(**arguments)
            return tool(**arguments)

        try:
            value = await asyncio.wait_for(
                asyncio.to_thread(invoke), timeout=timeout_seconds
            )
            data = value if isinstance(value, dict) else {"content": str(value)}
            return ToolResult(
                status=ToolResultStatus.SUCCESS,
                data=data,
                trace_id=trace_id,
                tool_execution_id=execution_id,
            )
        except asyncio.TimeoutError:
            return ToolResult(
                status=ToolResultStatus.ERROR,
                trace_id=trace_id,
                tool_execution_id=execution_id,
                error=ToolError(
                    code="tool_timeout", message="Tool execution timed out", retryable=False
                ),
            )
        except Exception:
            return ToolResult(
                status=ToolResultStatus.ERROR,
                trace_id=trace_id,
                tool_execution_id=execution_id,
                error=ToolError(
                    code="tool_execution_failed",
                    message="Tool execution failed",
                    retryable=False,
                ),
            )
