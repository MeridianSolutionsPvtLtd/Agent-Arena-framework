"""Protocol-level tests for the internal MCP server."""

import asyncio

from mcp import Client

from core.tooling.native_mcp_server import mcp


def test_internal_mcp_lists_only_reusable_custom_agent_tools():
    async def list_names():
        async with Client(mcp) as client:
            response = await client.list_tools()
            return {tool.name for tool in response.tools}

    assert asyncio.run(list_names()) == {
        "extract_data_from_file",
        "summarize_content",
        "generate_report",
        "web_search",
        "speech_to_text",
        "send_email",
        "mailbox_tracker_graph",
    }
