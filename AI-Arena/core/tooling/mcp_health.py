"""External MCP validation and safe operational health reporting."""

from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import datetime, timezone
from time import perf_counter
from typing import Any, Callable

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from config import settings
from core.tooling.capability_catalog import CapabilityCatalog, CapabilityConflict
from models.capability import (
    CapabilityKind,
    CapabilityStatus,
    McpHealthStatus,
    McpRuntimeHealth,
    McpServerDefinitionSpec,
    McpServerKind,
    McpServerPurpose,
    VersionedCapabilityRef,
)


class McpServerValidationFailed(RuntimeError):
    """Safe validation failure suitable for translation at the API boundary."""

    def __init__(self, code: str, message: str, *, status_code: int = 502):
        super().__init__(message)
        self.code = code
        self.status_code = status_code


def _tool_contract(tool: Any) -> dict[str, Any]:
    input_schema = getattr(tool, "input_schema", None) or {"type": "object"}
    output_schema = getattr(tool, "output_schema", None) or {}
    try:
        Draft202012Validator.check_schema(input_schema)
        Draft202012Validator.check_schema(output_schema)
    except SchemaError as exc:
        raise McpServerValidationFailed(
            "invalid_tool_schema", "MCP server returned an invalid tool schema"
        ) from exc
    raw_annotations = getattr(tool, "annotations", None)
    annotations = (
        raw_annotations.model_dump(by_alias=True)
        if hasattr(raw_annotations, "model_dump")
        else raw_annotations if isinstance(raw_annotations, dict) else {}
    )
    return {
        "name": str(getattr(tool, "name", "")),
        "description": str(getattr(tool, "description", "") or "")[:4000],
        "annotations": annotations,
        "input_schema": input_schema,
        "output_schema": output_schema,
    }


