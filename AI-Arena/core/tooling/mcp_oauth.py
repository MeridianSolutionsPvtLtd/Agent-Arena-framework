"""Dynamic OAuth 2.1 discovery for user-owned remote MCP connections."""

from __future__ import annotations

import base64
import hashlib
import json
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode, urlsplit

import httpx2
from pymongo import ASCENDING
from pymongo.errors import PyMongoError

from core.security.payload_crypto import decrypt_payload, encrypt_payload
from core.tooling.capability_catalog import CapabilityCatalog
from core.tooling.external_mcp import canonical_endpoint, validate_resolved_endpoint
from database import get_db
from models.capability import (
    AuthenticationMode, CapabilityKind, CapabilityStatus, McpServerDefinitionSpec,
    McpServerPurpose, VersionedCapabilityRef,
)


class McpOAuthError(RuntimeError):
    """Safe domain error translated by the router into an actionable API response."""

    def __init__(self, message: str, *, code: str = "mcp_oauth_error"):
        super().__init__(message)
        self.code = code


def _utcnow() -> datetime:
    """Return timezone-aware UTC so MongoDB TTL and expiry comparisons are stable."""

    return datetime.now(timezone.utc)


def _state_hash(value: str) -> str:
    """Hash browser-visible OAuth state before using it as a database identifier."""

    return hashlib.sha256(value.encode("ascii")).hexdigest()


def _b64url(value: bytes) -> str:
    """Encode PKCE digest bytes using unpadded URL-safe Base64."""

    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _well_known(url: str, suffix: str, *, include_path: bool = True) -> str:
    """Build RFC well-known discovery URLs for both path-aware and origin fallbacks."""

    parsed = urlsplit(url)
    path = parsed.path.rstrip("/") if include_path else ""
    return f"{parsed.scheme}://{parsed.netloc}/.well-known/{suffix}{path}"


def _oidc_well_known(issuer: str) -> str:
    """Build the OpenID Connect discovery fallback for an OAuth issuer."""

    return f"{issuer.rstrip('/')}/.well-known/openid-configuration"


def _collection():
    """Return the short-lived OAuth transaction collection or fail closed."""

    db = get_db()
    if db is None:
        raise McpOAuthError("OAuth connection store is unavailable")
    return db["mcp_oauth_states"]


def _challenge_value(challenge: str, name: str) -> str | None:
    """Extract a quoted parameter such as resource_metadata from a Bearer challenge."""

    match = re.search(rf'{re.escape(name)}="([^"]+)"', challenge, re.IGNORECASE)
    return match.group(1) if match else None


async def _get_json(client: Any, urls: list[str], error: str) -> dict[str, Any]:
    """Load the first valid public-HTTPS JSON metadata document.

    Every candidate is DNS/IP validated before the request. Invalid JSON and
    non-object documents are ignored so standards-compatible fallback URLs can
    be attempted, while a generic error prevents leaking provider internals.
    """

    for url in dict.fromkeys(urls):
        if urlsplit(url).scheme != "https":
            continue
        await validate_resolved_endpoint(url)
        try:
            response = await client.get(url)
            if response.status_code < 400:
                value = response.json()
                if isinstance(value, dict):
                    return value
        except (ValueError, TypeError):
            continue
    raise McpOAuthError(error)


