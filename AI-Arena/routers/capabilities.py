"""Governed Capability Catalog endpoints for Admin and Agent Builder UIs."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from core.tooling.capability_catalog import (
    CapabilityCatalog,
    CapabilityCatalogUnavailable,
    CapabilityConflict,
    CapabilityNotFound,
    InvalidLifecycleTransition,
)
from middleware.auth import get_capability_admin, get_current_user
from models.capability import (
    AuthenticationSpec, CapabilityKind, CapabilityOwner, CapabilityRecord, CapabilityStatus,
    DatasetDefinitionSpec, EngineDefinitionSpec, ExecutionTargetKind,
    ExecutionTarget, McpServerDefinitionSpec, McpServerKind, McpToolCandidateSpec,
    McpTransport, RiskLevel, StrictModel, ToolDefinitionSpec, VersionedCapabilityRef,
)
from pydantic import Field, model_validator
from config import settings


router = APIRouter(prefix="/api/capabilities", tags=["Capabilities"])


class CapabilityLifecycleRequest(StrictModel):
    from_status: CapabilityStatus
    to_status: CapabilityStatus
    reason: Optional[str] = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def activation_requires_runtime(self) -> "CapabilityLifecycleRequest":
        if self.to_status == CapabilityStatus.ACTIVE and not settings.ENABLE_GOVERNED_TOOL_RUNTIME:
            raise ValueError(
                "capability activation is disabled until the Execution Broker and MCP runtime are enabled"
            )
        return self


class McpServerRegistrationRequest(StrictModel):
    capability_id: str = Field(min_length=1, max_length=160)
    version: str = Field(min_length=5, max_length=80)
    name: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=4000)
    owner_team: str = Field(min_length=1, max_length=120)
    endpoint_ref: str = Field(min_length=1, max_length=2048)
    authentication: AuthenticationSpec
    allowed_tool_names: list[str] = Field(default_factory=list, max_length=500)


class McpToolPromotionRequest(StrictModel):
    """Human-reviewed business metadata used to promote a discovered schema."""

    tool_id: str = Field(min_length=1, max_length=160)
    version: str = Field(default="1.0.0", min_length=5, max_length=80)
    name: Optional[str] = Field(default=None, min_length=1, max_length=160)
    description: Optional[str] = Field(default=None, max_length=4000)
    category: Optional[str] = Field(default=None, min_length=1, max_length=100)
    risk_level: Optional[RiskLevel] = None
    policy_refs: list[VersionedCapabilityRef] = Field(default_factory=list, max_length=20)
    supports_files: bool = False
    idempotent: bool = False
    timeout_seconds: int = Field(default=60, ge=1, le=3600)
    max_attempts: int = Field(default=1, ge=1, le=5)


def _actor_id(user: dict) -> str:
    actor = str(user.get("_id") or "").strip()
    if not actor:
        raise HTTPException(status_code=401, detail="Authenticated user ID is missing")
    return actor


def _translate_catalog_error(exc: Exception) -> HTTPException:
    if isinstance(exc, CapabilityNotFound):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, (CapabilityConflict, InvalidLifecycleTransition)):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, CapabilityCatalogUnavailable):
        return HTTPException(status_code=503, detail="Capability Catalog is unavailable")
    return HTTPException(status_code=500, detail="Capability Catalog operation failed")


def _resolve_config_endpoint(endpoint_ref: str) -> str:
    from core.tooling.external_mcp import resolve_config_endpoint
    return resolve_config_endpoint(endpoint_ref)


async def _validate_activation_readiness(
    kind: CapabilityKind, capability_id: str, version: str
) -> None:
    if kind == CapabilityKind.MCP_TOOL_CANDIDATE:
        raise CapabilityConflict(
            "MCP tool candidates cannot be activated; promote the candidate to a tool"
        )
    record = await CapabilityCatalog.get(kind, capability_id, version)
    dependencies: list[tuple[CapabilityKind, VersionedCapabilityRef]] = []
    if kind == CapabilityKind.TOOL:
        spec = ToolDefinitionSpec.model_validate(record["spec"])
        target_kind = {
            ExecutionTargetKind.NATIVE_MCP: CapabilityKind.MCP_SERVER,
            ExecutionTargetKind.EXTERNAL_MCP: CapabilityKind.MCP_SERVER,
            ExecutionTargetKind.CONNECTOR: CapabilityKind.CONNECTOR,
            ExecutionTargetKind.ENGINE: CapabilityKind.ENGINE,
        }[spec.execution_target.kind]
        dependencies.append((target_kind, spec.execution_target.target_ref))
        dependencies.extend((CapabilityKind.POLICY, ref) for ref in spec.policy_refs)
    elif kind == CapabilityKind.DATASET:
        spec = DatasetDefinitionSpec.model_validate(record["spec"])
        dependencies.append((CapabilityKind.ENGINE, spec.engine_ref))
        dependencies.extend((CapabilityKind.POLICY, ref) for ref in spec.policy_refs)
    elif kind == CapabilityKind.ENGINE:
        spec = EngineDefinitionSpec.model_validate(record["spec"])
        dependencies.extend((CapabilityKind.POLICY, ref) for ref in spec.policy_refs)
    elif kind == CapabilityKind.MCP_SERVER:
        spec = McpServerDefinitionSpec.model_validate(record["spec"])
        if spec.purpose.value == "template":
            raise CapabilityConflict("MCP templates cannot be activated for execution")
        if spec.server_kind == McpServerKind.INTERNAL and not settings.ENABLE_NATIVE_MCP_SERVER:
            raise CapabilityConflict("Internal MCP tools are not enabled")
        if spec.server_kind == McpServerKind.EXTERNAL:
            from core.tooling.external_mcp import resolve_config_endpoint
            from models.capability import AuthenticationMode

            try:
                resolve_config_endpoint(spec.endpoint_ref or "")
            except ValueError as exc:
                raise CapabilityConflict(str(exc)) from exc
            from core.tooling.mcp_health import require_recent_healthy_validation

            require_recent_healthy_validation(record)
            if not spec.allowed_tool_names:
                raise CapabilityConflict(
                    "External MCP server requires at least one approved tool name"
                )
            if spec.authentication.mode not in {
                AuthenticationMode.NONE,
                AuthenticationMode.API_KEY,
                AuthenticationMode.BEARER_TOKEN,
                AuthenticationMode.OAUTH2,
                AuthenticationMode.JWT,
            }:
                raise CapabilityConflict(
                    "External MCP authentication mode is not supported by direct transport"
                )

    for dependency_kind, reference in dependencies:
        dependency = await CapabilityCatalog.get(
            dependency_kind,
            reference.capability_id,
            reference.version,
            allowed_statuses={CapabilityStatus.ACTIVE},
        )
        if dependency_kind == CapabilityKind.MCP_SERVER:
            dependency_spec = McpServerDefinitionSpec.model_validate(dependency["spec"])
            if dependency_spec.purpose.value == "template":
                raise CapabilityConflict("Tools cannot target an MCP template")


@router.get("/builder/tools")
async def list_builder_tools(
    limit: int = Query(default=200, ge=1, le=200),
    current_user: dict = Depends(get_current_user),
):
    """Return active, projected tool metadata safe for automatic selection."""

    try:
        return {
            "items": await CapabilityCatalog.get_active_tools_for_builder(
                owner_user_id=_actor_id(current_user), limit=limit
            )
        }
    except CapabilityCatalogUnavailable as exc:
        raise _translate_catalog_error(exc) from exc


@router.post("/mcp-servers/register", status_code=status.HTTP_201_CREATED)
async def register_external_mcp_server(
    body: McpServerRegistrationRequest,
    admin: dict = Depends(get_capability_admin),
):
    """Register a local-registry MCP server draft without accepting secrets."""

    try:
        if (
            settings.CAPABILITY_MANAGEMENT_ACCESS == "authenticated"
            and body.authentication.secret_ref
            and not body.authentication.secret_ref.startswith("mongodb-user://")
        ):
            raise ValueError("User MCP credentials must use encrypted user storage")
        # Designed and implemented by Rajadurai R.
        endpoint = _resolve_config_endpoint(body.endpoint_ref)
        from core.tooling.external_mcp import canonical_endpoint

        normalized_endpoint, endpoint_fingerprint = canonical_endpoint(endpoint)
        actor = _actor_id(admin)
        await CapabilityCatalog.assert_external_endpoint_available(
            endpoint_fingerprint,
            capability_id=body.capability_id,
            owner_user_id=actor,
        )
        record = CapabilityRecord(
            kind=CapabilityKind.MCP_SERVER,
            capability_id=body.capability_id,
            version=body.version,
            status=CapabilityStatus.DRAFT,
            name=body.name,
            description=body.description,
            owner=CapabilityOwner(team=body.owner_team, contact=actor),
            tags=["external", "mcp", "manual_registry"],
            spec=McpServerDefinitionSpec(
                server_kind=McpServerKind.EXTERNAL,
                transport=McpTransport.STREAMABLE_HTTP,
                endpoint_ref=normalized_endpoint,
                authentication=body.authentication,
                allowed_tool_names=body.allowed_tool_names,
                endpoint_fingerprint=endpoint_fingerprint,
            ).model_dump(mode="json"),
        )
        return await CapabilityCatalog.create(record, actor_id=_actor_id(admin))
    except (CapabilityConflict, InvalidLifecycleTransition, CapabilityCatalogUnavailable) as exc:
        raise _translate_catalog_error(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


# Designed and implemented by Rajadurai R.
@router.post("/mcp-servers/{capability_id}/{version}/validate")
async def validate_external_mcp_server(
    capability_id: str,
    version: str,
    user: dict = Depends(get_capability_admin),
):
    """Validate connectivity, credentials, protocol and tool schemas safely."""

    from core.tooling.mcp_health import (
        McpServerValidationFailed,
        McpServerValidationService,
    )

    try:
        await CapabilityCatalog.get_owned(
            CapabilityKind.MCP_SERVER, capability_id, version, _actor_id(user)
        )
        return await McpServerValidationService(_resolve_config_endpoint).validate(
            VersionedCapabilityRef(capability_id=capability_id, version=version),
            actor_id=_actor_id(user),
        )
    except McpServerValidationFailed as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"code": exc.code, "message": str(exc)},
        ) from exc
    except (CapabilityNotFound, CapabilityConflict, CapabilityCatalogUnavailable) as exc:
        raise _translate_catalog_error(exc) from exc


@router.get("")
async def list_capabilities(
    kind: Optional[CapabilityKind] = None,
    capability_status: Optional[CapabilityStatus] = Query(default=None, alias="status"),
    owner_team: Optional[str] = Query(default=None, min_length=1, max_length=120),
    after_id: Optional[str] = Query(default=None, max_length=300),
    limit: int = Query(default=50, ge=1, le=200),
    _admin: dict = Depends(get_capability_admin),
):
    """List catalog records for the governed Admin UI."""

    try:
        items = await CapabilityCatalog.list_capabilities(
            kind=kind,
            status=capability_status,
            owner_team=owner_team,
            owner_user_id=_actor_id(_admin),
            after_id=after_id,
            limit=limit,
        )
        return {
            "items": items,
            "next_after_id": items[-1].get("catalog_id") if len(items) == limit else None,
        }
    except CapabilityCatalogUnavailable as exc:
        raise _translate_catalog_error(exc) from exc


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_capability_draft(
    body: CapabilityRecord,
    admin: dict = Depends(get_capability_admin),
):
    """Create one immutable, human-managed capability draft."""

    try:
        actor = _actor_id(admin)
        owned = body.model_copy(
            update={"owner": body.owner.model_copy(update={"contact": actor})}
        )
        return await CapabilityCatalog.create(owned, actor_id=actor)
    except (CapabilityConflict, InvalidLifecycleTransition, CapabilityCatalogUnavailable) as exc:
        raise _translate_catalog_error(exc) from exc


@router.get("/{kind}/{capability_id}/{version}")
async def get_capability(
    kind: CapabilityKind,
    capability_id: str,
    version: str,
    _admin: dict = Depends(get_capability_admin),
):
    """Return one exact immutable capability version."""

    try:
        return await CapabilityCatalog.get_visible(
            kind, capability_id, version, _actor_id(_admin)
        )
    except (CapabilityNotFound, CapabilityCatalogUnavailable) as exc:
        raise _translate_catalog_error(exc) from exc


@router.post("/{kind}/{capability_id}/{version}/lifecycle")
async def transition_capability_lifecycle(
    kind: CapabilityKind,
    capability_id: str,
    version: str,
    body: CapabilityLifecycleRequest,
    admin: dict = Depends(get_capability_admin),
):
    """Apply an atomic, audited lifecycle transition; activation is gated."""

    try:
        await CapabilityCatalog.get_owned(
            kind, capability_id, version, _actor_id(admin)
        )
        if body.to_status == CapabilityStatus.ACTIVE:
            await _validate_activation_readiness(kind, capability_id, version)
        return await CapabilityCatalog.transition_status(
            kind,
            capability_id,
            version,
            from_status=body.from_status,
            to_status=body.to_status,
            actor_id=_actor_id(admin),
            reason=body.reason,
        )
    except (
        CapabilityNotFound,
        CapabilityConflict,
        InvalidLifecycleTransition,
        CapabilityCatalogUnavailable,
    ) as exc:
        raise _translate_catalog_error(exc) from exc
@router.post("/mcp_server/{capability_id}/{version}/discover")
async def discover_external_mcp_tools(
    capability_id: str,
    version: str,
    admin: dict = Depends(get_capability_admin),
):
    """Stage external MCP schemas as draft candidates; never auto-activate."""
    from core.tooling.external_mcp import ExternalMcpDiscoveryService

    try:
        await CapabilityCatalog.get_owned(
            CapabilityKind.MCP_SERVER, capability_id, version, _actor_id(admin)
        )
        service = ExternalMcpDiscoveryService(_resolve_config_endpoint)
        items = await service.discover(
            VersionedCapabilityRef(capability_id=capability_id, version=version),
            actor_id=_actor_id(admin),
        )
        return {"items": items}
    except (CapabilityNotFound, CapabilityConflict, CapabilityCatalogUnavailable) as exc:
        raise _translate_catalog_error(exc) from exc
    except TimeoutError as exc:
        raise HTTPException(status_code=504, detail="MCP tool discovery timed out") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post(
    "/mcp-tool-candidates/{capability_id}/{candidate_version}/promote",
    status_code=status.HTTP_201_CREATED,
)
async def promote_mcp_tool_candidate(
    capability_id: str,
    candidate_version: str,
    body: McpToolPromotionRequest,
    user: dict = Depends(get_capability_admin),
):
    """Promote one reviewed MCP schema into a governed tool draft.

    Discovered schemas remain immutable evidence.  Promotion creates a separate
    TOOL record, and normal review/approval/activation gates still apply.
    """

    try:
        candidate = await CapabilityCatalog.get_owned(
            CapabilityKind.MCP_TOOL_CANDIDATE,
            capability_id,
            candidate_version,
            _actor_id(user),
        )
        if candidate.get("status") not in {
            CapabilityStatus.DRAFT.value, CapabilityStatus.REVIEW.value
        }:
            raise CapabilityConflict("MCP tool candidate is not promotable")
        candidate_spec = McpToolCandidateSpec.model_validate(candidate["spec"])
        server = await CapabilityCatalog.get_owned(
            CapabilityKind.MCP_SERVER,
            candidate_spec.mcp_server_ref.capability_id,
            candidate_spec.mcp_server_ref.version,
            _actor_id(user),
        )
        if server.get("status") not in {
            CapabilityStatus.APPROVED.value, CapabilityStatus.ACTIVE.value
        }:
            raise CapabilityConflict("MCP server is not approved")
        server_spec = McpServerDefinitionSpec.model_validate(server["spec"])
        if candidate_spec.remote_tool_name not in server_spec.allowed_tool_names:
            raise CapabilityConflict(
                "The MCP tool is not in the server's approved tool allow-list"
            )

        tool = CapabilityRecord(
            kind=CapabilityKind.TOOL,
            capability_id=body.tool_id,
            version=body.version,
            status=CapabilityStatus.DRAFT,
            name=body.name or candidate["name"],
            description=(
                body.description
                if body.description is not None
                else candidate.get("description", "")
            ),
            owner=CapabilityOwner.model_validate(candidate["owner"]),
            tags=["external", "mcp", "promoted"],
            source=candidate.get("source"),
            spec=ToolDefinitionSpec(
                category=body.category or "external_mcp",
                risk_level=body.risk_level or candidate_spec.suggested_risk_level,
                input_schema=candidate_spec.input_schema,
                output_schema=candidate_spec.output_schema,
                execution_target=ExecutionTarget(
                    kind=ExecutionTargetKind.EXTERNAL_MCP,
                    target_ref=candidate_spec.mcp_server_ref,
                    operation=candidate_spec.remote_tool_name,
                ),
                policy_refs=body.policy_refs,
                supports_files=body.supports_files,
                idempotent=body.idempotent,
                timeout_seconds=body.timeout_seconds,
                max_attempts=body.max_attempts,
                requires_approval=candidate_spec.builder_metadata.requires_approval,
                builder_metadata=candidate_spec.builder_metadata,
            ).model_dump(mode="json"),
        )
        return await CapabilityCatalog.create(tool, actor_id=_actor_id(user))
    except (
        CapabilityNotFound,
        CapabilityConflict,
        InvalidLifecycleTransition,
        CapabilityCatalogUnavailable,
    ) as exc:
        raise _translate_catalog_error(exc) from exc
