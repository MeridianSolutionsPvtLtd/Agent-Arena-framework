"""Simple owner-scoped MCP APIs for template browsing and connection setup."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import Field, SecretStr

from core.tooling.capability_catalog import (
    CapabilityCatalog,
    CapabilityCatalogUnavailable,
    CapabilityConflict,
    CapabilityNotFound,
)
from core.tooling.mcp_connections import McpConnectionService
from core.tooling.mcp_health import McpServerValidationFailed
from core.tooling.mcp_oauth import McpOAuthError, McpOAuthService
from middleware.auth import get_current_user
from models.capability import (
    AuthenticationMode, CapabilityKind, StrictModel, VersionedCapabilityRef,
)


router = APIRouter(prefix="/api/mcp", tags=["MCP Connections"])


class McpConnectRequest(StrictModel):
    name: str = Field(min_length=1, max_length=160)
    template_ref: Optional[VersionedCapabilityRef] = None
    endpoint: Optional[str] = Field(default=None, max_length=2048)
    authentication_mode: Optional[AuthenticationMode] = None
    credential: Optional[SecretStr] = None


class McpToolSelectionRequest(StrictModel):
    selected_tool_names: list[str] = Field(min_length=1, max_length=200)


class McpOAuthStartRequest(StrictModel):
    name: str = Field(min_length=1, max_length=160)
    endpoint: Optional[str] = Field(default=None, min_length=1, max_length=2048)
    template_ref: Optional[VersionedCapabilityRef] = None
    client_id: Optional[str] = Field(default=None, min_length=1, max_length=2048)
    client_secret: Optional[SecretStr] = None
    token_endpoint_auth_method: Optional[str] = Field(
        default=None, pattern=r"^(none|client_secret_post|client_secret_basic)$"
    )
    scopes: list[str] = Field(default_factory=list, max_length=100)


class McpAuthenticationInspectRequest(StrictModel):
    endpoint: str = Field(min_length=1, max_length=2048)


class McpReconnectRequest(StrictModel):
    credential: SecretStr


def _safe_connection(record: dict) -> dict:
    """Project user-visible connection state without secret references."""

    spec = dict(record.get("spec") or {})
    authentication = dict(spec.get("authentication") or {})
    authentication.pop("secret_ref", None)
    spec["authentication"] = authentication
    spec.pop("endpoint_fingerprint", None)
    return {
        "connection_id": record.get("capability_id"),
        "version": record.get("version"),
        "name": record.get("name"),
        "description": record.get("description"),
        "status": record.get("status"),
        "health": record.get("runtime_health"),
        "spec": spec,
    }


def _translate(exc: Exception) -> HTTPException:
    if isinstance(exc, CapabilityNotFound):
        return HTTPException(status_code=404, detail="MCP connection was not found")
    if isinstance(exc, CapabilityConflict):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, CapabilityCatalogUnavailable):
        return HTTPException(status_code=503, detail="MCP connection store is unavailable")
    if isinstance(exc, McpServerValidationFailed):
        return HTTPException(
            status_code=exc.status_code,
            detail={"code": exc.code, "message": str(exc)},
        )
    if isinstance(exc, McpOAuthError):
        return HTTPException(
            status_code=409,
            detail={"code": exc.code, "message": str(exc)},
        )
    return HTTPException(status_code=422, detail=str(exc))


# Designed and implemented by Rajadurai R.
@router.get("/templates")
async def list_mcp_templates(
    limit: int = Query(default=100, ge=1, le=200),
    _user: dict = Depends(get_current_user),
):
    try:
        return {"items": await CapabilityCatalog.list_mcp_templates(limit=limit)}
    except CapabilityCatalogUnavailable as exc:
        raise _translate(exc) from exc


@router.get("/connections")
async def list_mcp_connections(
    limit: int = Query(default=100, ge=1, le=200),
    user: dict = Depends(get_current_user),
):
    try:
        items = await CapabilityCatalog.list_owned_mcp_connections(
            str(user["_id"]), limit=limit
        )
        return {"items": [_safe_connection(item) for item in items]}
    except CapabilityCatalogUnavailable as exc:
        raise _translate(exc) from exc


@router.get("/connections/{connection_id}/{version}")
async def get_mcp_connection(
    connection_id: str, version: str, user: dict = Depends(get_current_user)
):
    try:
        record = await CapabilityCatalog.get_owned(
            CapabilityKind.MCP_SERVER,
            connection_id, version, str(user["_id"]),
        )
        return _safe_connection(record)
    except (CapabilityNotFound, CapabilityCatalogUnavailable) as exc:
        raise _translate(exc) from exc


@router.post("/connections", status_code=status.HTTP_201_CREATED)
async def connect_mcp(
    body: McpConnectRequest,
    user: dict = Depends(get_current_user),
):
    # Designed and implemented by Rajadurai R.
    # No-auth/API-key/bearer connections enter through this owner-scoped endpoint.
    try:
        result = await McpConnectionService.connect(
            user_id=str(user["_id"]),
            name=body.name,
            template_ref=body.template_ref,
            endpoint=body.endpoint,
            authentication_mode=body.authentication_mode,
            credential=body.credential.get_secret_value() if body.credential else None,
        )
        result["connection"] = _safe_connection(result["connection"])
        return result
    except (
        CapabilityNotFound, CapabilityConflict, CapabilityCatalogUnavailable,
        McpServerValidationFailed, ValueError,
    ) as exc:
        raise _translate(exc) from exc


# Designed and implemented by Rajadurai R.
@router.post("/inspect")
async def inspect_mcp_authentication(
    body: McpAuthenticationInspectRequest,
    _user: dict = Depends(get_current_user),
):
    try:
        return await McpOAuthService.inspect_authentication(body.endpoint)
    except (McpOAuthError, ValueError) as exc:
        raise _translate(exc) from exc


# Designed and implemented by Rajadurai R.
@router.get("/oauth/client-metadata", name="mcp_oauth_client_metadata")
async def mcp_oauth_client_metadata(request: Request):
    """Public CIMD identity used by compatible OAuth authorization servers."""

    client_id = str(request.url_for("mcp_oauth_client_metadata"))
    callback_url = str(request.url_for("complete_mcp_oauth"))
    return {
        "client_id": client_id,
        "client_name": "Meridian AI Arena",
        "client_uri": str(request.base_url).rstrip("/"),
        "redirect_uris": [callback_url],
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "none",
    }


# Designed and implemented by Rajadurai R.
@router.post("/oauth/start")
async def start_mcp_oauth(
    body: McpOAuthStartRequest,
    request: Request,
    user: dict = Depends(get_current_user),
):
    try:
        return await McpOAuthService.start(
            user_id=str(user["_id"]),
            name=body.name,
            endpoint=body.endpoint,
            template_ref=body.template_ref,
            callback_url=str(request.url_for("complete_mcp_oauth")),
            client_metadata_url=str(request.url_for("mcp_oauth_client_metadata")),
            supplied_client_id=body.client_id,
            supplied_client_secret=(
                body.client_secret.get_secret_value() if body.client_secret else None
            ),
            supplied_token_auth_method=body.token_endpoint_auth_method,
            requested_scopes=body.scopes,
        )
    except (McpOAuthError, ValueError) as exc:
        raise _translate(exc) from exc


@router.get("/oauth/callback", name="complete_mcp_oauth")
async def complete_mcp_oauth(
    state: str,
    code: Optional[str] = None,
    iss: Optional[str] = None,
    error: Optional[str] = None,
):
    """Complete a one-time provider redirect; state carries encrypted ownership."""
    # Designed and implemented by Rajadurai R.

    try:
        if error:
            await McpOAuthService.discard_state(state)
            raise HTTPException(
                status_code=400,
                detail={"code": "oauth_authorization_denied", "message": "OAuth authorization was not completed"},
            )
        if not code:
            raise McpOAuthError("OAuth callback parameters are invalid")
        result = await McpOAuthService.callback(state=state, code=code, issuer=iss)
        result["connection"] = _safe_connection(result["connection"])
        return result
    except HTTPException:
        raise
    except (
        McpOAuthError, CapabilityNotFound, CapabilityConflict,
        CapabilityCatalogUnavailable, McpServerValidationFailed, ValueError,
    ) as exc:
        raise _translate(exc) from exc


@router.post("/connections/{connection_id}/{version}/tools")
async def select_mcp_tools(
    connection_id: str,
    version: str,
    body: McpToolSelectionRequest,
    user: dict = Depends(get_current_user),
):
    # Designed and implemented by Rajadurai R.
    # User review promotes remote operations into the owned catalog. Agent
    # Builder assigns the resulting tools later while generating a blueprint.
    try:
        return await McpConnectionService.select_tools(
            user_id=str(user["_id"]),
            connection_id=connection_id,
            version=version,
            selected_tool_names=body.selected_tool_names,
        )
    except (
        CapabilityNotFound, CapabilityConflict, CapabilityCatalogUnavailable,
        McpServerValidationFailed, ValueError,
    ) as exc:
        raise _translate(exc) from exc


@router.post("/connections/{connection_id}/{version}/validate")
async def validate_mcp_connection(
    connection_id: str, version: str, user: dict = Depends(get_current_user)
):
    # Designed and implemented by Rajadurai R.
    # Manual validation refreshes health and detects remote schema drift.
    from core.tooling.external_mcp import resolve_config_endpoint
    from core.tooling.mcp_health import McpServerValidationService
    try:
        await CapabilityCatalog.get_owned(
            CapabilityKind.MCP_SERVER, connection_id, version, str(user["_id"])
        )
        return await McpServerValidationService(resolve_config_endpoint).validate(
            VersionedCapabilityRef(capability_id=connection_id, version=version),
            actor_id=str(user["_id"]),
        )
    except (
        CapabilityNotFound, CapabilityConflict, CapabilityCatalogUnavailable,
        McpServerValidationFailed, ValueError,
    ) as exc:
        raise _translate(exc) from exc


@router.post("/connections/{connection_id}/{version}/reconnect")
async def reconnect_mcp_connection(
    connection_id: str, version: str, body: McpReconnectRequest,
    user: dict = Depends(get_current_user),
):
    # Designed and implemented by Rajadurai R.
    # Credential replacement is validated before it is considered usable.
    try:
        return await McpConnectionService.reconnect(
            user_id=str(user["_id"]), connection_id=connection_id, version=version,
            credential=body.credential.get_secret_value(),
        )
    except (
        CapabilityNotFound, CapabilityConflict, CapabilityCatalogUnavailable,
        McpServerValidationFailed, ValueError,
    ) as exc:
        raise _translate(exc) from exc


@router.delete("/connections/{connection_id}/{version}")
async def disconnect_mcp_connection(
    connection_id: str, version: str, user: dict = Depends(get_current_user)
):
    # Designed and implemented by Rajadurai R.
    # Disconnect refuses while generated tools are still assigned to an agent.
    try:
        result = await McpConnectionService.disconnect(
            user_id=str(user["_id"]), connection_id=connection_id, version=version
        )
        return {"connection_id": connection_id, "status": result["status"]}
    except (
        CapabilityNotFound, CapabilityConflict, CapabilityCatalogUnavailable, ValueError,
    ) as exc:
        raise _translate(exc) from exc