# Designed and implemented by Rajadurai R.
class McpOAuthService:
    """Run user-owned OAuth 2.1 authorization for remote MCP connections.

    The service dynamically discovers provider metadata, chooses CIMD, DCR, or
    manual client registration, creates a PKCE-protected browser transaction,
    consumes the callback once, and hands the resulting token bundle to the
    owner-scoped MCP connection service for encrypted persistence.
    """

    @staticmethod
    async def ensure_indexes() -> None:
        """Create automatic expiry for abandoned OAuth browser transactions.

        MongoDB removes a state document when ``expires_at`` is reached. The
        callback also checks the timestamp, so authorization fails closed even
        if TTL cleanup has not run yet.
        """

        from core.startup.indexes import ensure_index

        await ensure_index(
            _collection(),
            [("expires_at", ASCENDING)],
            expireAfterSeconds=0,
            name="ttl_mcp_oauth_state",
        )

    @staticmethod
    async def discard_state(state: str) -> None:
        """Consume a denied OAuth attempt so its state cannot be replayed.

        The provider redirects with ``error`` instead of ``code`` when the user
        cancels. Atomic deletion makes that state unusable for later callbacks.
        """

        if not state or len(state) > 512:
            raise McpOAuthError("OAuth callback parameters are invalid")
        try:
            document = await _collection().find_one_and_delete({
                "_id": _state_hash(state), "expires_at": {"$gt": _utcnow()}
            })
        except PyMongoError as exc:
            raise McpOAuthError("OAuth callback store is unavailable") from exc
        if not document:
            raise McpOAuthError("OAuth state is invalid, expired, or already used")

    @classmethod
    async def inspect_authentication(cls, endpoint: str) -> dict[str, Any]:
        """Classify the next UI action from an unauthenticated MCP challenge.

        This endpoint probe deliberately sends no credential. A successful MCP
        response means no authentication; a 401 challenge identifies OAuth,
        API-key, or bearer-token onboarding. OAuth metadata is inspected only
        to tell the UI whether registration can be automatic.
        """

        # Probe without credentials and translate the challenge into a UI action.
        normalized, _ = canonical_endpoint(endpoint)
        await validate_resolved_endpoint(normalized)
        async with httpx2.AsyncClient(timeout=15.0, follow_redirects=False) as client:
            response = await client.post(
                normalized,
                headers={"Accept": "application/json, text/event-stream"},
                json={
                    "jsonrpc": "2.0", "id": "auth-inspection", "method": "initialize",
                    "params": {
                        "protocolVersion": "2025-11-25", "capabilities": {},
                        "clientInfo": {"name": "Meridian AI Arena", "version": "2.0.0"},
                    },
                },
            )
        challenge = response.headers.get("WWW-Authenticate", "")
        challenge_lower = challenge.casefold()
        if response.status_code < 400:
            return {
                "endpoint": normalized, "authentication_mode": "none",
                "next_action": "connect", "automatic_oauth": False,
            }
        if response.status_code == 401 and (
            "resource_metadata=" in challenge_lower or "oauth-protected-resource" in challenge_lower
        ):
            metadata = await cls._metadata(normalized)
            automatic = bool(
                metadata.get("client_id_metadata_document_supported")
                or metadata.get("registration_endpoint")
            )
            return {
                "endpoint": normalized, "authentication_mode": "oauth2",
                "next_action": "start_oauth" if automatic else "provide_oauth_client",
                "automatic_oauth": automatic,
                "registration_methods": [
                    method for method, enabled in (
                        ("client_metadata_document", metadata.get("client_id_metadata_document_supported")),
                        ("dynamic", metadata.get("registration_endpoint")),
                        ("user_provided", True),
                    ) if enabled
                ],
            }
        if response.status_code == 401 and ("api-key" in challenge_lower or "apikey" in challenge_lower):
            return {
                "endpoint": normalized, "authentication_mode": "api_key",
                "next_action": "enter_api_key", "automatic_oauth": False,
            }
        if response.status_code == 401 and "bearer" in challenge_lower:
            return {
                "endpoint": normalized, "authentication_mode": "bearer_token",
                "next_action": "enter_bearer_token", "automatic_oauth": False,
            }
        return {
            "endpoint": normalized, "authentication_mode": "unknown",
            "next_action": "choose_authentication", "automatic_oauth": False,
        }

    @staticmethod
    async def _metadata(endpoint: str) -> dict[str, Any]:
        """Discover and validate the MCP resource and OAuth authorization server.

        Discovery follows the MCP protected-resource document to an OAuth or
        OIDC authorization-server document. Issuer equality, public DNS/IP,
        and HTTPS are required for all authorization, token, and registration
        destinations to reduce mix-up, downgrade, and SSRF risks.
        """

        # Follow MCP protected-resource discovery, then OAuth/OIDC issuer discovery.
        normalized, _ = canonical_endpoint(endpoint)
        await validate_resolved_endpoint(normalized)
        async with httpx2.AsyncClient(timeout=15.0, follow_redirects=False) as client:
            probe = await client.post(
                normalized,
                headers={"Accept": "application/json, text/event-stream"},
                json={"jsonrpc": "2.0", "id": "oauth-discovery", "method": "tools/list"},
            )
            challenge = probe.headers.get("WWW-Authenticate", "")
            advertised = _challenge_value(challenge, "resource_metadata")
            resource_urls = ([advertised] if advertised else []) + [
                _well_known(normalized, "oauth-protected-resource"),
                _well_known(normalized, "oauth-protected-resource", include_path=False),
            ]
            resource = await _get_json(
                client, resource_urls, "MCP server does not publish OAuth resource metadata"
            )
            authorization_servers = resource.get("authorization_servers") or []
            if not authorization_servers:
                raise McpOAuthError("MCP OAuth authorization server is missing")
            issuer = str(authorization_servers[0]).rstrip("/")
            if urlsplit(issuer).scheme != "https":
                raise McpOAuthError("MCP OAuth issuer must use HTTPS")
            authorization = await _get_json(
                client,
                [
                    _well_known(issuer, "oauth-authorization-server"),
                    _oidc_well_known(issuer),
                    _well_known(issuer, "oauth-authorization-server", include_path=False),
                    _well_known(issuer, "openid-configuration", include_path=False),
                ],
                "MCP OAuth authorization metadata is unavailable",
            )

        metadata_issuer = str(authorization.get("issuer") or issuer).rstrip("/")
        if metadata_issuer != issuer:
            raise McpOAuthError("MCP OAuth authorization issuer does not match resource metadata")
        authorization_endpoint = str(authorization.get("authorization_endpoint") or "")
        token_endpoint = str(authorization.get("token_endpoint") or "")
        if not authorization_endpoint or not token_endpoint:
            raise McpOAuthError("MCP OAuth metadata is incomplete")
        for destination in (authorization_endpoint, token_endpoint):
            if urlsplit(destination).scheme != "https":
                raise McpOAuthError("MCP OAuth endpoints must use HTTPS")
            await validate_resolved_endpoint(destination)
        registration_endpoint = str(authorization.get("registration_endpoint") or "")
        if registration_endpoint:
            if urlsplit(registration_endpoint).scheme != "https":
                raise McpOAuthError("MCP OAuth registration endpoint must use HTTPS")
            await validate_resolved_endpoint(registration_endpoint)
        return {
            "resource": str(resource.get("resource") or normalized),
            "issuer": metadata_issuer,
            "authorization_endpoint": authorization_endpoint,
            "token_endpoint": token_endpoint,
            "registration_endpoint": registration_endpoint or None,
            "client_id_metadata_document_supported": bool(
                authorization.get("client_id_metadata_document_supported")
            ),
            "challenge_scope": _challenge_value(challenge, "scope"),
        }

    @staticmethod
    async def _register_client(
        metadata: dict[str, Any], *, callback_url: str, client_name: str
    ) -> dict[str, Any]:
        """Register this deployment through OAuth Dynamic Client Registration.

        DCR is the compatibility fallback when a provider cannot consume the
        platform's Client ID Metadata Document. The provider returns a new
        client ID and, optionally, a client secret for this deployment.
        """

        endpoint = metadata.get("registration_endpoint")
        if not endpoint:
            raise McpOAuthError("OAuth provider does not support automatic client registration")
        local = urlsplit(callback_url).hostname in {"localhost", "127.0.0.1"}
        request_body = {
            "client_name": client_name,
            "redirect_uris": [callback_url],
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "none",
            "application_type": "native" if local else "web",
        }
        async with httpx2.AsyncClient(timeout=20.0, follow_redirects=False) as client:
            response = await client.post(endpoint, json=request_body)
        if response.status_code >= 400:
            raise McpOAuthError("OAuth dynamic client registration failed")
        registered = response.json()
        client_id = str(registered.get("client_id") or "")
        if not client_id:
            raise McpOAuthError("OAuth registration did not return a client ID")
        auth_method = str(registered.get("token_endpoint_auth_method") or "none")
        if auth_method not in {"none", "client_secret_post", "client_secret_basic"}:
            raise McpOAuthError("OAuth registration returned an unsupported client authentication method")
        return {
            "client_id": client_id,
            "client_secret": str(registered.get("client_secret") or "") or None,
            "token_endpoint_auth_method": auth_method,
            "registration_method": "dynamic",
        }

    @classmethod
    async def start(
        cls, *, user_id: str, name: str, endpoint: str | None,
        template_ref: VersionedCapabilityRef | None, callback_url: str,
        client_metadata_url: str, supplied_client_id: str | None = None,
        supplied_client_secret: str | None = None,
        supplied_token_auth_method: str | None = None,
        requested_scopes: list[str] | None = None,
    ) -> dict[str, Any]:
        """Start a ten-minute, owner-bound OAuth authorization transaction.

        Registration is selected in this order:

        1. Manual/user-provided client: required by providers that expect an
           administrator to register an OAuth application in their console.
        2. CIMD: uses this application's public metadata URL as ``client_id``;
           no provider-specific secret or environment variable is required.
        3. DCR: asks the provider's registration endpoint for a client ID and
           optional secret when CIMD is unavailable.

        The method validates an optional curated template, discovers metadata,
        generates state and PKCE S256 values, encrypts ownership and verifier
        data in MongoDB, and returns only the provider authorization URL.
        """

        callback = urlsplit(callback_url)
        if callback.scheme not in {"https", "http"} or (
            callback.scheme == "http" and callback.hostname not in {"localhost", "127.0.0.1"}
        ):
            raise McpOAuthError("OAuth callback must use HTTPS outside local development")
        if template_ref:
            template = await CapabilityCatalog.get(
                CapabilityKind.MCP_SERVER, template_ref.capability_id, template_ref.version,
                allowed_statuses={CapabilityStatus.ACTIVE},
            )
            template_spec = McpServerDefinitionSpec.model_validate(template["spec"])
            if (
                not template.get("code_owned")
                or template_spec.purpose != McpServerPurpose.TEMPLATE
                or template_spec.authentication.mode != AuthenticationMode.OAUTH2
            ):
                raise McpOAuthError("Selected template is not an approved OAuth MCP template")
            if endpoint and template_spec.endpoint_ref:
                provided, _ = canonical_endpoint(endpoint)
                expected, _ = canonical_endpoint(template_spec.endpoint_ref)
                if provided != expected:
                    raise McpOAuthError("Official template endpoint cannot be overridden")
            endpoint = endpoint or template_spec.endpoint_ref
        if not endpoint:
            raise McpOAuthError("MCP OAuth endpoint is required")

        metadata = await cls._metadata(endpoint)
        if supplied_client_secret and not supplied_client_id:
            raise McpOAuthError("OAuth client secret requires a client ID")
        if supplied_token_auth_method not in {None, "none", "client_secret_post", "client_secret_basic"}:
            raise McpOAuthError("OAuth client authentication method is unsupported")
        if supplied_token_auth_method in {"client_secret_post", "client_secret_basic"} and not supplied_client_secret:
            raise McpOAuthError("Selected OAuth client authentication method requires a client secret")
        # Manual registration wins because it is an explicit user/admin choice
        # and may be mandatory for providers with a pre-registered OAuth app.
        if supplied_client_id:
            registration = {
                "client_id": supplied_client_id,
                "client_secret": supplied_client_secret,
                "token_endpoint_auth_method": supplied_token_auth_method or (
                    "client_secret_post" if supplied_client_secret else "none"
                ),
                "registration_method": "user_provided",
            }
        # CIMD is the preferred zero-configuration production path: the HTTPS
        # metadata URL is itself the client_id and publishes the redirect URI.
        elif metadata["client_id_metadata_document_supported"] and urlsplit(client_metadata_url).scheme == "https":
            registration = {
                "client_id": client_metadata_url, "client_secret": None,
                "token_endpoint_auth_method": "none",
                "registration_method": "client_metadata_document",
            }
        # DCR creates a provider-side client dynamically when CIMD is unsupported.
        elif metadata.get("registration_endpoint"):
            registration = await cls._register_client(
                metadata, callback_url=callback_url, client_name="Meridian AI Arena"
            )
        else:
            raise McpOAuthError(
                "OAuth provider cannot register this client automatically; provide an OAuth client ID through the connection UI",
                code="oauth_client_registration_required",
            )

        scopes = list(dict.fromkeys(item.strip() for item in (requested_scopes or []) if item.strip()))
        if any(len(item) > 200 for item in scopes):
            raise McpOAuthError("OAuth scope must not exceed 200 characters")
        if not scopes and metadata.get("challenge_scope"):
            scopes = str(metadata["challenge_scope"]).split()
        state = secrets.token_urlsafe(32)
        verifier = secrets.token_urlsafe(64)
        expires_at = _utcnow() + timedelta(minutes=10)
        payload = {
            "user_id": user_id, "name": name, "endpoint": endpoint,
            "template_ref": template_ref.model_dump(mode="json") if template_ref else None,
            "verifier": verifier, "callback_url": callback_url, "scopes": scopes,
            **registration, **metadata,
        }
        # State, PKCE verifier, and any client secret are encrypted together and expire.
        try:
            await _collection().insert_one({
                "_id": _state_hash(state), "payload_ciphertext": encrypt_payload(payload),
                "expires_at": expires_at, "created_at": _utcnow(),
            })
        except PyMongoError as exc:
            raise McpOAuthError("OAuth connection could not be started") from exc

        query = {
            "response_type": "code", "client_id": registration["client_id"],
            "redirect_uri": callback_url, "state": state,
            "code_challenge": _b64url(hashlib.sha256(verifier.encode("ascii")).digest()),
            "code_challenge_method": "S256", "resource": metadata["resource"],
        }
        if scopes:
            query["scope"] = " ".join(scopes)
        return {
            "authorization_url": f"{metadata['authorization_endpoint']}?{urlencode(query)}",
            "expires_at": expires_at.isoformat(),
            "registration_method": registration["registration_method"],
        }

    @classmethod
    async def callback(cls, *, state: str, code: str, issuer: str | None = None) -> dict[str, Any]:
        """Complete OAuth once and create the authenticated MCP connection.

        State is hashed for lookup and atomically deleted before code exchange,
        preventing replay. The saved issuer is checked, the authorization code
        is bound to the original PKCE verifier, and the token bundle is passed
        directly to owner-scoped encrypted storage rather than returned to the
        browser, catalog, planner, or LLM.
        """

        if not state or len(state) > 512 or not code or len(code) > 4096:
            raise McpOAuthError("OAuth callback parameters are invalid")
        try:
            document = await _collection().find_one_and_delete({
                "_id": _state_hash(state), "expires_at": {"$gt": _utcnow()}
            })
        except PyMongoError as exc:
            raise McpOAuthError("OAuth callback store is unavailable") from exc
        if not document:
            raise McpOAuthError("OAuth state is invalid, expired, or already used")
        # Atomic state consumption blocks callback replay before exchanging the code.
        payload = decrypt_payload(document["payload_ciphertext"])
        if issuer and issuer.rstrip("/") != str(payload["issuer"]).rstrip("/"):
            raise McpOAuthError("OAuth callback issuer does not match the discovered provider")

        token_request = {
            "grant_type": "authorization_code", "code": code,
            "redirect_uri": payload["callback_url"], "client_id": payload["client_id"],
            "code_verifier": payload["verifier"], "resource": payload["resource"],
        }
        headers: dict[str, str] = {}
        client_secret = payload.get("client_secret")
        auth_method = payload.get("token_endpoint_auth_method", "none")
        if client_secret and auth_method == "client_secret_basic":
            encoded = base64.b64encode(
                f"{payload['client_id']}:{client_secret}".encode("utf-8")
            ).decode("ascii")
            headers["Authorization"] = f"Basic {encoded}"
        elif client_secret:
            token_request["client_secret"] = client_secret

        await validate_resolved_endpoint(payload["token_endpoint"])
        async with httpx2.AsyncClient(timeout=20.0, follow_redirects=False) as client:
            response = await client.post(payload["token_endpoint"], data=token_request, headers=headers)
        if response.status_code >= 400:
            raise McpOAuthError("OAuth token exchange failed")
        tokens = response.json()
        if not tokens.get("access_token"):
            raise McpOAuthError("OAuth provider did not return an access token")
        bundle = {
            "access_token": tokens["access_token"], "refresh_token": tokens.get("refresh_token"),
            "expires_at": (_utcnow() + timedelta(seconds=int(tokens.get("expires_in", 3600)))).isoformat(),
            "token_endpoint": payload["token_endpoint"], "issuer": payload["issuer"],
            "scope": tokens.get("scope", " ".join(payload.get("scopes") or [])),
            "client_id": payload["client_id"], "client_secret": client_secret,
            "token_endpoint_auth_method": auth_method,
            "registration_method": payload["registration_method"],
        }
        from core.tooling.mcp_connections import McpConnectionService

        return await McpConnectionService.connect(
            user_id=payload["user_id"], name=payload["name"],
            template_ref=(VersionedCapabilityRef.model_validate(payload["template_ref"])
                          if payload.get("template_ref") else None),
            endpoint=payload["endpoint"], authentication_mode=AuthenticationMode.OAUTH2,
            credential=json.dumps(bundle, separators=(",", ":")), allow_oauth_internal=True,
        )
