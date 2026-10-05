"""Authorization and safety tests for Capability Catalog APIs."""

import asyncio

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from middleware.auth import get_capability_admin
from models.capability import (
    AuthenticationMode,
    AuthenticationSpec,
    CapabilityKind,
    CapabilityStatus,
    McpServerDefinitionSpec,
    McpServerKind,
    McpToolCandidateSpec,
    McpTransport,
    RiskLevel,
    VersionedCapabilityRef,
)
from routers.capabilities import (
    CapabilityLifecycleRequest,
    McpToolPromotionRequest,
    _translate_catalog_error,
    _validate_activation_readiness,
    promote_mcp_tool_candidate,
)
from core.tooling.capability_catalog import (
    CapabilityCatalogUnavailable,
    CapabilityConflict,
    CapabilityNotFound,
)
from config import settings


def test_authenticated_user_can_manage_capabilities_during_rbac_migration(monkeypatch):
    monkeypatch.setattr(settings, "CAPABILITY_MANAGEMENT_ACCESS", "authenticated")
    user = {"_id": "user-1", "roles": []}
    assert asyncio.run(get_capability_admin(user)) == user


def test_ordinary_user_is_denied_when_admin_access_mode_is_enabled(monkeypatch):
    monkeypatch.setattr(settings, "CAPABILITY_MANAGEMENT_ACCESS", "admin")
    with pytest.raises(HTTPException) as captured:
        asyncio.run(get_capability_admin({"_id": "user-1", "roles": []}))
    assert captured.value.status_code == 403


@pytest.mark.parametrize(
    "user",
    [
        {"_id": "admin-1", "is_admin": True},
        {"_id": "admin-2", "roles": ["capability_admin"]},
        {"_id": "admin-3", "roles": "platform_admin"},
    ],
)
def test_explicit_capability_admin_roles_are_accepted(user, monkeypatch):
    monkeypatch.setattr(settings, "CAPABILITY_MANAGEMENT_ACCESS", "admin")
    assert asyncio.run(get_capability_admin(user)) == user


def test_mcp_candidate_cannot_be_activated():
    with pytest.raises(CapabilityConflict, match="promote the candidate"):
        asyncio.run(
            _validate_activation_readiness(
                CapabilityKind.MCP_TOOL_CANDIDATE, "server.remote_tool", "1.0.0"
            )
        )


def test_promote_candidate_copies_discovered_schema_and_builds_external_target(monkeypatch):
    server_ref = VersionedCapabilityRef(capability_id="ticketing", version="1.0.0")
    candidate = {
        "kind": "mcp_tool_candidate",
        "capability_id": "ticketing.create_ticket",
        "version": "1.0.0+abc",
        "status": "review",
        "name": "Create ticket",
        "description": "Creates a support ticket",
        "owner": {"team": "integration-governance", "contact": "user-1"},
        "source": None,
        "spec": McpToolCandidateSpec(
            mcp_server_ref=server_ref,
            remote_tool_name="create_ticket",
            input_schema={"type": "object", "properties": {"title": {"type": "string"}}},
            output_schema={"type": "object"},
            schema_hash="a" * 64,
            suggested_risk_level=RiskLevel.WRITE,
            discovered_at="2026-01-01T00:00:00Z",
        ).model_dump(mode="json"),
    }
    server = {
        "owner": {"team": "integration-governance", "contact": "user-1"},
        "status": "active",
        "spec": McpServerDefinitionSpec(
            server_kind=McpServerKind.EXTERNAL,
            transport=McpTransport.STREAMABLE_HTTP,
            endpoint_ref="https://mcp.example.com/mcp",
            authentication=AuthenticationSpec(mode=AuthenticationMode.NONE),
            allowed_tool_names=["create_ticket"],
        ).model_dump(mode="json")
    }
    created = {}

    async def fake_get(kind, capability_id, version, *, allowed_statuses=None):
        return candidate if kind == CapabilityKind.MCP_TOOL_CANDIDATE else server

    async def fake_create(record, *, actor_id):
        created["record"] = record
        created["actor_id"] = actor_id
        return record.model_dump(mode="json")

    from core.tooling.capability_catalog import CapabilityCatalog
    monkeypatch.setattr(CapabilityCatalog, "get", fake_get)
    monkeypatch.setattr(CapabilityCatalog, "create", fake_create)

    response = asyncio.run(
        promote_mcp_tool_candidate(
            "ticketing.create_ticket",
            "1.0.0+abc",
            McpToolPromotionRequest(
                tool_id="create_support_ticket",
                category="support",
                risk_level=RiskLevel.WRITE,
            ),
            {"_id": "user-1"},
        )
    )

    assert response["kind"] == "tool"
    assert response["status"] == "draft"
    assert response["spec"]["input_schema"] == candidate["spec"]["input_schema"]
    assert response["spec"]["execution_target"]["operation"] == "create_ticket"
    assert response["spec"]["execution_target"]["kind"] == "external_mcp"
    assert created["actor_id"] == "user-1"


def test_activation_is_blocked_until_runtime_exists(monkeypatch):
    from routers import capabilities

    monkeypatch.setattr(
        capabilities.settings, "ENABLE_GOVERNED_TOOL_RUNTIME", False
    )
    with pytest.raises(ValidationError, match="activation is disabled"):
        CapabilityLifecycleRequest(
            from_status=CapabilityStatus.APPROVED,
            to_status=CapabilityStatus.ACTIVE,
            reason="activate early",
        )


@pytest.mark.parametrize(
    ("error", "expected_status"),
    [
        (CapabilityNotFound("missing"), 404),
        (CapabilityConflict("conflict"), 409),
        (CapabilityCatalogUnavailable("down"), 503),
    ],
)
def test_repository_errors_are_translated_without_internal_details(error, expected_status):
    response = _translate_catalog_error(error)
    assert response.status_code == expected_status
    if expected_status == 503:
        assert "down" not in response.detail
