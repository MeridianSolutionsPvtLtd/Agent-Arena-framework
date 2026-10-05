"""Owner-scoped MCP template, connection, and OAuth boundary tests."""

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest

from config import settings
from core.tooling import mcp_connections
from core.tooling.mcp_connections import McpConnectionService
from core.tooling.capability_seed import build_mcp_templates
from core.tooling.external_mcp import canonical_endpoint, infer_builder_metadata
from core.tooling.mcp_oauth import McpOAuthError, McpOAuthService
from models.capability import (
    AuthenticationMode, AuthenticationSpec, CapabilityOwner,
    CapabilityStatus,
    McpServerDefinitionSpec, McpServerKind, McpToolCandidateSpec, McpTransport,
    McpServerPurpose,
    RiskLevel, ToolBuilderMetadata, VersionedCapabilityRef,
)
from services.keyvault_service import _validate_key_name


def test_official_templates_are_active_non_executable_and_secret_free():
    templates = build_mcp_templates()
    assert {record.capability_id for record, _ in templates} == {
        "template.github", "template.notion", "template.atlassian",
        "template.microsoft-learn", "template.google-drive",
    }
    for record, implementation_ref in templates:
        spec = McpServerDefinitionSpec.model_validate(record.spec)
        assert record.status == CapabilityStatus.ACTIVE
        assert spec.purpose == McpServerPurpose.TEMPLATE
        assert spec.authentication.secret_ref is None
        assert spec.endpoint_fingerprint is None
        assert implementation_ref.startswith("core.mcp.template.")


def test_endpoint_identity_is_canonical_and_per_owner_ready(monkeypatch):
    monkeypatch.setattr(settings, "APP_ENV", "development")
    first, first_hash = canonical_endpoint("https://MCP.EXAMPLE.COM:443/mcp/")
    second, second_hash = canonical_endpoint("https://mcp.example.com/mcp")
    assert first == second == "https://mcp.example.com/mcp"
    assert first_hash == second_hash


def test_unknown_tool_defaults_to_approval():
    risk, metadata = infer_builder_metadata("perform_action", "Performs an operation")
    assert risk.value == "sensitive_read"
    assert metadata.operation_type == "unknown"
    assert metadata.requires_approval is True


def test_credential_names_cannot_create_mongo_field_paths():
    assert _validate_key_name("MCP_USER_TOKEN") == "MCP_USER_TOKEN"
    with pytest.raises(ValueError):
        _validate_key_name("MCP.USER.TOKEN")
    with pytest.raises(ValueError):
        _validate_key_name("$MCP_TOKEN")


def test_no_auth_connection_is_owned_and_validated(monkeypatch):
    captured = {}

    async def fake_list(*args, **kwargs):
        return []

    async def fake_available(*args, **kwargs):
        captured["unique"] = kwargs

    async def fake_create(record, *, actor_id):
        captured["record"] = record
        return record.model_dump(mode="json")

    async def fake_validate(self, ref, *, actor_id):
        return {"status": "healthy", "tools": []}

    monkeypatch.setattr(mcp_connections.CapabilityCatalog, "list_owned_mcp_connections", fake_list)
    monkeypatch.setattr(mcp_connections.CapabilityCatalog, "assert_external_endpoint_available", fake_available)
    monkeypatch.setattr(mcp_connections.CapabilityCatalog, "create", fake_create)
    monkeypatch.setattr(mcp_connections.McpServerValidationService, "validate", fake_validate)
    monkeypatch.setattr(mcp_connections, "canonical_endpoint", lambda value: (value, "a" * 64))

    result = asyncio.run(McpConnectionService.connect(
        user_id="user-1", name="Public docs", template_ref=None,
        endpoint="https://docs.example.com/mcp",
        authentication_mode=AuthenticationMode.NONE, credential=None,
    ))
    assert result["validation"]["status"] == "healthy"
    assert captured["record"].owner.contact == "user-1"
    assert captured["unique"]["owner_user_id"] == "user-1"


