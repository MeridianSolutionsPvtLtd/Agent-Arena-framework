"""Governed external MCP discovery; discovered tools are never auto-activated."""

from __future__ import annotations

import hashlib
import json
import os
import re
import asyncio
import socket
from ipaddress import ip_address
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, Callable, Protocol

import httpx2
from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from urllib.parse import urlsplit, urlunsplit

from config import settings
from core.tooling.capability_catalog import CapabilityCatalog, CapabilityConflict
from models.capability import (
    CapabilityKind,
    CapabilityOwner,
    CapabilityRecord,
    CapabilityStatus,
    McpServerDefinitionSpec,
    McpServerKind,
    McpServerPurpose,
    McpToolCandidateSpec,
    RiskLevel,
    ToolBuilderMetadata,
    AuthenticationMode,
    VersionedCapabilityRef,
)


class EndpointResolver(Protocol):
    def __call__(self, endpoint_ref: str) -> str: ...


_MAX_TOOL_DESCRIPTION_LENGTH = 4000
_TRUNCATED_DESCRIPTION_SUFFIX = "\n[Provider description truncated]"


# Designed and implemented by Rajadurai R.
def _bounded_tool_description(value: Any) -> str:
    """Bound untrusted provider text while retaining useful builder context.

    Remote MCP descriptions may contain large examples or embedded markup. The
    catalog deliberately keeps a compact, visible description instead of
    rejecting the entire server or allowing unbounded provider-controlled text.
    """

    description = str(value or "").replace("\x00", "").strip()
    if len(description) <= _MAX_TOOL_DESCRIPTION_LENGTH:
        return description
    content_limit = _MAX_TOOL_DESCRIPTION_LENGTH - len(_TRUNCATED_DESCRIPTION_SUFFIX)
    shortened = description[:content_limit].rstrip()
    return f"{shortened}{_TRUNCATED_DESCRIPTION_SUFFIX}"


def _validate_external_endpoint(endpoint: str) -> str:
    from config import settings

    parsed = urlsplit(endpoint)
    if parsed.scheme.lower() != "https" or not parsed.hostname:
        raise ValueError("External MCP endpoint must use HTTPS")
    if parsed.username or parsed.password or parsed.fragment:
        raise ValueError("External MCP endpoint must not contain credentials or a fragment")
    hostname = parsed.hostname.lower().rstrip(".")
    try:
        address = ip_address(hostname)
    except ValueError:
        address = None
    if address and not address.is_global:
        raise ValueError("External MCP endpoint must not use a private or local IP address")
    allowed = {item.lower().rstrip(".") for item in settings.MCP_ALLOWED_ENDPOINT_HOSTS}
    # An optional allowlist supports locked-down deployments. An empty list is
    # the open-source self-service mode; public-DNS and SSRF checks still apply.
    if allowed and hostname not in allowed:
        raise ValueError("External MCP endpoint host is not approved")
    return endpoint


# Designed and implemented by Rajadurai R.
def canonical_endpoint(endpoint: str) -> tuple[str, str]:
    """Return a canonical public MCP URL and a non-reversible uniqueness hash."""

    validated = _validate_external_endpoint(endpoint.strip())
    parsed = urlsplit(validated)
    hostname = (parsed.hostname or "").lower().rstrip(".")
    port = parsed.port
    netloc = hostname if port in {None, 443} else f"{hostname}:{port}"
    path = parsed.path or "/mcp"
    if path != "/":
        path = path.rstrip("/")
    normalized = urlunsplit(("https", netloc, path, parsed.query, ""))
    return normalized, hashlib.sha256(normalized.encode("utf-8")).hexdigest()


async def validate_resolved_endpoint(endpoint: str) -> None:
    """Reject hostnames currently resolving to non-public networks."""

    hostname = urlsplit(endpoint).hostname
    if not hostname:
        raise ValueError("External MCP endpoint hostname is invalid")
    try:
        addresses = await asyncio.to_thread(
            socket.getaddrinfo, hostname, 443, type=socket.SOCK_STREAM
        )
    except socket.gaierror as exc:
        raise ValueError("External MCP endpoint hostname could not be resolved") from exc
    resolved = {item[4][0] for item in addresses}
    if not resolved or any(not ip_address(item).is_global for item in resolved):
        raise ValueError("External MCP endpoint resolved to a private or local address")


