"""Owner-scoped orchestration for non-technical MCP connection onboarding."""

from __future__ import annotations

import uuid
from typing import Any

from config import settings
from core.tooling.capability_catalog import (
    CapabilityCatalog,
    CapabilityConflict,
)
from core.tooling.external_mcp import (
    ExternalMcpDiscoveryService,
    canonical_endpoint,
    resolve_config_endpoint,
)
from core.tooling.mcp_health import McpServerValidationService
from models.capability import (
    AuthenticationMode,
    AuthenticationSpec,
    CapabilityKind,
    CapabilityOwner,
    CapabilityRecord,
    CapabilityStatus,
    ExecutionTarget,
    ExecutionTargetKind,
    McpServerDefinitionSpec,
    McpServerKind,
    McpServerPurpose,
    McpToolCandidateSpec,
    McpTransport,
    ToolDefinitionSpec,
    ToolRef,
    VersionedCapabilityRef,
)


# Designed and implemented by Rajadurai R.
class McpConnectionService:
    """Compose catalog, secret, validation, discovery and agent APIs safely."""

    VERSION = "1.0.0"

    @staticmethod
    async def connect(
        *,
        user_id: str,
        name: str,
        template_ref: VersionedCapabilityRef | None,
        endpoint: str | None,
        authentication_mode: AuthenticationMode | None,
        credential: str | None,
        allow_oauth_internal: bool = False,
    ) -> dict[str, Any]:
        # Resolve immutable template defaults, then create a user-owned connection.
        template = None
        if template_ref:
            template = await CapabilityCatalog.get(
                CapabilityKind.MCP_SERVER,
                template_ref.capability_id,
                template_ref.version,
                allowed_statuses={CapabilityStatus.ACTIVE},
            )
            if not template.get("code_owned"):
                raise CapabilityConflict("MCP template is not platform approved")
            template_spec = McpServerDefinitionSpec.model_validate(template["spec"])
            if template_spec.purpose != McpServerPurpose.TEMPLATE:
                raise CapabilityConflict("Selected capability is not an MCP template")
        else:
            template_spec = None

        chosen_endpoint = endpoint or (template_spec.endpoint_ref if template_spec else None)
        if not chosen_endpoint:
            raise ValueError("MCP endpoint is required")
        normalized_endpoint, fingerprint = canonical_endpoint(chosen_endpoint)
        if template_spec and template_spec.endpoint_ref:
            template_endpoint, _ = canonical_endpoint(template_spec.endpoint_ref)
            if normalized_endpoint != template_endpoint:
                raise CapabilityConflict("Official template endpoint cannot be overridden")
        if (
            template_spec
            and authentication_mode is not None
            and authentication_mode != template_spec.authentication.mode
        ):
            raise CapabilityConflict("Template authentication mode cannot be overridden")
        mode = authentication_mode or (
            template_spec.authentication.mode if template_spec else AuthenticationMode.NONE
        )
        if mode == AuthenticationMode.OAUTH2 and not allow_oauth_internal:
            raise CapabilityConflict("OAuth connections must begin with the OAuth start endpoint")

        # Quota and canonical identity prevent accidental duplicate connections.
        existing = await CapabilityCatalog.list_owned_mcp_connections(
            user_id, limit=settings.MCP_MAX_CONNECTIONS_PER_USER
        )
        if len(existing) >= settings.MCP_MAX_CONNECTIONS_PER_USER:
            raise CapabilityConflict("MCP connection limit has been reached")

        capability_id = f"mcp-{uuid.uuid4().hex}"
        await CapabilityCatalog.assert_external_endpoint_available(
            fingerprint, capability_id=capability_id, owner_user_id=user_id
        )
        secret_key = None
        if mode != AuthenticationMode.NONE:
            if not credential:
                raise ValueError("This MCP connection requires a credential")
            secret_key = f"MCP_{uuid.uuid4().hex.upper()}"
            from services.keyvault_service import set_credential

            await set_credential(user_id, secret_key, credential)
        authentication = AuthenticationSpec(
            mode=mode,
            secret_ref=f"mongodb-user://{secret_key}" if secret_key else None,
        )
        record = CapabilityRecord(
            kind=CapabilityKind.MCP_SERVER,
            capability_id=capability_id,
            version=McpConnectionService.VERSION,
            status=CapabilityStatus.DRAFT,
            name=name,
            description=(template or {}).get("description", "User-connected MCP server"),
            owner=CapabilityOwner(team="user", contact=user_id),
            tags=["external", "mcp", "connection"],
            spec=McpServerDefinitionSpec(
                purpose=McpServerPurpose.CONNECTION,
                server_kind=McpServerKind.EXTERNAL,
                transport=McpTransport.STREAMABLE_HTTP,
                endpoint_ref=normalized_endpoint,
                authentication=authentication,
                template_ref=template_ref,
                category=template_spec.category if template_spec else "custom",
                icon=template_spec.icon if template_spec else "mcp",
                trust_level=template_spec.trust_level if template_spec else None,
                maturity=template_spec.maturity if template_spec else None,
                endpoint_fingerprint=fingerprint,
            ).model_dump(mode="json"),
        )
        try:
            stored = await CapabilityCatalog.create(record, actor_id=user_id)
        except Exception:
            if secret_key:
                from services.keyvault_service import delete_credential

                try:
                    await delete_credential(user_id, secret_key)
                except Exception:
                    pass
            raise

        # Return only after real MCP validation provides a safe tool preview.
        validation = await McpServerValidationService(resolve_config_endpoint).validate(
            VersionedCapabilityRef(capability_id=capability_id, version=McpConnectionService.VERSION),
            actor_id=user_id,
        )
        return {"connection": stored, "validation": validation}

    @staticmethod
    async def select_tools(
        *, user_id: str, connection_id: str, version: str,
        selected_tool_names: list[str],
    ) -> dict[str, Any]:
        if not settings.ENABLE_GOVERNED_TOOL_RUNTIME:
            raise CapabilityConflict(
                "Governed tool runtime must be enabled before approving MCP tools"
            )
        if not selected_tool_names:
            raise ValueError("Select at least one MCP tool")
        selected = list(dict.fromkeys(selected_tool_names))
        if len(selected) > settings.MCP_MAX_ACTIVE_TOOLS_PER_AGENT:
            raise CapabilityConflict("Selected tools exceed the connection approval limit")

        server = await CapabilityCatalog.get_owned(
            CapabilityKind.MCP_SERVER, connection_id, version, user_id
        )
        server_spec = McpServerDefinitionSpec.model_validate(server["spec"])
        if server_spec.purpose != McpServerPurpose.CONNECTION:
            raise CapabilityConflict("MCP templates cannot publish user tools")

        # Re-discover so stale or invented remote tool names cannot be attached.
        discovered = await ExternalMcpDiscoveryService(resolve_config_endpoint).discover(
            VersionedCapabilityRef(capability_id=connection_id, version=version),
            actor_id=user_id,
        )
        by_name = {
            McpToolCandidateSpec.model_validate(item["spec"]).remote_tool_name: item
            for item in discovered
        }
        missing = sorted(set(selected) - set(by_name))
        if missing:
            raise CapabilityConflict("Selected MCP tools are not present in the latest discovery")

        await CapabilityCatalog.set_owned_mcp_allowed_tools(
            connection_id, version, user_id, selected
        )
        current = CapabilityStatus(server["status"])
        lifecycle = {
            CapabilityStatus.DRAFT: (
                CapabilityStatus.REVIEW, CapabilityStatus.APPROVED, CapabilityStatus.ACTIVE
            ),
            CapabilityStatus.REVIEW: (
                CapabilityStatus.APPROVED, CapabilityStatus.ACTIVE
            ),
            CapabilityStatus.APPROVED: (CapabilityStatus.ACTIVE,),
            CapabilityStatus.ACTIVE: (),
        }.get(current)
        if lifecycle is None:
            raise CapabilityConflict("MCP connection is not eligible for tool approval")
        for target in lifecycle:
            await CapabilityCatalog.transition_status(
                CapabilityKind.MCP_SERVER, connection_id, version,
                from_status=current, to_status=target, actor_id=user_id,
                reason="Owner reviewed and selected discovered MCP tools",
            )
            current = target

        tool_refs: list[ToolRef] = []
        for remote_name in selected:
            candidate = by_name[remote_name]
            candidate_spec = McpToolCandidateSpec.model_validate(candidate["spec"])
            tool_id = candidate["capability_id"]
            tool = CapabilityRecord(
                kind=CapabilityKind.TOOL,
                capability_id=tool_id,
                version="1.0.0",
                status=CapabilityStatus.DRAFT,
                name=candidate["name"],
                description=candidate.get("description", ""),
                owner=CapabilityOwner(team="user", contact=user_id),
                tags=["external", "mcp", "selected"],
                spec=ToolDefinitionSpec(
                    category=server_spec.category or "external_mcp",
                    risk_level=candidate_spec.suggested_risk_level,
                    input_schema=candidate_spec.input_schema,
                    output_schema=candidate_spec.output_schema,
                    execution_target=ExecutionTarget(
                        kind=ExecutionTargetKind.EXTERNAL_MCP,
                        target_ref=VersionedCapabilityRef(
                            capability_id=connection_id, version=version
                        ),
                        operation=remote_name,
                    ),
                    supports_files=False,
                    idempotent=candidate_spec.builder_metadata.operation_type == "read",
                    timeout_seconds=60,
                    max_attempts=1,
                    # Generated builder metadata is advisory. If it is absent,
                    # use the reviewed risk level as the conservative default;
                    # the Execution Broker still enforces the stored spec.
                    requires_approval=(
                        candidate_spec.builder_metadata.requires_approval
                        if candidate_spec.builder_metadata.requires_approval is not None
                        else candidate_spec.suggested_risk_level.value in {"write", "destructive"}
                    ),
                    builder_metadata=candidate_spec.builder_metadata,
                ).model_dump(mode="json"),
            )
            try:
                await CapabilityCatalog.create(tool, actor_id=user_id)
                tool_status = CapabilityStatus.DRAFT
                for target in (
                    CapabilityStatus.REVIEW, CapabilityStatus.APPROVED, CapabilityStatus.ACTIVE
                ):
                    await CapabilityCatalog.transition_status(
                        CapabilityKind.TOOL, tool_id, "1.0.0",
                        from_status=tool_status, to_status=target, actor_id=user_id,
                        reason="Owner selected tool from validated MCP discovery",
                    )
                    tool_status = target
            except CapabilityConflict:
                await CapabilityCatalog.get_active_tool(
                    ToolRef(tool_id=tool_id, version="1.0.0"), owner_user_id=user_id
                )
            tool_refs.append(ToolRef(tool_id=tool_id, version="1.0.0"))
        return {
            "connection_id": connection_id,
            "version": version,
            "tools": [item.model_dump() for item in tool_refs],
            "next_action": "build_agent",
        }

    @staticmethod
    async def reconnect(
        *, user_id: str, connection_id: str, version: str, credential: str
    ) -> dict[str, Any]:
        # Replace only this owner's encrypted credential, then validate immediately.
        record = await CapabilityCatalog.get_owned(
            CapabilityKind.MCP_SERVER, connection_id, version, user_id
        )
        spec = McpServerDefinitionSpec.model_validate(record["spec"])
        secret_ref = spec.authentication.secret_ref or ""
        if not secret_ref.startswith("mongodb-user://"):
            raise CapabilityConflict("This connection does not use an editable user credential")
        from services.keyvault_service import set_credential

        await set_credential(user_id, secret_ref.removeprefix("mongodb-user://"), credential)
        return await McpServerValidationService(resolve_config_endpoint).validate(
            VersionedCapabilityRef(capability_id=connection_id, version=version),
            actor_id=user_id,
        )

    @staticmethod
    async def disconnect(*, user_id: str, connection_id: str, version: str) -> dict[str, Any]:
        # Retire catalog state before deleting secrets so execution fails closed.
        record = await CapabilityCatalog.get_owned(
            CapabilityKind.MCP_SERVER, connection_id, version, user_id
        )
        spec = McpServerDefinitionSpec.model_validate(record["spec"])
        retired = await CapabilityCatalog.retire_owned_mcp_connection(
            connection_id, version, user_id
        )
        secret_ref = spec.authentication.secret_ref or ""
        if secret_ref.startswith("mongodb-user://"):
            from services.keyvault_service import delete_credential

            try:
                await delete_credential(user_id, secret_ref.removeprefix("mongodb-user://"))
            except ValueError:
                pass
        return retired