def test_selected_mcp_tools_are_promoted_for_builder_without_agent(monkeypatch):
    """MCP approval publishes catalog tools before any agent blueprint exists."""

    server_spec = McpServerDefinitionSpec(
        server_kind=McpServerKind.EXTERNAL,
        transport=McpTransport.STREAMABLE_HTTP,
        endpoint_ref="https://mcp.example.com/mcp",
        authentication=AuthenticationSpec(mode=AuthenticationMode.NONE),
    )
    candidate_spec = McpToolCandidateSpec(
        mcp_server_ref=VersionedCapabilityRef(
            capability_id="mcp-connection", version="1.0.0"
        ),
        remote_tool_name="search_documents",
        remote_description="Search connected documents",
        input_schema={"type": "object"},
        output_schema={"type": "object"},
        schema_hash="a" * 64,
        suggested_risk_level=RiskLevel.SENSITIVE_READ,
        builder_metadata=ToolBuilderMetadata(
            capabilities=["Search connected documents"],
            use_when=["The user asks about connected documents"],
            operation_type="read",
            requires_approval=False,
        ),
        discovered_at=datetime.now(timezone.utc),
    )
    candidate = {
        "capability_id": "mcp-connection.search_documents_abc123",
        "name": "Search Documents",
        "description": "Search connected documents",
        "spec": candidate_spec.model_dump(mode="json"),
    }
    created = []
    transitions = []

    async def fake_get_owned(*args, **kwargs):
        return {
            "status": CapabilityStatus.DRAFT.value,
            "spec": server_spec.model_dump(mode="json"),
        }

    async def fake_discover(self, ref, *, actor_id):
        return [candidate]

    async def fake_set_allowed(*args, **kwargs):
        return None

    async def fake_create(record, *, actor_id):
        created.append(record)
        return record.model_dump(mode="json")

    async def fake_transition(kind, capability_id, version, **kwargs):
        transitions.append((kind, capability_id, kwargs["to_status"]))
        return {}

    monkeypatch.setattr(settings, "ENABLE_GOVERNED_TOOL_RUNTIME", True)
    monkeypatch.setattr(mcp_connections.CapabilityCatalog, "get_owned", fake_get_owned)
    monkeypatch.setattr(
        mcp_connections.ExternalMcpDiscoveryService, "discover", fake_discover
    )
    monkeypatch.setattr(
        mcp_connections.CapabilityCatalog, "set_owned_mcp_allowed_tools", fake_set_allowed
    )
    monkeypatch.setattr(mcp_connections.CapabilityCatalog, "create", fake_create)
    monkeypatch.setattr(
        mcp_connections.CapabilityCatalog, "transition_status", fake_transition
    )

    result = asyncio.run(McpConnectionService.select_tools(
        user_id="user-1",
        connection_id="mcp-connection",
        version="1.0.0",
        selected_tool_names=["search_documents"],
    ))

    assert result["next_action"] == "build_agent"
    assert result["tools"] == [{
        "tool_id": "mcp-connection.search_documents_abc123", "version": "1.0.0"
    }]
    assert created[0].owner.contact == "user-1"
    assert created[0].status == CapabilityStatus.DRAFT
    assert transitions[-1][2] == CapabilityStatus.ACTIVE


class _OAuthStateCollection:
    def __init__(self):
        self.document = None

    async def insert_one(self, document):
        self.document = document
        return SimpleNamespace(inserted_id=document["_id"])


def test_authentication_inspection_detects_oauth_challenge(monkeypatch):
    response = SimpleNamespace(
        status_code=401,
        headers={"WWW-Authenticate": 'Bearer resource_metadata="https://mcp.example.com/.well-known/oauth-protected-resource"'},
    )

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, *args, **kwargs):
            return response

    async def fake_resolve(endpoint):
        return None

    async def fake_metadata(endpoint):
        return {
            "client_id_metadata_document_supported": True,
            "registration_endpoint": None,
        }

    monkeypatch.setattr("core.tooling.mcp_oauth.httpx2.AsyncClient", lambda **kwargs: FakeClient())
    monkeypatch.setattr("core.tooling.mcp_oauth.validate_resolved_endpoint", fake_resolve)
    monkeypatch.setattr(McpOAuthService, "_metadata", fake_metadata)
    result = asyncio.run(McpOAuthService.inspect_authentication("https://mcp.example.com/mcp"))
    assert result["authentication_mode"] == "oauth2"
    assert result["next_action"] == "start_oauth"
    assert result["registration_methods"] == ["client_metadata_document", "user_provided"]


