"""Persistence and lifecycle rules for user-managed agent registrations."""

import asyncio
import hashlib
import ipaddress
import json
import socket
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlsplit

from fastapi import HTTPException
from pymongo.errors import DuplicateKeyError, PyMongoError

from database import get_db
from config import settings
from models.agent_registry import RegistryAgentCreateRequest, RegistryAgentUpdateRequest
from utils.logger import get_logger


logger = get_logger(__name__)
COLLECTION = "agents"
CODE_OWNED_AGENT_IDS = {
    "call_audit",
    "compliance_policy",
    "data_insights",
    "group_discussion",
    "invoice_finance",
    "legal_agent",
    "recruitment",
    "sql_agent",
}


def _collection():
    db = get_db()
    if db is None:
        raise HTTPException(status_code=503, detail="Database is unavailable")
    return db[COLLECTION]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _config_fingerprint(provider_config: dict[str, Any]) -> str:
    canonical = json.dumps(provider_config, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _is_forbidden_ip(value: str) -> bool:
    address = ipaddress.ip_address(value)
    return not address.is_global


async def validate_public_https_endpoint(endpoint: str) -> None:
    """Reject endpoints that could reach local, private, or metadata networks."""
    parsed = urlsplit(endpoint)
    if parsed.scheme.lower() != "https" or not parsed.hostname:
        raise HTTPException(status_code=400, detail="Provider endpoint must use HTTPS")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise HTTPException(
            status_code=400,
            detail="Provider endpoint must not contain credentials, query parameters, or fragments",
        )

    hostname = parsed.hostname.rstrip(".").lower()
    if hostname in {"localhost", "localhost.localdomain"}:
        raise HTTPException(status_code=400, detail="Provider endpoint is not allowed")
    allowed_suffixes = settings.AGENT_REGISTRY_ALLOWED_HOST_SUFFIXES
    if allowed_suffixes and not any(
        hostname == suffix or hostname.endswith(f".{suffix}")
        for suffix in allowed_suffixes
    ):
        raise HTTPException(status_code=400, detail="Provider endpoint host is not allowlisted")

    try:
        if _is_forbidden_ip(hostname):
            raise HTTPException(status_code=400, detail="Provider endpoint is not allowed")
        return
    except ValueError:
        pass

    try:
        records = await asyncio.to_thread(
            socket.getaddrinfo,
            hostname,
            parsed.port or 443,
            type=socket.SOCK_STREAM,
        )
    except socket.gaierror as exc:
        raise HTTPException(status_code=400, detail="Provider endpoint could not be resolved") from exc

    addresses = {record[4][0] for record in records}
    if not addresses or any(_is_forbidden_ip(address) for address in addresses):
        raise HTTPException(status_code=400, detail="Provider endpoint is not allowed")


def serialize_registry_agent(document: dict[str, Any]) -> dict[str, Any]:
    result = {
        key: value
        for key, value in document.items()
        if key not in {"_id"}
    }
    result["id"] = str(document["_id"])
    for key in ("created_at", "updated_at"):
        if isinstance(result.get(key), datetime):
            result[key] = result[key].isoformat()
    test = dict(result.get("connection_test") or {})
    if isinstance(test.get("tested_at"), datetime):
        test["tested_at"] = test["tested_at"].isoformat()
    result["connection_test"] = test
    return result


async def register_agent(request: RegistryAgentCreateRequest, owner_user_id: str) -> dict:
    if request.agent_id in CODE_OWNED_AGENT_IDS:
        raise HTTPException(status_code=409, detail="Agent ID is reserved by a code-owned agent")

    provider_config = request.provider_config.model_dump(mode="json")
    await validate_public_https_endpoint(provider_config["endpoint"])
    now = _utcnow()
    document = {
        "agent_id": request.agent_id,
        "name": request.name,
        "description": request.description,
        "agent_kind": "prebuilt",
        "runtime_type": "azure_ai_foundry",
        "provider": request.provider,
        "visibility": "public",
        "status": "draft",
        "supports_files": False,
        "tools": [],
        "tags": request.tags,
        "provider_config": provider_config,
        "authentication": {"type": "platform_identity"},
        "managed_by": "registry",
        "connection_test": {
            "status": "untested",
            "config_fingerprint": _config_fingerprint(provider_config),
            "tested_at": None,
        },
        "created_by": owner_user_id,
        "created_at": now,
        "updated_at": now,
    }
    try:
        result = await _collection().insert_one(document)
    except DuplicateKeyError as exc:
        raise HTTPException(status_code=409, detail="Agent ID already exists") from exc
    except PyMongoError as exc:
        logger.exception("Agent registry insert failed")
        raise HTTPException(status_code=503, detail="Agent registry is unavailable") from exc
    document["_id"] = result.inserted_id
    return serialize_registry_agent(document)


async def get_registered_agent(agent_id: str, owner_user_id: str) -> dict:
    document = await _collection().find_one(
        {
            "agent_id": agent_id,
            "managed_by": "registry",
            "agent_kind": "prebuilt",
            "created_by": owner_user_id,
        }
    )
    if not document:
        raise HTTPException(status_code=404, detail="Registered agent not found")
    return document


async def list_registered_agents(owner_user_id: str, limit: int = 200) -> list[dict]:
    bounded_limit = max(1, min(int(limit), 200))
    cursor = (
        _collection()
        .find(
            {
                "managed_by": "registry",
                "agent_kind": "prebuilt",
                "created_by": owner_user_id,
            }
        )
        .sort("updated_at", -1)
        .limit(bounded_limit)
    )
    return [serialize_registry_agent(item) for item in await cursor.to_list(bounded_limit)]


async def update_registered_agent(
    agent_id: str,
    request: RegistryAgentUpdateRequest,
    owner_user_id: str,
) -> dict:
    document = await get_registered_agent(agent_id, owner_user_id)
    changes = request.model_dump(exclude_unset=True, mode="json")
    if not changes:
        raise HTTPException(status_code=400, detail="No registry fields provided")

    if "provider_config" in changes:
        await validate_public_https_endpoint(changes["provider_config"]["endpoint"])
        changes["connection_test"] = {
            "status": "untested",
            "config_fingerprint": _config_fingerprint(changes["provider_config"]),
            "tested_at": None,
        }
        changes["status"] = "draft"
    changes["updated_by"] = owner_user_id
    changes["updated_at"] = _utcnow()
    await _collection().update_one({"_id": document["_id"]}, {"$set": changes})
    updated = await _collection().find_one({"_id": document["_id"]})
    return serialize_registry_agent(updated)


async def record_connection_test(
    agent_id: str,
    owner_user_id: str,
    *,
    success: bool,
    provider_name: str | None = None,
    latency_ms: int | None = None,
    error_code: str | None = None,
) -> dict:
    document = await get_registered_agent(agent_id, owner_user_id)
    test_result = {
        "status": "verified" if success else "failed",
        "config_fingerprint": _config_fingerprint(document["provider_config"]),
        "tested_at": _utcnow(),
        "provider_name": provider_name,
        "latency_ms": latency_ms,
        "error_code": error_code,
    }
    await _collection().update_one(
        {"_id": document["_id"]},
        {"$set": {"connection_test": test_result, "updated_at": _utcnow()}},
    )
    return test_result


async def set_registered_agent_status(agent_id: str, status: str, owner_user_id: str) -> dict:
    if status not in {"active", "inactive"}:
        raise HTTPException(status_code=400, detail="Unsupported registry status")
    document = await get_registered_agent(agent_id, owner_user_id)
    if status == "active":
        test = document.get("connection_test") or {}
        current_fingerprint = _config_fingerprint(document["provider_config"])
        if test.get("status") != "verified" or test.get("config_fingerprint") != current_fingerprint:
            raise HTTPException(status_code=409, detail="A successful connection test is required")
    await _collection().update_one(
        {"_id": document["_id"]},
        {
            "$set": {
                "status": status,
                "updated_by": owner_user_id,
                "updated_at": _utcnow(),
            }
        },
    )
    document["status"] = status
    document["updated_by"] = owner_user_id
    document["updated_at"] = _utcnow()
    return serialize_registry_agent(document)