def _fingerprint(contracts: list[dict[str, Any]]) -> str:
    schema_contracts = [
        {
            "name": item["name"],
            "input_schema": item["input_schema"],
            "output_schema": item["output_schema"],
        }
        for item in contracts
    ]
    canonical = json.dumps(
        sorted(schema_contracts, key=lambda item: item["name"]),
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# Designed and implemented by Rajadurai R.
def require_recent_healthy_validation(
    server_record: dict[str, Any], *, allow_schema_changed: bool = False
) -> None:
    """Fail closed when discovery/activation lacks a recent healthy probe."""

    raw = server_record.get("runtime_health")
    if not raw:
        raise CapabilityConflict("MCP server must pass connection validation first")
    health = McpRuntimeHealth.model_validate(raw)
    checked_at = health.checked_at
    if checked_at.tzinfo is None:
        checked_at = checked_at.replace(tzinfo=timezone.utc)
    age = (datetime.now(timezone.utc) - checked_at).total_seconds()
    accepted = {McpHealthStatus.HEALTHY}
    if allow_schema_changed:
        accepted.add(McpHealthStatus.SCHEMA_CHANGED)
    if health.status not in accepted:
        raise CapabilityConflict("MCP server does not have a healthy validation result")
    if age < 0 or age > settings.MCP_VALIDATION_MAX_AGE_SECONDS:
        raise CapabilityConflict("MCP server validation has expired; validate it again")


# Designed and implemented by Rajadurai R.
class McpServerValidationService:
    """Validate one registered external MCP server without exposing credentials."""

    def __init__(self, endpoint_resolver: Callable[[str], str], client_factory=None):
        self.endpoint_resolver = endpoint_resolver
        self.client_factory = client_factory

    async def validate(
        self, server_ref: VersionedCapabilityRef, *, actor_id: str
    ) -> dict[str, Any]:
        # Designed and implemented by Rajadurai R.
        # Record a bounded contract fingerprint so schema drift is visible.
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
        spec = McpServerDefinitionSpec.model_validate(server_record["spec"])
        if spec.server_kind != McpServerKind.EXTERNAL or spec.purpose != McpServerPurpose.CONNECTION:
            raise McpServerValidationFailed(
                "not_connection", "Validation is only available for user MCP connections",
                status_code=409,
            )

        started = perf_counter()
        checked_at = datetime.now(timezone.utc)
        previous = server_record.get("runtime_health") or {}
        try:
            endpoint = self.endpoint_resolver(spec.endpoint_ref or "")
            if self.client_factory is None:
                from core.tooling.external_mcp import managed_mcp_client, validate_resolved_endpoint

                await validate_resolved_endpoint(endpoint)
                context = managed_mcp_client(endpoint, spec, user_id=actor_id)
            else:
                context = self.client_factory(endpoint, spec)
            async with context as client:
                response = await asyncio.wait_for(
                    client.list_tools(),
                    timeout=settings.MCP_SERVER_VALIDATION_TIMEOUT_SECONDS,
                )
                protocol_version = str(getattr(client, "protocol_version", "unknown"))

            tools = list(response.tools)
            if len(tools) > settings.MCP_MAX_DISCOVERED_TOOLS:
                raise McpServerValidationFailed(
                    "tool_limit_exceeded", "MCP server exposes too many tools"
                )
            contracts = [_tool_contract(tool) for tool in tools]
            names = [item["name"] for item in contracts]
            if any(not name for name in names) or len(names) != len(set(names)):
                raise McpServerValidationFailed(
                    "invalid_tool_names", "MCP server returned blank or duplicate tool names"
                )
            fingerprint = _fingerprint(contracts)
            elapsed = int((perf_counter() - started) * 1000)
            previous_fingerprint = previous.get("schema_fingerprint")
            schema_changed = bool(
                previous_fingerprint and previous_fingerprint != fingerprint
            )
            health = McpRuntimeHealth(
                status=(
                    McpHealthStatus.SCHEMA_CHANGED
                    if schema_changed
                    else McpHealthStatus.HEALTHY
                ),
                checked_at=checked_at,
                last_success_at=checked_at,
                response_time_ms=elapsed,
                protocol_version=protocol_version,
                discovered_tool_count=len(tools),
                schema_fingerprint=fingerprint,
                consecutive_failures=0,
            )
            await CapabilityCatalog.update_mcp_runtime_health(
                server_ref.capability_id,
                server_ref.version,
                health,
                actor_id=actor_id,
            )
            allowed = set(spec.allowed_tool_names)
            actual = set(names)
            from core.tooling.external_mcp import infer_builder_metadata

            tool_previews = []
            for contract in contracts:
                suggested_risk, builder_metadata = infer_builder_metadata(
                    contract["name"], contract["description"], contract["annotations"],
                    trusted_annotations=spec.trust_level is not None,
                )
                tool_previews.append({
                    "name": contract["name"],
                    "description": contract["description"],
                    "suggested_risk_level": suggested_risk.value,
                    "builder_metadata": builder_metadata.model_dump(mode="json"),
                })
            return {
                "server_id": server_ref.capability_id,
                "version": server_ref.version,
                "status": health.status.value,
                "protocol_version": protocol_version,
                "response_time_ms": elapsed,
                "tool_count": len(tools),
                "allowed_tools_found": sorted(allowed & actual),
                "missing_allowed_tools": sorted(allowed - actual),
                "unexpected_tools": sorted(actual - allowed),
                "schema_changed": schema_changed,
                "schema_fingerprint": fingerprint,
                "tools": tool_previews,
                "validated_at": checked_at.isoformat(),
            }
        except McpServerValidationFailed as exc:
            await self._record_failure(server_ref, actor_id, checked_at, previous, exc.code)
            raise
        except asyncio.TimeoutError as exc:
            await self._record_failure(server_ref, actor_id, checked_at, previous, "timeout")
            raise McpServerValidationFailed(
                "timeout", "MCP server validation timed out", status_code=504
            ) from exc
        except ValueError as exc:
            await self._record_failure(
                server_ref, actor_id, checked_at, previous, "configuration_invalid"
            )
            raise McpServerValidationFailed(
                "configuration_invalid", "MCP server configuration is invalid", status_code=409
            ) from exc
        except Exception as exc:
            status_code = getattr(getattr(exc, "response", None), "status_code", None)
            if status_code in {401, 403}:
                await self._record_failure(
                    server_ref, actor_id, checked_at, previous, "authentication_failed",
                    status=McpHealthStatus.AUTHENTICATION_FAILED,
                )
                raise McpServerValidationFailed(
                    "authentication_failed", "MCP authentication failed", status_code=401
                ) from exc
            await self._record_failure(server_ref, actor_id, checked_at, previous, "unavailable")
            raise McpServerValidationFailed(
                "unavailable", "MCP server validation failed"
            ) from exc

    @staticmethod
    async def _record_failure(
        server_ref: VersionedCapabilityRef,
        actor_id: str,
        checked_at: datetime,
        previous: dict[str, Any],
        error_code: str,
        status: McpHealthStatus = McpHealthStatus.UNAVAILABLE,
    ) -> None:
        # Persist safe failure codes only; never store provider response bodies.
        health = McpRuntimeHealth(
            status=status,
            checked_at=checked_at,
            last_success_at=previous.get("last_success_at"),
            discovered_tool_count=int(previous.get("discovered_tool_count") or 0),
            schema_fingerprint=previous.get("schema_fingerprint"),
            consecutive_failures=int(previous.get("consecutive_failures") or 0) + 1,
            last_error_code=error_code,
        )
        await CapabilityCatalog.update_mcp_runtime_health(
            server_ref.capability_id,
            server_ref.version,
            health,
            actor_id=actor_id,
        )