def resolve_config_endpoint(endpoint_ref: str) -> str:
    if endpoint_ref.lower().startswith("https://"):
        return _validate_external_endpoint(endpoint_ref)
    prefix = "config://"
    if not endpoint_ref.startswith(prefix):
        raise ValueError("MCP endpoint must use a config reference")
    key = endpoint_ref[len(prefix):]
    if not re.fullmatch(r"[A-Z][A-Z0-9_]{2,100}", key):
        raise ValueError("MCP endpoint configuration reference is invalid")
    value = os.getenv(key, "").strip()
    if not value:
        raise ValueError("MCP endpoint configuration is unavailable")
    return _validate_external_endpoint(value)


def _candidate_id(server_id: str, remote_name: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", remote_name.lower()).strip("_")
    digest = hashlib.sha256(remote_name.encode("utf-8")).hexdigest()[:10]
    return f"{server_id}.{normalized[:80] or 'tool'}_{digest}"


# Designed and implemented by Rajadurai R.
def infer_builder_metadata(
    name: str, description: str, annotations: dict[str, Any] | None = None,
    *, trusted_annotations: bool = False,
) -> tuple[RiskLevel, ToolBuilderMetadata]:
    """Create conservative, explainable planning hints from MCP-owned metadata."""

    text = f"{name} {description}".lower()
    tokens = {item for item in re.split(r"[^a-z0-9]+", text) if item}
    destructive = tokens & {"delete", "remove", "purge", "drop", "revoke", "cancel"}
    write = tokens & {
        "send", "create", "update", "write", "post", "publish", "approve", "pay", "execute"
    }
    sensitive = tokens & {"customer", "employee", "finance", "invoice", "medical", "private"}
    annotations = annotations or {}
    if destructive or (trusted_annotations and annotations.get("destructiveHint") is True):
        risk, operation = RiskLevel.DESTRUCTIVE, "destructive"
    elif write:
        risk, operation = RiskLevel.WRITE, "write"
    elif sensitive or (trusted_annotations and annotations.get("readOnlyHint") is True):
        risk, operation = RiskLevel.SENSITIVE_READ, "read"
    else:
        risk, operation = RiskLevel.SENSITIVE_READ, "unknown"
    capabilities = sorted((tokens & {
        "search", "read", "list", "summarize", "send", "create", "update", "delete",
        "email", "document", "calendar", "invoice", "customer", "file",
    }))[:20]
    friendly = name.replace("_", " ").replace("-", " ").strip()
    return risk, ToolBuilderMetadata(
        capabilities=capabilities or [operation],
        use_when=[f"The user asks to {friendly}."],
        avoid_when=[
            f"The request requires an operation other than {friendly}."
        ],
        operation_type=operation,
        requires_approval=(
            risk in {RiskLevel.WRITE, RiskLevel.DESTRUCTIVE} or operation == "unknown"
        ),
        inference_source=(
            "trusted_annotation" if trusted_annotations and annotations else "generated"
        ),
    )


# Designed and implemented by Rajadurai R.
# Discovery creates review candidates and never activates remote tools automatically.
class ExternalMcpDiscoveryService:
    def __init__(
        self,
        endpoint_resolver: EndpointResolver,
        client_factory: Callable[[str, McpServerDefinitionSpec], Any] | None = None,
    ):
        self.endpoint_resolver = endpoint_resolver
        self.client_factory = client_factory or managed_mcp_client

    async def discover(
        self,
        server_ref: VersionedCapabilityRef,
        *,
        actor_id: str,
    ) -> list[dict[str, Any]]:
        server_record = await CapabilityCatalog.get(
            CapabilityKind.MCP_SERVER,
            server_ref.capability_id,
            server_ref.version,
            allowed_statuses={
                CapabilityStatus.DRAFT,
                CapabilityStatus.REVIEW,
                CapabilityStatus.APPROVED,
                CapabilityStatus.ACTIVE,
            },
        )
        # Designed and implemented by Rajadurai R.
        from core.tooling.mcp_health import require_recent_healthy_validation

        require_recent_healthy_validation(server_record, allow_schema_changed=True)
        spec = McpServerDefinitionSpec.model_validate(server_record["spec"])
        if spec.server_kind != McpServerKind.EXTERNAL or spec.purpose != McpServerPurpose.CONNECTION:
            raise ValueError("Discovery is only available for external MCP servers")
        endpoint = self.endpoint_resolver(spec.endpoint_ref or "")
        if not endpoint.lower().startswith("https://"):
            raise ValueError("External MCP discovery requires an HTTPS endpoint")
        if self.client_factory is managed_mcp_client:
            await validate_resolved_endpoint(endpoint)

        client_context = (
            managed_mcp_client(endpoint, spec, user_id=actor_id)
            if self.client_factory is managed_mcp_client
            else self.client_factory(endpoint, spec)
        )
        async with client_context as client:
            response = await asyncio.wait_for(
                client.list_tools(), timeout=settings.MCP_SERVER_VALIDATION_TIMEOUT_SECONDS
            )

        if len(response.tools) > settings.MCP_MAX_DISCOVERED_TOOLS:
            raise ValueError("MCP server exposes too many tools")
        discovered_names = [str(tool.name) for tool in response.tools]
        if any(not name for name in discovered_names) or len(discovered_names) != len(
            set(discovered_names)
        ):
            raise ValueError("MCP server returned blank or duplicate tool names")

        candidates: list[dict[str, Any]] = []
        for tool in response.tools:
            description = _bounded_tool_description(tool.description)
            input_schema = tool.input_schema or {"type": "object"}
            output_schema = getattr(tool, "output_schema", None) or {}
            try:
                Draft202012Validator.check_schema(input_schema)
                Draft202012Validator.check_schema(output_schema)
            except SchemaError as exc:
                raise ValueError("MCP server returned an invalid tool schema") from exc
            canonical = json.dumps(
                {"input": input_schema, "output": output_schema},
                sort_keys=True,
                separators=(",", ":"),
            )
            schema_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
            raw_annotations = getattr(tool, "annotations", None)
            annotations = (
                raw_annotations.model_dump(by_alias=True)
                if hasattr(raw_annotations, "model_dump")
                else raw_annotations if isinstance(raw_annotations, dict) else {}
            )
            suggested_risk, builder_metadata = infer_builder_metadata(
                tool.name,
                description,
                annotations,
                trusted_annotations=spec.trust_level is not None,
            )
            candidate = CapabilityRecord(
                kind=CapabilityKind.MCP_TOOL_CANDIDATE,
                capability_id=_candidate_id(server_ref.capability_id, tool.name),
                version=f"1.0.0+{schema_hash[:12]}",
                status=CapabilityStatus.DRAFT,
                name=tool.name[:160],
                description=description,
                owner=CapabilityOwner.model_validate(server_record["owner"]),
                tags=["external", "mcp", "discovered"],
                spec=McpToolCandidateSpec(
                    mcp_server_ref=server_ref,
                    remote_tool_name=tool.name,
                    remote_description=description,
                    input_schema=input_schema,
                    output_schema=output_schema,
                    schema_hash=schema_hash,
                    suggested_risk_level=suggested_risk,
                    builder_metadata=builder_metadata,
                    discovered_at=datetime.now(timezone.utc),
                ).model_dump(mode="json"),
            )
            try:
                stored = await CapabilityCatalog.create(candidate, actor_id=actor_id)
            except CapabilityConflict:
                stored = await CapabilityCatalog.get(
                    CapabilityKind.MCP_TOOL_CANDIDATE,
                    candidate.capability_id,
                    candidate.version,
                )
            candidates.append(stored)
        return candidates


@asynccontextmanager
# Designed and implemented by Rajadurai R.
# All external sessions share endpoint validation and owner-scoped authentication.
async def managed_mcp_client(
    endpoint: str,
    spec: McpServerDefinitionSpec,
    *,
    user_id: str | None = None,
):
    """Create a direct authenticated MCP client from approved secret references."""
    endpoint = _validate_external_endpoint(endpoint)
    await validate_resolved_endpoint(endpoint)
    headers: dict[str, str] = {}
    if spec.authentication.mode == AuthenticationMode.NONE:
        pass
    elif spec.authentication.mode in {
        AuthenticationMode.API_KEY,
        AuthenticationMode.BEARER_TOKEN,
        AuthenticationMode.OAUTH2,
        AuthenticationMode.JWT,
    }:
        from core.tooling.providers import get_secret_provider

        secret_ref = spec.authentication.secret_ref or ""
        if spec.authentication.mode == AuthenticationMode.OAUTH2:
            if not user_id or not secret_ref.startswith("mongodb-user://"):
                raise ValueError("OAuth MCP connection requires an owned token reference")
            from services.keyvault_service import get_oauth_access_token

            secret = await get_oauth_access_token(
                user_id, secret_ref.removeprefix("mongodb-user://")
            )
        else:
            secret = await get_secret_provider(secret_ref).get_secret(
                secret_ref, user_id=user_id
            )
        if spec.authentication.mode == AuthenticationMode.API_KEY:
            headers["X-API-Key"] = secret
        else:
            headers["Authorization"] = f"Bearer {secret}"
    else:
        raise ValueError("External MCP authentication mode is not supported by direct transport")

    async with httpx2.AsyncClient(
        headers=headers,
        follow_redirects=False,
        timeout=httpx2.Timeout(30.0, read=300.0),
    ) as http_client:
        transport = streamable_http_client(endpoint, http_client=http_client)
        async with Client(transport) as client:
            yield client
