"""Focused tests for owner-scoped, bounded Agent Builder tool retrieval."""

import pytest

from core.tooling.capability_catalog import CapabilityCatalog
from core.tooling.tool_retriever import ToolRetriever


def _tool(
    tool_id: str,
    *,
    name: str,
    description: str,
    operation: str = "read",
    capabilities: list[str] | None = None,
) -> dict:
    return {
        "capability_id": tool_id,
        "version": "1.0.0",
        "name": name,
        "description": description,
        "spec": {
            "category": "knowledge",
            "risk_level": operation,
            "builder_metadata": {
                "capabilities": capabilities or [],
                "use_when": [],
                "avoid_when": [],
                "operation_type": operation,
            },
        },
    }


def test_rank_prefers_relevant_read_tool_and_rejects_unrelated_tool():
    notion = _tool(
        "notion.search",
        name="Notion Search",
        description="Search and retrieve Notion documents",
        capabilities=["search documents", "retrieve pages"],
    )
    email = _tool(
        "mail.send",
        name="Send Email",
        description="Send an email message",
        operation="write",
        capabilities=["send email"],
    )

    ranked_notion = ToolRetriever.rank(
        notion, "Search my Notion documents and summarize relevant pages"
    )
    ranked_email = ToolRetriever.rank(
        email, "Search my Notion documents and summarize relevant pages"
    )

    assert ranked_notion is not None
    assert ranked_notion.score > 0
    assert "notion" in ranked_notion.reason
    assert ranked_email is None


@pytest.mark.asyncio
async def test_search_returns_only_bounded_highest_ranked_tools(monkeypatch):
    documents = [
        _tool(
            f"docs.search_{index}",
            name=f"Document Search {index}",
            description="Search documents",
            capabilities=["search documents"],
        )
        for index in range(75)
    ]
    documents.append(
        _tool(
            "mail.send",
            name="Send Email",
            description="Send email",
            operation="write",
        )
    )

    async def stream(*, owner_user_id: str):
        assert owner_user_id == "user-123"
        for document in documents:
            yield document

    monkeypatch.setattr(
        CapabilityCatalog,
        "stream_active_tools_for_builder",
        stream,
    )

    result = await ToolRetriever.search(
        owner_user_id="user-123",
        query="Search documents",
        limit=7,
    )

    assert len(result) == 7
    assert all(item["capability_id"].startswith("docs.search_") for item in result)
    assert all(item["selection_reason"] for item in result)
    assert all(item["retrieval_score"] > 0 for item in result)


@pytest.mark.asyncio
async def test_search_returns_empty_when_no_tool_matches(monkeypatch):
    async def stream(*, owner_user_id: str):
        yield _tool(
            "mail.send",
            name="Send Email",
            description="Send email",
            operation="write",
        )

    monkeypatch.setattr(
        CapabilityCatalog,
        "stream_active_tools_for_builder",
        stream,
    )

    result = await ToolRetriever.search(
        owner_user_id="user-123",
        query="Analyze accounting invoices",
    )

    assert result == []
