"""Provider and direct MCP transport security contracts."""

import asyncio

import pytest

from config import settings
from core.tooling.external_mcp import resolve_config_endpoint
from core.tooling.providers import get_secret_provider
from core.tooling.secrets import (
    EncryptedMongoSecretProvider,
    EnvironmentSecretProvider,
    SecretResolutionError,
)


def test_direct_mcp_requires_approved_host_in_production(monkeypatch):
    monkeypatch.setattr(settings, "APP_ENV", "production")
    monkeypatch.setattr(settings, "MCP_ALLOWED_ENDPOINT_HOSTS", ["approved.example.com"])

    assert resolve_config_endpoint("https://approved.example.com/mcp") == "https://approved.example.com/mcp"
    with pytest.raises(ValueError, match="not approved"):
        resolve_config_endpoint("https://unapproved.example.com/mcp")


def test_direct_mcp_rejects_private_ip_even_in_development(monkeypatch):
    monkeypatch.setattr(settings, "APP_ENV", "development")

    with pytest.raises(ValueError, match="private or local"):
        resolve_config_endpoint("https://127.0.0.1/mcp")


def test_secret_provider_is_selected_by_reference_scheme():
    assert isinstance(get_secret_provider("env://MCP_TOKEN"), EnvironmentSecretProvider)
    assert isinstance(get_secret_provider("mongodb-user://MCP_TOKEN"), EncryptedMongoSecretProvider)
    with pytest.raises(ValueError, match="Unsupported"):
        get_secret_provider("keyvault://MCP_TOKEN")


def test_environment_secret_provider_rejects_missing_secret(monkeypatch):
    monkeypatch.delenv("MISSING_MCP_SECRET", raising=False)
    with pytest.raises(SecretResolutionError, match="unavailable"):
        asyncio.run(EnvironmentSecretProvider().get_secret("env://MISSING_MCP_SECRET"))
