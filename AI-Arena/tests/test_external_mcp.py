"""External MCP discovery governance tests."""

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

from core.tooling.external_mcp import ExternalMcpDiscoveryService
from core.tooling.mcp_tool_client import McpToolClient, _external_provider_error
from models.capability import (
    AuthenticationMode, AuthenticationSpec, CapabilityOwner, CapabilityStatus, ExecutionContext,
    McpHealthStatus, McpRuntimeHealth, McpServerDefinitionSpec, McpServerKind, McpTransport,
    McpToolCandidateSpec, ToolResultStatus, VersionedCapabilityRef,
)


class _ClientContext:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def list_tools(self):
        return SimpleNamespace(tools=[SimpleNamespace(
            name="Create-Ticket", description="Creates a ticket",
            input_schema={"type": "object", "properties": {"title": {"type": "string"}}},
            output_schema={"type": "object"},
        )])


def test_discovery_stages_draft_candidate_and_never_activates(monkeypatch):
    from core.tooling import external_mcp

    server_spec = McpServerDefinitionSpec(
        server_kind=McpServerKind.EXTERNAL,
        transport=McpTransport.STREAMABLE_HTTP,
        endpoint_ref="config://TICKETING_MCP_URL",
        authentication=AuthenticationSpec(mode=AuthenticationMode.NONE),
    )
    async def fake_get(*args, **kwargs):
        return {
            "spec": server_spec.model_dump(mode="json"),
            "owner": CapabilityOwner(team="user", contact="admin-1").model_dump(mode="json"),
            "runtime_health": McpRuntimeHealth(
                status=McpHealthStatus.HEALTHY,
                checked_at=datetime.now(timezone.utc),
                last_success_at=datetime.now(timezone.utc),
            ).model_dump(mode="json"),
        }

    stored = []
    async def fake_create(record, actor_id):
        stored.append(record)
        return record.model_dump(mode="json")

    monkeypatch.setattr(external_mcp.CapabilityCatalog, "get", staticmethod(fake_get))
    monkeypatch.setattr(external_mcp.CapabilityCatalog, "create", staticmethod(fake_create))
    service = ExternalMcpDiscoveryService(
        lambda ref: "https://mcp.example.com/mcp",
        client_factory=lambda endpoint, spec: _ClientContext(),
    )
    result = asyncio.run(service.discover(
        VersionedCapabilityRef(capability_id="ticketing_mcp", version="1.0.0"),
        actor_id="admin-1",
    ))
    assert len(result) == 1
    assert stored[0].status == CapabilityStatus.DRAFT
    assert stored[0].capability_id.startswith("ticketing_mcp.create_ticket_")
    assert stored[0].version.startswith("1.0.0+")


def test_discovery_bounds_oversized_provider_description(monkeypatch):
    """Large provider examples must not block tool review or Builder visibility."""
    from core.tooling import external_mcp

    oversized = "Retrieves details about a document. " + ("<example>data</example>" * 500)
    server_spec = McpServerDefinitionSpec(
        server_kind=McpServerKind.EXTERNAL,
        transport=McpTransport.STREAMABLE_HTTP,
        endpoint_ref="config://DOCUMENT_MCP_URL",
        authentication=AuthenticationSpec(mode=AuthenticationMode.NONE),
    )

    class LongDescriptionClient(_ClientContext):
        async def list_tools(self):
            return SimpleNamespace(tools=[SimpleNamespace(
                name="retrieve_document",
                description=oversized,
                input_schema={"type": "object"},
                output_schema={"type": "object"},
            )])

    async def fake_get(*args, **kwargs):
        return {
            "spec": server_spec.model_dump(mode="json"),
            "owner": CapabilityOwner(team="user", contact="user-1").model_dump(mode="json"),
            "runtime_health": McpRuntimeHealth(
                status=McpHealthStatus.HEALTHY,
                checked_at=datetime.now(timezone.utc),
                last_success_at=datetime.now(timezone.utc),
            ).model_dump(mode="json"),
        }

    stored = []

    async def fake_create(record, actor_id):
        stored.append(record)
        return record.model_dump(mode="json")

    monkeypatch.setattr(external_mcp.CapabilityCatalog, "get", staticmethod(fake_get))
    monkeypatch.setattr(external_mcp.CapabilityCatalog, "create", staticmethod(fake_create))
    service = ExternalMcpDiscoveryService(
        lambda ref: "https://mcp.example.com/mcp",
        client_factory=lambda endpoint, spec: LongDescriptionClient(),
    )

    result = asyncio.run(service.discover(
        VersionedCapabilityRef(capability_id="document_mcp", version="1.0.0"),
        actor_id="user-1",
    ))

    candidate_spec = McpToolCandidateSpec.model_validate(result[0]["spec"])
    assert len(result[0]["description"]) == 4000
    assert len(candidate_spec.remote_description) == 4000
    assert candidate_spec.remote_description.endswith("[Provider description truncated]")


# Designed and implemented by Rajadurai R.
def test_builder_metadata_inference_is_conservative():
    from core.tooling.external_mcp import infer_builder_metadata

    read_risk, read_metadata = infer_builder_metadata(
        "search_documents", "Search approved customer documents"
    )
    assert read_risk.value == "sensitive_read"
    assert read_metadata.operation_type == "read"
    assert read_metadata.requires_approval is False

    write_risk, write_metadata = infer_builder_metadata(
        "send_email", "Send an email to a recipient"
    )
    assert write_risk.value == "write"
    assert write_metadata.requires_approval is True

    destructive_risk, destructive_metadata = infer_builder_metadata(
        "delete_email", "Permanently remove an email"
    )
    assert destructive_risk.value == "destructive"
    assert destructive_metadata.requires_approval is True


def test_external_execution_rejects_operation_not_approved_by_server():
    spec = McpServerDefinitionSpec(
        server_kind=McpServerKind.EXTERNAL,
        transport=McpTransport.STREAMABLE_HTTP,
        endpoint_ref="https://mcp.example.com/mcp",
        authentication=AuthenticationSpec(mode=AuthenticationMode.NONE),
        allowed_tool_names=["read_ticket"],
    )

    result = asyncio.run(
        McpToolClient.call_external(
            spec,
            "delete_ticket",
            {},
            trace_id="trace-1",
            execution_id="execution-1",
            timeout_seconds=10,
            context=ExecutionContext(
                user_id="user-1",
                agent_id="agent-1",
                tenant_id="tenant-1",
                role="user",
                trace_id="trace-1",
            ),
        )
    )

    assert result.status == ToolResultStatus.REJECTED
    assert result.error.code == "mcp_tool_not_approved"


def test_external_provider_entitlement_error_is_safe_and_actionable():
    response = SimpleNamespace(
        content=[SimpleNamespace(
            text="This tool requires a Business plan or higher. "
            "https://provider.example/private-account-id"
        )]
    )

    error = _external_provider_error(response)

    assert error.code == "external_mcp_entitlement_required"
    assert error.retryable is False
    assert "private-account-id" not in error.message
    assert "https://" not in error.message


def test_external_provider_rate_limit_is_retryable_without_raw_payload():
    response = SimpleNamespace(
        content=[SimpleNamespace(text="Too many requests for workspace secret-123")]
    )

    error = _external_provider_error(response)

    assert error.code == "external_mcp_rate_limited"
    assert error.retryable is True
    assert "secret-123" not in error.message