def test_oauth_start_uses_pkce_and_stores_no_plain_state(monkeypatch):
    collection = _OAuthStateCollection()
    monkeypatch.setattr("core.tooling.mcp_oauth._collection", lambda: collection)

    async def fake_metadata(endpoint):
        return {
            "resource": endpoint,
            "issuer": "https://identity.example.com",
            "authorization_endpoint": "https://identity.example.com/authorize",
            "token_endpoint": "https://identity.example.com/token",
            "registration_endpoint": None,
            "client_id_metadata_document_supported": True,
            "challenge_scope": "files.read",
        }

    monkeypatch.setattr(McpOAuthService, "_metadata", fake_metadata)
    result = asyncio.run(McpOAuthService.start(
        user_id="user-1", name="My workspace",
        endpoint="https://mcp.example.com/mcp", template_ref=None,
        callback_url="https://app.example.com/api/mcp/oauth/callback",
        client_metadata_url="https://app.example.com/api/mcp/oauth/client-metadata",
    ))
    query = parse_qs(urlsplit(result["authorization_url"]).query)
    assert query["code_challenge_method"] == ["S256"]
    assert query["client_id"] == ["https://app.example.com/api/mcp/oauth/client-metadata"]
    assert query["scope"] == ["files.read"]
    assert result["registration_method"] == "client_metadata_document"
    assert query["state"][0] not in str(collection.document)
    assert "payload_ciphertext" in collection.document


def test_oauth_uses_dynamic_registration_when_cimd_is_unavailable(monkeypatch):
    collection = _OAuthStateCollection()
    monkeypatch.setattr("core.tooling.mcp_oauth._collection", lambda: collection)

    async def fake_metadata(endpoint):
        return {
            "resource": endpoint,
            "issuer": "https://identity.example.com",
            "authorization_endpoint": "https://identity.example.com/authorize",
            "token_endpoint": "https://identity.example.com/token",
            "registration_endpoint": "https://identity.example.com/register",
            "client_id_metadata_document_supported": False,
            "challenge_scope": None,
        }

    async def fake_register(metadata, *, callback_url, client_name):
        return {
            "client_id": "dynamic-client",
            "client_secret": "dynamic-secret",
            "token_endpoint_auth_method": "client_secret_post",
            "registration_method": "dynamic",
        }

    monkeypatch.setattr(McpOAuthService, "_metadata", fake_metadata)
    monkeypatch.setattr(McpOAuthService, "_register_client", fake_register)
    result = asyncio.run(McpOAuthService.start(
        user_id="user-1", name="Dynamic workspace",
        endpoint="https://mcp.example.com/mcp", template_ref=None,
        callback_url="https://app.example.com/api/mcp/oauth/callback",
        client_metadata_url="https://app.example.com/api/mcp/oauth/client-metadata",
    ))
    query = parse_qs(urlsplit(result["authorization_url"]).query)
    assert query["client_id"] == ["dynamic-client"]
    assert result["registration_method"] == "dynamic"
    assert "dynamic-secret" not in str(collection.document)


def test_oauth_requires_ui_client_when_registration_is_unsupported(monkeypatch):
    async def fake_metadata(endpoint):
        return {
            "resource": endpoint,
            "issuer": "https://identity.example.com",
            "authorization_endpoint": "https://identity.example.com/authorize",
            "token_endpoint": "https://identity.example.com/token",
            "registration_endpoint": None,
            "client_id_metadata_document_supported": False,
            "challenge_scope": None,
        }

    monkeypatch.setattr(McpOAuthService, "_metadata", fake_metadata)
    with pytest.raises(McpOAuthError, match="provide an OAuth client ID"):
        asyncio.run(McpOAuthService.start(
            user_id="user-1", name="Unsupported workspace",
            endpoint="https://mcp.example.com/mcp", template_ref=None,
            callback_url="https://app.example.com/api/mcp/oauth/callback",
            client_metadata_url="https://app.example.com/api/mcp/oauth/client-metadata",
        ))


def test_oauth_callback_rejects_oversized_or_missing_parameters():
    with pytest.raises(McpOAuthError, match="callback parameters"):
        asyncio.run(McpOAuthService.callback(state="", code="code"))
    with pytest.raises(McpOAuthError, match="callback parameters"):
        asyncio.run(McpOAuthService.callback(state="state", code="x" * 5000))
