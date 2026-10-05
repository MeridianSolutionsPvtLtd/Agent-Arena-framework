"""External MCP server validation and health contract tests."""

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from config import settings
from core.tooling.capability_catalog import CapabilityCatalog, CapabilityConflict
from core.tooling.mcp_health import (
    McpServerValidationService,
    require_recent_healthy_validation,
)
from models.capability import (
    AuthenticationMode,
    AuthenticationSpec,
    McpHealthStatus,
    McpRuntimeHealth,
    McpServerDefinitionSpec,
    McpServerKind,
    McpTransport,
    VersionedCapabilityRef,
)


class _HealthyClient:
    protocol_version = "2025-11-25"

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def list_tools(self):
        return SimpleNamespace(
            tools=[
                SimpleNamespace(
                    name="search_tickets",
                    input_schema={"type": "object"},
                    output_schema={"type": "object"},
                )
            ]
        )


def _server_record():
    return {
        "spec": McpServerDefinitionSpec(
            server_kind=McpServerKind.EXTERNAL,
            transport=McpTransport.STREAMABLE_HTTP,
            endpoint_ref="https://mcp.example.com/mcp",
            authentication=AuthenticationSpec(mode=AuthenticationMode.NONE),
            allowed_tool_names=["search_tickets", "create_ticket"],
        ).model_dump(mode="json")
    }


# Designed and implemented by Rajadurai R.
def test_validation_stores_safe_health_and_reports_allow_list_difference(monkeypatch):
    stored = {}

    async def fake_get(*args, **kwargs):
        return _server_record()

    async def fake_update(capability_id, version, health, *, actor_id):
        stored.update(health.model_dump(mode="json"))
        return {}

    monkeypatch.setattr(CapabilityCatalog, "get", fake_get)
    monkeypatch.setattr(CapabilityCatalog, "update_mcp_runtime_health", fake_update)
    service = McpServerValidationService(
        lambda value: value,
        client_factory=lambda endpoint, spec: _HealthyClient(),
    )

    result = asyncio.run(
        service.validate(
            VersionedCapabilityRef(capability_id="ticketing_mcp", version="1.0.0"),
            actor_id="user-1",
        )
    )

    assert result["status"] == "healthy"
    assert result["allowed_tools_found"] == ["search_tickets"]
    assert result["missing_allowed_tools"] == ["create_ticket"]
    assert result["unexpected_tools"] == []
    assert stored["last_error_code"] is None
    assert len(result["schema_fingerprint"]) == 64


def test_recent_health_is_required_and_expires(monkeypatch):
    monkeypatch.setattr(settings, "MCP_VALIDATION_MAX_AGE_SECONDS", 60)
    with pytest.raises(CapabilityConflict, match="validation first"):
        require_recent_healthy_validation({})

    expired = McpRuntimeHealth(
        status=McpHealthStatus.HEALTHY,
        checked_at=datetime.now(timezone.utc) - timedelta(minutes=2),
    )
    with pytest.raises(CapabilityConflict, match="expired"):
        require_recent_healthy_validation(
            {"runtime_health": expired.model_dump(mode="json")}
        )

    naive_recent = McpRuntimeHealth(
        status=McpHealthStatus.HEALTHY,
        checked_at=datetime.now(timezone.utc).replace(tzinfo=None),
    )
    require_recent_healthy_validation(
        {"runtime_health": naive_recent.model_dump(mode="json")}
    )
