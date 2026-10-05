"""In-process MCP server for reusable Meridian native tools."""

from __future__ import annotations

import uuid
from typing import Any, Optional

from mcp.server import MCPServer

from core.tooling.native_tool_gateway import NativeToolGateway

# Designed and implemented by Rajadurai R.
# Existing in-process tools are exposed through one reusable MCP server.
def _server() -> MCPServer:
    return MCPServer(**{
        "name": "Meridian Native Tools",
        "description": "Governed reusable tools for Meridian custom agents.",
        "version": "1.0.0",
    })


mcp = _server()


async def _call(operation: str, arguments: dict[str, Any]) -> dict[str, Any]:
    # Route direct MCP calls through the same normalized native gateway.
    trace_id = f"mcp_{uuid.uuid4().hex}"
    result = await NativeToolGateway.call(
        operation,
        arguments,
        trace_id=trace_id,
        execution_id=f"mcp_direct_{uuid.uuid4().hex}",
        timeout_seconds=600,
    )
    return result.model_dump(mode="json")


@mcp.tool()
async def extract_data_from_file(file_path: str) -> dict[str, Any]:
    """Extract structured data from a broker-authorized uploaded file."""
    return await _call("extract_data_from_file", {"file_path": file_path})


@mcp.tool()
async def summarize_content(text: str) -> dict[str, Any]:
    """Summarize supplied text."""
    return await _call("summarize_content", {"text": text})


@mcp.tool()
async def generate_report(
    content: str, title: str, format: str = "markdown", persona: Optional[dict[str, Any]] = None
) -> dict[str, Any]:
    """Generate a structured Markdown or PDF business report."""
    return await _call("generate_report", {"content": content, "title": title, "format": format, "persona": persona})


@mcp.tool()
async def web_search(
    query: str = "", action: str = "search", target_url: str = "", region: str = "in-en",
    max_results: int = 8, checkin: str = "", checkout: str = "", strict_mode: bool = True,
    evidence_depth: int = 3,
) -> dict[str, Any]:
    """Search the public web or scrape an approved public URL."""
    return await _call("web_search", locals())


@mcp.tool()
async def speech_to_text(file_path: str) -> dict[str, Any]:
    """Transcribe a broker-authorized uploaded audio file."""
    return await _call("speech_to_text", {"file_path": file_path})


@mcp.tool()
async def send_email(recipient: str, subject: str, body: str) -> dict[str, Any]:
    """Send an approved email through the configured provider."""
    return await _call("send_email", {"recipient": recipient, "subject": subject, "body": body})


@mcp.tool()
async def mailbox_tracker_graph(
    action: str = "fetch_new", subject_contains: str = "", sender_domain: str = "",
    max_results: int = 10, include_attachments: bool = True, mark_as_read: bool = False,
    message_id: str = "", target_user: str = "me",
) -> dict[str, Any]:
    """Read, search, or mark mailbox messages through Microsoft Graph."""
    return await _call("mailbox_tracker_graph", locals())
