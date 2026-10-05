"""Unified agent catalog, ownership, and execution service.

This module deliberately follows the Arena backend's existing service style:
MongoDB access stays close to the feature and existing agent implementations
remain the source of truth for prebuilt execution.
"""

import asyncio
import hashlib
import os
import re
import tempfile
import uuid
import zipfile
from datetime import datetime, timezone
from io import BytesIO
from typing import Any, Optional

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import HTTPException, UploadFile
from pymongo import ReturnDocument
from pymongo.errors import OperationFailure, PyMongoError

from database import get_db
from config import settings
from middleware.hit_counter import increment_hit_count
from models.agent import (
    AgentPreviewRequest,
    AgentRunRequest,
    AgentToolGovernance,
    AgentUpdateRequest,
)
from models.capability import ToolRef
from utils.logger import get_logger


logger = get_logger(__name__)

AGENTS_COLLECTION = "agents"
AGENT_RUNS_COLLECTION = "agent_runs"
# Tools are enabled only when their executor has been migrated and tested here.
# Accepting a tool name without executing it would create a misleading agent.
ALLOWED_CUSTOM_TOOLS = {
    "extract_data_from_file",
    "generate_report",
    "send_email",
    "summarize_content",
    "web_search",
    "mailbox_tracker_graph",
    "speech_to_text",
}


def _allowed_custom_tools() -> set[str]:
    tools = set(ALLOWED_CUSTOM_TOOLS)
    if settings.ENABLE_UNSAFE_PYTHON_TOOL:
        tools.add("execute_python")
    if settings.ENABLE_ADVANCED_WEB_TOOL:
        tools.add("data_collector_visualizer")
    return tools

PREBUILT_AGENTS = (
    {
        "agent_id": "call_audit",
        "name": "Call Audit Agent",
        "description": "Transcribes and audits customer calls.",
        "supports_files": True,
        "handler": "call_audit",
    },
    {
        "agent_id": "compliance_policy",
        "name": "Compliance Agent",
        "description": "Analyzes policies and compliance documents.",
        "supports_files": True,
        "handler": "compliance",
    },
    {
        "agent_id": "data_insights",
        "name": "Data Insights Agent",
        "description": "Analyzes structured data and business context.",
        "supports_files": True,
        "handler": "data_insights",
    },
    {
        "agent_id": "group_discussion",
        "name": "Group Discussion Agent",
        "description": "Produces structured analysis of group discussions.",
        "supports_files": True,
        "handler": "group_discussion",
    },
    {
        "agent_id": "invoice_finance",
        "name": "Invoice Finance Agent",
        "description": "Extracts financial information from invoices.",
        "supports_files": True,
        "handler": "invoice_finance",
    },
    {
        "agent_id": "legal_agent",
        "name": "Legal Agent",
        "description": "Answers legal questions and assists with legal analysis.",
        "supports_files": True,
        "handler": "legal",
    },
    {
        "agent_id": "recruitment",
        "name": "Recruitment Agent",
        "description": "Creates job descriptions and analyzes candidates.",
        "supports_files": True,
        "handler": "recruitment",
    },
    {
        "agent_id": "sql_agent",
        "name": "SQL Agent",
        "description": "Queries uploaded structured datasets.",
        "supports_files": True,
        "handler": "sql_agent",
    },
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _collection():
    db = get_db()
    if db is None:
        raise HTTPException(status_code=503, detail="Database is unavailable")
    return db[AGENTS_COLLECTION]


def _runs_collection():
    db = get_db()
    if db is None:
        raise HTTPException(status_code=503, detail="Database is unavailable")
    return db[AGENT_RUNS_COLLECTION]


def _safe_object_id(value: str, field_name: str = "id") -> ObjectId:
    try:
        return ObjectId(value)
    except (InvalidId, TypeError) as exc:
        raise HTTPException(status_code=400, detail=f"Invalid {field_name}") from exc


def _serialize_datetime(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _validate_custom_config(config: dict[str, Any]) -> dict[str, Any]:
    """Accept only runtime settings that the custom executor actually uses."""
    unknown = sorted(set(config) - {"model"})
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unsupported config fields: {', '.join(unknown)}")
    if "model" not in config:
        return {}
    model = config["model"]
    if not isinstance(model, str) or not model.strip() or len(model.strip()) > 120:
        raise HTTPException(status_code=400, detail="config.model must be a non-empty string")
    return {"model": model.strip()}


def _validate_blueprint(blueprint: dict[str, Any]) -> dict[str, Any]:
    """Validate an LLM-produced blueprint before it crosses the trust boundary."""
    if not isinstance(blueprint, dict):
        raise HTTPException(status_code=400, detail="blueprint must be an object")
    name = str(blueprint.get("name") or "").strip()
    system_prompt = str(blueprint.get("system_prompt") or "").strip()
    if not name or len(name) > 120:
        raise HTTPException(status_code=400, detail="blueprint.name is invalid")
    if not system_prompt or len(system_prompt) > 30000:
        raise HTTPException(status_code=400, detail="blueprint.system_prompt is invalid")

    tools = blueprint.get("tools") or []
    if not isinstance(tools, list) or not all(isinstance(tool, str) for tool in tools):
        raise HTTPException(status_code=400, detail="blueprint.tools must be a string list")
    if not settings.ENABLE_GOVERNED_TOOL_RUNTIME:
        unsupported = sorted(set(tools) - _allowed_custom_tools())
        if unsupported:
            raise HTTPException(status_code=400, detail=f"Unsupported tools: {', '.join(unsupported)}")

    raw_tool_refs = blueprint.get("tool_refs") or []
    if not isinstance(raw_tool_refs, list):
        raise HTTPException(status_code=400, detail="blueprint.tool_refs must be a list")
    normalized_tool_refs: list[dict[str, str]] = []
    referenced_tools: set[str] = set()
    for raw_ref in raw_tool_refs:
        if not isinstance(raw_ref, dict):
            raise HTTPException(status_code=400, detail="Each tool reference must be an object")
        try:
            ref = ToolRef.model_validate(raw_ref)
        except Exception as exc:
            raise HTTPException(status_code=400, detail="Invalid versioned tool reference") from exc
        if ref.tool_id not in tools or ref.tool_id in referenced_tools:
            raise HTTPException(status_code=400, detail="Tool references must uniquely match blueprint tools")
        referenced_tools.add(ref.tool_id)
        normalized_tool_refs.append(ref.model_dump(mode="json"))

    raw_governance = blueprint.get("tool_governance") or {}
    if not isinstance(raw_governance, dict):
        raise HTTPException(status_code=400, detail="blueprint.tool_governance must be an object")
    if not set(raw_governance).issubset(set(tools)):
        raise HTTPException(
            status_code=400,
            detail="Tool governance may only reference tools selected in the blueprint",
        )
    normalized_governance: dict[str, dict[str, Any]] = {}
    for tool_id, raw_policy in raw_governance.items():
        try:
            normalized_governance[tool_id] = AgentToolGovernance.model_validate(
                raw_policy
            ).model_dump(mode="json", exclude_none=True)
        except Exception as exc:
            raise HTTPException(
                status_code=400, detail=f"Invalid agent governance for tool: {tool_id}"
            ) from exc

    crew_roles = blueprint.get("crew_roles") or []
    if not isinstance(crew_roles, list) or len(crew_roles) > 12:
        raise HTTPException(status_code=400, detail="blueprint.crew_roles is invalid")
    normalized_roles = []
    for role in crew_roles:
        if not isinstance(role, dict):
            raise HTTPException(status_code=400, detail="Each crew role must be an object")
        assigned = role.get("assigned_tools") or []
        if not isinstance(assigned, list) or not set(assigned).issubset(set(tools)):
            raise HTTPException(status_code=400, detail="Crew roles may only use blueprint tools")
        normalized_roles.append(
            {
                "role": str(role.get("role") or "Specialist")[:200],
                "goal": str(role.get("goal") or "Complete the assigned task")[:2000],
                "backstory": str(role.get("backstory") or "")[:4000],
                "assigned_tools": assigned,
                "communication_protocol": (
                    str(role.get("communication_protocol"))[:4000]
                    if role.get("communication_protocol")
                    else None
                ),
            }
        )

    cleaned = dict(blueprint)
    cleaned.pop("_id", None)
    cleaned.pop("user_id", None)
    cleaned.pop("agent_id", None)
    cleaned.pop("tool_metadata", None)
    # Preview-only retrieval diagnostics must never become persisted agent policy.
    cleaned.pop("tool_selection_warnings", None)
    cleaned["name"] = name
    cleaned["system_prompt"] = system_prompt
    cleaned["tools"] = list(dict.fromkeys(tools))
    cleaned["tool_refs"] = normalized_tool_refs
    cleaned["tool_governance"] = normalized_governance
    cleaned["crew_roles"] = normalized_roles or [
        {
            "role": "General Specialist",
            "goal": str(blueprint.get("user_intent") or name)[:2000],
            "backstory": system_prompt[:4000],
            "assigned_tools": list(dict.fromkeys(tools)),
            "communication_protocol": None,
        }
    ]
    return cleaned


async def _validate_active_tool_refs(
    blueprint: dict[str, Any], *, authenticated_user_id: str
) -> list[dict[str, Any]]:
    """Validate exact catalog versions when governed runtime is enabled."""
    # Designed and implemented by Rajadurai R.
    # Blueprint ownership is derived from the authenticated user, never request metadata.
    if not settings.ENABLE_GOVERNED_TOOL_RUNTIME:
        return []
    from core.tooling.capability_catalog import CapabilityCatalog, CapabilityCatalogError
    from core.tooling.agent_tool_policy import AgentToolPolicy
    from models.capability import ToolDefinitionSpec

    tools = set(blueprint.get("tools") or [])
    refs = [ToolRef.model_validate(item) for item in blueprint.get("tool_refs") or []]
    if {ref.tool_id for ref in refs} != tools:
        raise HTTPException(
            status_code=400,
            detail="Every governed tool must have one active version reference",
        )
    try:
        metadata: list[dict[str, Any]] = []
        for ref in refs:
            capability = await CapabilityCatalog.get_active_tool(
                ref, owner_user_id=authenticated_user_id
            )
            spec = ToolDefinitionSpec.model_validate(capability["spec"])
            governance = AgentToolGovernance.model_validate(
                (blueprint.get("tool_governance") or {}).get(ref.tool_id) or {}
            )
            AgentToolPolicy.validate_governance(governance, spec)
            metadata.append({
                "tool_id": ref.tool_id,
                "version": ref.version,
                "name": capability.get("name", ""),
                "description": capability.get("description", ""),
                "category": spec.category,
                "risk_level": spec.risk_level.value,
                "platform_approval_required": spec.requires_approval or spec.risk_level.value in {"write", "destructive"},
                "maximum_timeout_seconds": spec.timeout_seconds,
                "maximum_attempts": spec.max_attempts,
                "supports_files": spec.supports_files,
            })
        return metadata
    except (CapabilityCatalogError, ValueError) as exc:
        raise HTTPException(
            status_code=409,
            detail="A selected tool version or agent tool policy is invalid",
        ) from exc


async def preview_custom_agent(
    request: AgentPreviewRequest, user_id: str, tenant_id: Optional[str] = None
) -> dict:
    from core.orchestration.builder import AgentBuilder
    from core.tooling.capability_catalog import CapabilityCatalogUnavailable
    from core.tooling.tool_retriever import ToolRetriever

    try:
        # Designed and implemented by Rajadurai R.
        catalog_tools = await ToolRetriever.search(
            owner_user_id=user_id,
            query=request.query,
        )
    except CapabilityCatalogUnavailable:
        # Migration compatibility only: runtime still uses the native registry
        # until MCP activation. Catalog outages must not broaden the allow-list.
        catalog_tools = []

    blueprint = await asyncio.to_thread(
        AgentBuilder.build,
        request.query,
        user_id,
        request.name,
        request.conversation_history,
        catalog_tools,
    )
    cleaned = _validate_blueprint(blueprint)
    selected_refs = {
        (item["tool_id"], item["version"]) for item in cleaned.get("tool_refs") or []
    }
    cleaned["tool_metadata"] = [
        {
            "tool_id": item["capability_id"],
            "version": item["version"],
            "name": item.get("name", ""),
            "description": item.get("description", ""),
            "risk_level": (item.get("spec") or {}).get("risk_level"),
            "platform_approval_required": bool((item.get("spec") or {}).get("requires_approval"))
            or (item.get("spec") or {}).get("risk_level") in {"write", "destructive"},
            "maximum_timeout_seconds": (item.get("spec") or {}).get("timeout_seconds"),
            "maximum_attempts": (item.get("spec") or {}).get("max_attempts"),
            "selection_reason": item.get("selection_reason"),
            "supports_files": bool((item.get("spec") or {}).get("supports_files")),
            "builder_metadata": (item.get("spec") or {}).get("builder_metadata") or {},
        }
        for item in catalog_tools
        if (item.get("capability_id"), item.get("version")) in selected_refs
    ]
    if catalog_tools and not cleaned.get("tool_refs"):
        cleaned["tool_selection_warnings"] = [
            {
                "code": "no_tool_selected",
                "message": "Relevant tools were found, but no valid tool was selected. Review available tools before creating the agent.",
            }
        ]
    elif not catalog_tools:
        cleaned["tool_selection_warnings"] = [
            {
                "code": "no_relevant_tools",
                "message": "No accessible active tools matched this agent request.",
            }
        ]
    else:
        cleaned["tool_selection_warnings"] = []
    return cleaned


async def create_custom_agent_from_blueprint(
    blueprint: dict[str, Any], user_id: str, tenant_id: Optional[str] = None
) -> dict:
    cleaned = _validate_blueprint(blueprint)
    cleaned["tool_metadata"] = await _validate_active_tool_refs(
        cleaned, authenticated_user_id=user_id
    )
    now = _utcnow()
    agent_id = f"custom_{uuid.uuid4().hex}"
    cleaned.update(
        {
            "agent_id": agent_id,
            "agent_kind": "custom",
            "status": "active",
            "user_id": user_id,
            "visibility": "private",
            "supports_files": (
                any(item.get("supports_files") for item in cleaned.get("tool_metadata") or [])
                if settings.ENABLE_GOVERNED_TOOL_RUNTIME
                else bool(
                    set(cleaned.get("tools") or [])
                    & {"extract_data_from_file", "summarize_content", "speech_to_text"}
                )
            ),
            "config": {},
            "created_at": now,
            "updated_at": now,
        }
    )
    result = await _collection().insert_one(cleaned)
    cleaned["_id"] = result.inserted_id
    return serialize_agent(cleaned, user_id, include_config=True)


def serialize_agent(agent: dict, user_id: str, include_config: bool = False) -> dict:
    """Return the public agent shape without leaking another user's prompt."""
    is_owner = agent.get("agent_kind") == "custom" and agent.get("user_id") == user_id
    config = dict(agent.get("config") or {}) if include_config and is_owner else {}
    if include_config and agent.get("agent_kind") == "prebuilt":
        # Provider endpoints and authentication metadata are intentionally
        # available only to the registration owner through the registry API.
        config = {"handler": (agent.get("config") or {}).get("handler")}

    return {
        "id": str(agent["_id"]),
        "agent_id": agent["agent_id"],
        "name": agent["name"],
        "description": agent.get("description", ""),
        "agent_kind": agent["agent_kind"],
        "status": agent.get("status", "active"),
        "visibility": agent.get("visibility", "private"),
        "supports_files": bool(agent.get("supports_files", False)),
        "tools": list(agent.get("tools") or []),
        "tool_refs": list(agent.get("tool_refs") or []),
        "tool_governance": dict(agent.get("tool_governance") or {}),
        "tool_metadata": list(agent.get("tool_metadata") or []),
        "runtime_type": agent.get("runtime_type"),
        "provider": agent.get("provider"),
        "tags": list(agent.get("tags") or []),
        "is_owner": is_owner,
        "system_prompt": agent.get("system_prompt") if include_config and is_owner else None,
        "config": config,
        "created_at": _serialize_datetime(agent.get("created_at")),
        "updated_at": _serialize_datetime(agent.get("updated_at")),
    }


async def _ensure_index(collection, keys, **kwargs) -> None:
    """Delegate to the Cosmos DB-compatible index utility."""
    from core.startup.indexes import ensure_index
    await ensure_index(collection, keys, **kwargs)


async def initialize_agent_storage() -> None:
    """Create indexes and idempotently seed code-owned prebuilt metadata."""
    from core.tooling.capability_catalog import CapabilityCatalog
    from core.tooling.capability_seed import seed_code_owned_capabilities
    from core.persistence.runtime_store import AgentRuntimeStore
    from core.tooling.tool_execution_store import ToolExecutionStore
    from core.tooling.mcp_oauth import McpOAuthService
    from core.tools.init_tools import register_default_tools

    AgentRuntimeStore.connect(get_db())
    register_default_tools()

    # Designed and implemented by Rajadurai R.
    # Catalog correctness is required at startup. Definitions remain approved
    # (not active) until the MCP server and Execution Broker are deployable.
    await CapabilityCatalog.ensure_indexes()
    await seed_code_owned_capabilities()
    await ToolExecutionStore.ensure_indexes()
    await McpOAuthService.ensure_indexes()

    agents = _collection()
    runs = _runs_collection()

    # The old unique key index must be removed before unsetting the field from
    # multiple documents; otherwise MongoDB permits only one missing value.
    try:
        await agents.drop_index("uq_agents_agent_key")
    except Exception:
        pass

    # One-time, idempotent migration from the former catalog ``agent_key`` to
    # the single stable ``agent_id`` used by both the API and runtime.
    async for document in agents.find({"agent_key": {"$exists": True}}):
        updates: dict[str, Any] = {}
        if not document.get("agent_id") and document.get("agent_key"):
            updates["agent_id"] = document["agent_key"]
        operation: dict[str, Any] = {"$unset": {"agent_key": ""}}
        if updates:
            operation["$set"] = updates
        await agents.update_one({"_id": document["_id"]}, operation)

    # Historical run audits used ``agent_id`` for the Mongo document ID and
    # ``agent_key`` for the stable runtime ID. Normalize those meanings.
    async for document in runs.find({"agent_key": {"$exists": True}}):
        stable_agent_id = document.get("agent_key")
        operation = {"$unset": {"agent_key": ""}}
        if stable_agent_id:
            operation["$set"] = {
                "agent_document_id": document.get("agent_id"),
                "agent_id": stable_agent_id,
            }
        await runs.update_one({"_id": document["_id"]}, operation)

    await AgentRuntimeStore.ensure_indexes()
    
    # Attachment collection for the multimodal ingestion layer.
    # Local import keeps core.ingestion out of this module's import graph.
    from core.ingestion.store import ensure_indexes as ensure_attachment_indexes
    await ensure_attachment_indexes()
    await _ensure_index(agents, "agent_id", unique=True, name="uq_agents_agent_id")
    await _ensure_index(agents, [("user_id", 1), ("agent_kind", 1)], name="ix_agents_owner_kind")
    await _ensure_index(
        agents,
        [("status", 1), ("visibility", 1), ("agent_kind", 1)],
        name="ix_agents_catalog",
    )
    await _ensure_index(
        _runs_collection(),
        [("user_id", 1), ("created_at", -1)],
        name="ix_agent_runs_user_created",
    )
    await _ensure_index(
        agents,
        [("agent_kind", -1), ("name", 1)],
        name="ix_agents_kind_name_sort",
    )
    await _ensure_index(
        agents,
        [("managed_by", 1), ("status", 1), ("updated_at", -1)],
        name="ix_agents_registry_status",
    )

    now = _utcnow()
    for definition in PREBUILT_AGENTS:
        await agents.update_one(
            {"agent_id": definition["agent_id"]},
            {
                "$set": {
                    "name": definition["name"],
                    "description": definition["description"],
                    "agent_kind": "prebuilt",
                    "runtime_type": "local_service",
                    "provider": "local",
                    "managed_by": "code",
                    "agent_id": definition["agent_id"],
                    "user_id": None,
                    "visibility": "public",
                    "supports_files": definition["supports_files"],
                    "tools": [],
                    "config.handler": definition["handler"],
                    "updated_at": now,
                },
                "$setOnInsert": {"status": "active", "created_at": now},
            },
            upsert=True,
        )


async def list_agents(user_id: str, agent_kind: Optional[str] = None) -> list[dict]:
    query: dict[str, Any] = {
        "$or": [
            {"agent_kind": "prebuilt", "visibility": "public", "status": "active"},
            {"agent_kind": "custom", "user_id": user_id},
        ]
    }
    if agent_kind:
        if agent_kind not in {"prebuilt", "custom"}:
            raise HTTPException(status_code=400, detail="Invalid agent_kind")
        query["agent_kind"] = agent_kind

    cursor = _collection().find(query).sort([("agent_kind", -1), ("name", 1)]).limit(200)
    return [serialize_agent(doc, user_id) async for doc in cursor]


async def get_accessible_agent(agent_id: str, user_id: str, include_inactive_owner: bool = False) -> dict:
    identifier_query: dict[str, Any]
    try:
        identifier_query = {"_id": ObjectId(agent_id)}
    except (InvalidId, TypeError):
        identifier_query = {"agent_id": agent_id}

    access = {
        "$or": [
            {"agent_kind": "prebuilt", "visibility": "public", "status": "active"},
            {"agent_kind": "custom", "user_id": user_id},
        ]
    }
    if not include_inactive_owner:
        access = {
            "$or": [
                {"agent_kind": "prebuilt", "visibility": "public", "status": "active"},
                {"agent_kind": "custom", "user_id": user_id, "status": "active"},
            ]
        }
    agent = await _collection().find_one({"$and": [identifier_query, access]})
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent


async def update_custom_agent(
    agent_id: str,
    request: AgentUpdateRequest,
    user_id: str,
    tenant_id: Optional[str] = None,
) -> dict:
    oid = _safe_object_id(agent_id, "agent id")
    update = request.model_dump(exclude_none=True)
    if not update:
        raise HTTPException(status_code=400, detail="No fields provided")
    if "tools" in update and not settings.ENABLE_GOVERNED_TOOL_RUNTIME:
        unsupported = sorted(set(update["tools"]) - _allowed_custom_tools())
        if unsupported:
            raise HTTPException(status_code=400, detail=f"Unsupported tools: {', '.join(unsupported)}")
        update["supports_files"] = bool(
            set(update["tools"])
            & {"extract_data_from_file", "summarize_content", "speech_to_text"}
        )
    if settings.ENABLE_GOVERNED_TOOL_RUNTIME and (
        "tools" in update or "tool_refs" in update or "tool_governance" in update
    ):
        existing = await _collection().find_one(
            {"_id": oid, "agent_kind": "custom", "user_id": user_id}
        )
        if not existing:
            raise HTTPException(status_code=404, detail="Agent not found")
        candidate = _validate_blueprint({**existing, **update})
        update["tool_metadata"] = await _validate_active_tool_refs(
            candidate, authenticated_user_id=user_id
        )
        update["supports_files"] = any(
            item.get("supports_files") for item in update["tool_metadata"]
        )
    if "config" in update:
        update["config"] = _validate_custom_config(update["config"])
    if "system_prompt" in update:
        update["system_prompt"] = update.pop("system_prompt").strip()
    if "name" in update:
        update["name"] = update["name"].strip()
    update["updated_at"] = _utcnow()

    doc = await _collection().find_one_and_update(
        {"_id": oid, "agent_kind": "custom", "user_id": user_id},
        {"$set": update},
        return_document=ReturnDocument.AFTER,
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Agent not found")
    return serialize_agent(doc, user_id, include_config=True)


async def delete_custom_agent(agent_id: str, user_id: str) -> None:
    from core.persistence.runtime_store import AgentRuntimeStore

    oid = _safe_object_id(agent_id, "agent id")
    agent = await _collection().find_one(
        {"_id": oid, "agent_kind": "custom", "user_id": user_id}
    )
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    await AgentRuntimeStore.clear_agent_history(_runtime_agent_id(agent), user_id)
    result = await _collection().delete_one(
        {"_id": oid, "agent_kind": "custom", "user_id": user_id}
    )
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Agent not found")


def _runtime_agent_id(agent: dict) -> str:
    return str(agent.get("agent_id") or agent.get("_id"))


async def get_custom_agent_config(agent_id: str, user_id: str) -> dict:
    agent = await get_accessible_agent(agent_id, user_id, include_inactive_owner=True)
    if agent.get("agent_kind") != "custom" or agent.get("user_id") != user_id:
        raise HTTPException(status_code=404, detail="Agent not found")
    fields = {
        "name",
        "description",
        "domain",
        "user_intent",
        "system_prompt",
        "tools",
        "tool_refs",
        "tool_governance",
        "tool_metadata",
        "crew_roles",
        "validator_config",
        "executor_policy",
        "supports_files",
        "status",
    }
    return {key: agent.get(key) for key in fields if key in agent}


async def update_custom_agent_config(
    agent_id: str,
    config: dict[str, Any],
    user_id: str,
    tenant_id: Optional[str] = None,
) -> dict:
    agent = await get_accessible_agent(agent_id, user_id, include_inactive_owner=True)
    if agent.get("agent_kind") != "custom" or agent.get("user_id") != user_id:
        raise HTTPException(status_code=404, detail="Agent not found")
    allowed = {
        "name",
        "description",
        "domain",
        "user_intent",
        "system_prompt",
        "tools",
        "tool_refs",
        "tool_governance",
        "crew_roles",
        "validator_config",
        "executor_policy",
    }
    unknown = sorted(set(config) - allowed)
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unsupported config fields: {', '.join(unknown)}")
    if not config:
        raise HTTPException(status_code=400, detail="No config fields provided")

    candidate = {**agent, **config}
    cleaned = _validate_blueprint(candidate)
    cleaned["tool_metadata"] = await _validate_active_tool_refs(
        cleaned, authenticated_user_id=user_id
    )
    updates = {key: cleaned[key] for key in allowed if key in cleaned}
    updates["tool_metadata"] = cleaned["tool_metadata"]
    updates["supports_files"] = bool(
        any(item.get("supports_files") for item in cleaned["tool_metadata"])
        if settings.ENABLE_GOVERNED_TOOL_RUNTIME
        else set(updates.get("tools") or agent.get("tools") or [])
        & {"extract_data_from_file", "summarize_content", "speech_to_text"}
    )
    updates["updated_at"] = _utcnow()
    await _collection().update_one(
        {"_id": agent["_id"], "agent_kind": "custom", "user_id": user_id},
        {"$set": updates},
    )
    return await get_custom_agent_config(str(agent["_id"]), user_id)


async def clear_custom_agent_history(agent_id: str, user_id: str) -> None:
    from core.persistence.runtime_store import AgentRuntimeStore

    agent = await get_accessible_agent(agent_id, user_id, include_inactive_owner=True)
    if agent.get("agent_kind") != "custom" or agent.get("user_id") != user_id:
        raise HTTPException(status_code=404, detail="Agent not found")
    if not await AgentRuntimeStore.clear_agent_history(_runtime_agent_id(agent), user_id):
        raise HTTPException(status_code=500, detail="Failed to clear agent history")


async def get_custom_agent_context(agent_id: str, user_id: str, limit: int = 60) -> dict:
    from core.persistence.runtime_store import AgentRuntimeStore

    agent = await get_accessible_agent(agent_id, user_id, include_inactive_owner=True)
    if agent.get("agent_kind") != "custom" or agent.get("user_id") != user_id:
        raise HTTPException(status_code=404, detail="Agent not found")
    runtime_id = _runtime_agent_id(agent)
    thread = await AgentRuntimeStore.get_latest_thread(user_id=user_id, agent_id=runtime_id)
    if not thread:
        return {"thread_id": None, "messages": [], "total_tokens": 0}
    messages = await AgentRuntimeStore.get_messages_for_thread(
        thread_id=thread["thread_id"],
        user_id=user_id,
        agent_id=runtime_id,
        limit=max(1, min(limit, 200)),
    )
    ui_messages = []
    for message in messages:
        role = str(message.get("role") or "").lower()
        if role not in {"user", "assistant"}:
            continue
        metadata = message.get("metadata") or {}
        ui_messages.append(
            {
                "sender": "user" if role == "user" else "bot",
                "text": message.get("text", ""),
                "trace_id": message.get("trace_id"),
                "collaboration": metadata.get("collaboration"),
            }
        )
    return {
        "thread_id": thread["thread_id"],
        "messages": ui_messages,
        "total_tokens": await AgentRuntimeStore.get_cumulative_token_usage(runtime_id, user_id),
    }


async def get_custom_agent_runtime_metadata(agent_id: str, user_id: str, field: str) -> dict:
    from core.persistence.runtime_store import AgentRuntimeStore

    if field not in {"blackboard", "sub_agent_histories"}:
        raise HTTPException(status_code=400, detail="Invalid runtime metadata field")
    agent = await get_accessible_agent(agent_id, user_id, include_inactive_owner=True)
    if agent.get("agent_kind") != "custom" or agent.get("user_id") != user_id:
        raise HTTPException(status_code=404, detail="Agent not found")
    runtime_id = _runtime_agent_id(agent)
    thread = await AgentRuntimeStore.get_latest_thread(user_id=user_id, agent_id=runtime_id)
    if not thread:
        return {}
    messages = await AgentRuntimeStore.get_messages_for_thread(
        thread_id=thread["thread_id"], user_id=user_id, agent_id=runtime_id, limit=1
    )
    if not messages:
        return {}
    return (messages[-1].get("metadata") or {}).get(field, {})


async def run_custom_agent_file(
    agent_id: str,
    file: UploadFile,
    user_id: str,
    *,
    tenant_id: Optional[str] = None,
    message: str = "Analyze the uploaded file.",
    thread_id: Optional[str] = None,
    chat_id: Optional[str] = None,
    payload: Optional[dict[str, Any]] = None,
) -> dict:
    from core.file_uploads.validation import custom_agent_upload_policy, read_upload_with_limit
    from services.blob_service import upload_user_file

    agent = await get_accessible_agent(agent_id, user_id)
    if agent.get("agent_kind") != "custom":
        raise HTTPException(status_code=400, detail="Use the existing prebuilt file endpoint for this agent")
    policy = custom_agent_upload_policy(agent.get("tools") or [])
    content = await read_upload_with_limit(file, policy)

    upload_copy = UploadFile(filename=file.filename or "upload", file=BytesIO(content), headers=file.headers)
    upload_info = await upload_user_file(user_id, upload_copy)

    extension = os.path.splitext(file.filename or "")[1].lower()
    safe_user = re.sub(r"[^A-Za-z0-9_-]", "_", user_id)
    uploads_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "uploads", safe_user))
    os.makedirs(uploads_dir, exist_ok=True)
    local_path = os.path.join(uploads_dir, f"{uuid.uuid4().hex}{extension}")
    with open(local_path, "wb") as buffer:
        buffer.write(content)

    display_message = (message or "Analyze the uploaded file.").strip()
    runtime_query = (
        f"{display_message}\n\nUploaded file path: {local_path}\n"
        f"Original filename: {file.filename or 'upload'}"
    )
    run_payload = dict(payload or {})
    run_payload["_chat_user_message"] = display_message
    try:
        response = await run_agent(
            agent_id,
            AgentRunRequest(
                message=runtime_query,
                thread_id=thread_id,
                chat_id=chat_id,
                payload=run_payload,
            ),
            user_id,
            tenant_id=tenant_id or user_id,
        )
        response["metadata"].update(
            {
                "filename": upload_info["filename"],
                "file_url": upload_info["url"],
                "file_size": upload_info["size"],
            }
        )
        return response
    finally:
        # Keep the local file only while a human-approval plan is pending; the
        # next approved turn recovers its authorized path from thread history.
        if "response" not in locals() or not response.get("data", {}).get("hitl_pending"):
            try:
                os.remove(local_path)
            except OSError:
                logger.warning("Could not remove temporary agent upload %s", local_path)


def _export_blueprint(agent: dict) -> dict:
    excluded = {"_id", "user_id", "created_at", "updated_at", "visibility", "agent_kind"}
    return {key: value for key, value in agent.items() if key not in excluded}


async def export_custom_agent_blueprint(agent_id: str, user_id: str) -> tuple[dict, str]:
    agent = await get_accessible_agent(agent_id, user_id, include_inactive_owner=True)
    if agent.get("agent_kind") != "custom" or agent.get("user_id") != user_id:
        raise HTTPException(status_code=404, detail="Agent not found")
    safe_name = re.sub(r"[^A-Za-z0-9_-]", "_", agent.get("name") or "custom_agent")[:80]
    return _export_blueprint(agent), f"{safe_name}_blueprint.json"


def _build_portable_agent_zip(blueprint: dict, filename_stem: str) -> str:
    backend_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    descriptor, zip_path = tempfile.mkstemp(prefix=f"{filename_stem}_", suffix=".zip")
    os.close(descriptor)
    skip_dirs = {"__pycache__", ".chroma", ".git", "uploads", "outputs", "static"}
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
        import json

        archive.writestr("agent.json", json.dumps(blueprint, indent=2, default=str))
        for source_name in ("runner_stub.py", "requirements.txt", ".env.example"):
            source_path = os.path.join(backend_root, source_name)
            if os.path.isfile(source_path):
                archive.write(source_path, source_name)
        core_root = os.path.join(backend_root, "core")
        for root, directories, files in os.walk(core_root):
            directories[:] = [name for name in directories if name not in skip_dirs]
            for filename in files:
                if filename.endswith((".pyc", ".pyo")):
                    continue
                source_path = os.path.join(root, filename)
                relative = os.path.relpath(source_path, backend_root).replace("\\", "/")
                archive.write(source_path, relative)
        archive.writestr(
            "README.txt",
            "Meridian portable custom agent\n\n"
            "1. Install Python and run: pip install -r requirements.txt\n"
            "2. Copy .env.example to .env and configure required services.\n"
            "3. Run: python runner_stub.py\n"
            "4. Keep agent.json, runner_stub.py, and core/ together.\n",
        )
    return zip_path


async def export_custom_agent_zip(agent_id: str, user_id: str) -> tuple[str, str]:
    blueprint, blueprint_filename = await export_custom_agent_blueprint(agent_id, user_id)
    filename_stem = blueprint_filename.removesuffix("_blueprint.json")
    zip_path = await asyncio.to_thread(_build_portable_agent_zip, blueprint, filename_stem)
    return zip_path, f"{filename_stem}_portable.zip"


def _usage_dict(usage: Any) -> dict[str, int]:
    if usage is None:
        return {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    if hasattr(usage, "model_dump"):
        usage = usage.model_dump()
    if not isinstance(usage, dict):
        return {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    if isinstance(usage.get("per_query"), dict):
        per_query = usage["per_query"]
        return {
            "prompt_tokens": int(per_query.get("query_tokens", 0) or 0)
            + int(per_query.get("context_tokens", 0) or 0),
            "completion_tokens": int(per_query.get("response_tokens", 0) or 0),
            "total_tokens": int(per_query.get("total_tokens", 0) or 0),
        }
    return {
        "prompt_tokens": int(usage.get("prompt_tokens", 0) or 0),
        "completion_tokens": int(usage.get("completion_tokens", 0) or 0),
        "total_tokens": int(usage.get("total_tokens", 0) or 0),
    }


async def _run_custom(
    agent: dict, request: AgentRunRequest, user_id: str, tenant_id: Optional[str] = None,
    agent_run_id: Optional[str] = None,
) -> dict:
    from core.agent_runtime.service import AgentRuntimeService, RunAgentRequest as RuntimeRunRequest

    runtime_request = RuntimeRunRequest(
        query=request.message,
        conversation_history=str(request.payload.get("conversation_history") or ""),
        trace_id=request.payload.get("trace_id"),
        thread_id=request.thread_id,
        file_ids=request.file_ids,
        agent_run_id=agent_run_id,
    )
    return await AgentRuntimeService.run_agent(
        agent["agent_id"],
        runtime_request,
        user_id,
        tenant_id=tenant_id or user_id,
    )


async def _run_prebuilt(
    agent: dict,
    request: AgentRunRequest,
    provider_thread_id: Optional[str] = None,
) -> dict:
    handler = (agent.get("config") or {}).get("handler")
    if handler == "compliance":
        from agents.compliance.service import ComplianceService

        service = ComplianceService()
        prompt = service.build_analysis_prompt(request.message)
        return await asyncio.to_thread(service.run_analysis, prompt, provider_thread_id)
    if handler == "data_insights":
        from agents.data_insights.service import DataInsightsService

        service = DataInsightsService()
        prompt = f"# Data Analysis Request\n\n## Provided Data\n{request.message}"
        context = request.payload.get("context")
        if context:
            prompt += f"\n\n## Context\n{context}"
        prompt += "\n\nPlease perform a full Data Insights Analysis on this data."
        return await asyncio.to_thread(service.get_client().run_analysis, prompt)
    if handler == "group_discussion":
        from agents.group_discussion.service import analyze_gd

        topic = str(request.payload.get("topic") or "").strip()
        if not topic:
            raise HTTPException(status_code=400, detail="payload.topic is required")
        return await analyze_gd(request.message, topic)
    if handler == "recruitment":
        from agents.recruitment.service import generate_jd

        role = str(request.payload.get("role") or request.message).strip()
        return {"response": await generate_jd(role), "role": role}
    if handler == "legal":
        from agents.legal.router import get_agent_client

        return await asyncio.to_thread(
            lambda: get_agent_client().run_query(
                prompt=request.message,
                thread_id=provider_thread_id,
            )
        )
    raise HTTPException(status_code=400, detail="This agent requires its existing file-specific endpoint")


def _response_text(result: dict) -> str:
    return str(
        result.get("response")
        or result.get("summary")
        or result.get("jobDescription")
        or result.get("structuredNotes")
        or ""
    )


async def _append_chat(chat_id: Optional[str], user_id: str, user_text: str, assistant_text: str) -> None:
    if not chat_id:
        return
    oid = _safe_object_id(chat_id, "chat id")
    now = _utcnow().isoformat()
    messages = [
        {"role": "user", "content": user_text, "timestamp": now},
        {"role": "assistant", "content": assistant_text, "timestamp": now},
    ]
    result = await get_db()["chats"].update_one(
        {"_id": oid, "user_id": user_id},
        {"$push": {"messages": {"$each": messages}}, "$set": {"updated_at": now}},
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Chat not found")


async def run_agent(
    agent_id: str,
    request: AgentRunRequest,
    user_id: str,
    tenant_id: Optional[str] = None,
) -> dict:
    agent = await get_accessible_agent(agent_id, user_id)
    started_at = _utcnow()
    run_doc = {
        "user_id": user_id,
        "agent_document_id": str(agent["_id"]),
        "agent_id": agent["agent_id"],
        "agent_kind": agent["agent_kind"],
        "chat_id": request.chat_id,
        "thread_id": request.thread_id,
        "status": "running",
        "input_hash": hashlib.sha256(request.message.encode("utf-8")).hexdigest(),
        "created_at": started_at,
    }
    inserted = await _runs_collection().insert_one(run_doc)

    try:
        if agent["agent_kind"] == "custom":
            result = await _run_custom(
                agent, request, user_id, tenant_id or user_id,
                agent_run_id=str(inserted.inserted_id),
            )
            thread_id = result.get("thread_id") or request.thread_id
        else:
            from services.external_thread_service import (
                complete_provider_thread,
                create_application_thread,
                prepare_provider_thread,
            )

            handler = (agent.get("config") or {}).get("handler")
            is_registered = agent.get("runtime_type") == "azure_ai_foundry"
            thread_id = request.thread_id
            if thread_id:
                provider_thread_id = await prepare_provider_thread(
                    thread_id=thread_id,
                    user_id=user_id,
                    agent_id=agent["agent_id"],
                    require_provider=is_registered or handler in {"compliance", "legal"},
                )
            else:
                thread_id = await create_application_thread(
                    user_id=user_id,
                    agent_id=agent["agent_id"],
                )
                provider_thread_id = None
            if is_registered:
                from services.registered_agent_service import run_registered_agent

                result = await run_registered_agent(
                    agent,
                    request.message,
                    provider_thread_id,
                )
            else:
                result = await _run_prebuilt(agent, request, provider_thread_id)
            thread_id = await complete_provider_thread(
                requested_thread_id=thread_id,
                provider_thread_id=result.get("thread_id"),
                user_id=user_id,
                agent_id=agent["agent_id"],
            )

        response_text = _response_text(result)
        usage = _usage_dict(result.get("usage") or result.get("token_usage"))
        public_result = dict(result)
        hitl_pending = bool(public_result.get("hitl_pending"))
        run_status = "pending_approval" if hitl_pending else "success"
        tool_execution_id = (
            str(public_result.get("tool_execution_id") or "").strip() or None
        )
        approval_type = public_result.get("approval_type") if hitl_pending else None
        if agent["agent_kind"] == "prebuilt":
            # Never expose the provider's thread identifier to clients.
            public_result["thread_id"] = thread_id
            from core.persistence.runtime_store import AgentRuntimeStore

            await AgentRuntimeStore.append_message(
                thread_id=thread_id,
                user_id=user_id,
                agent_id=agent["agent_id"],
                role="user",
                text=request.message,
                metadata={"source": "unified_prebuilt"},
            )
            await AgentRuntimeStore.append_message(
                thread_id=thread_id,
                user_id=user_id,
                agent_id=agent["agent_id"],
                role="assistant",
                text=response_text,
                metadata={"source": "unified_prebuilt"},
            )
        await _append_chat(
            request.chat_id,
            user_id,
            str(request.payload.get("_chat_user_message") or request.message),
            response_text,
        )
        run_updates = {
            "status": run_status,
            "thread_id": thread_id,
            "token_usage": usage,
            "updated_at": _utcnow(),
        }
        if tool_execution_id:
            run_updates["tool_execution_id"] = tool_execution_id
        if approval_type:
            run_updates["approval_type"] = approval_type
        if not hitl_pending:
            run_updates["completed_at"] = _utcnow()
        await _runs_collection().update_one(
            {"_id": inserted.inserted_id},
            {"$set": run_updates},
        )
        await increment_hit_count(
            user_id,
            re.sub(r"[^a-zA-Z0-9_-]", "_", agent["agent_id"]),
            target_field="agent_hits",
            tokens=usage["total_tokens"],
        )
        return {
            "agent_id": agent["agent_id"],
            "agent_kind": agent["agent_kind"],
            "status": run_status,
            "response": response_text,
            "thread_id": thread_id,
            "chat_id": request.chat_id,
            "run_id": str(inserted.inserted_id),
            "tool_execution_id": tool_execution_id,
            "approval_type": approval_type,
            "data": public_result,
            "metadata": {
                "agent_document_id": str(agent["_id"]),
                "token_usage": usage,
            },
        }
    except HTTPException as exc:
        await _runs_collection().update_one(
            {"_id": inserted.inserted_id},
            {"$set": {"status": "error", "error_code": exc.status_code, "completed_at": _utcnow()}},
        )
        raise
    except Exception as exc:
        logger.exception("Agent execution failed (agent=%s, run=%s)", agent["agent_id"], inserted.inserted_id)
        await _runs_collection().update_one(
            {"_id": inserted.inserted_id},
            {"$set": {"status": "error", "error_code": 500, "completed_at": _utcnow()}},
        )
        raise HTTPException(status_code=500, detail="Agent execution failed") from exc


async def list_agent_threads(agent_id: str, user_id: str, limit: int = 100) -> list[dict]:
    """List only application thread metadata owned by the authenticated user."""
    agent = await get_accessible_agent(agent_id, user_id, include_inactive_owner=True)
    from services.external_thread_service import list_owned_threads

    return await list_owned_threads(
        user_id=user_id,
        agent_id=agent["agent_id"],
        limit=limit,
    )


async def get_agent_thread_messages(
    agent_id: str,
    thread_id: str,
    user_id: str,
    limit: int = 100,
) -> dict:
    """Load an owned thread without exposing provider-specific identifiers."""
    agent = await get_accessible_agent(agent_id, user_id, include_inactive_owner=True)
    canonical_agent_id = agent["agent_id"]

    if agent["agent_kind"] == "custom":
        from core.persistence.runtime_store import AgentRuntimeStore

        owned = await AgentRuntimeStore.threads_collection.find_one(
            {
                "thread_id": thread_id,
                "user_id": user_id,
                "agent_id": canonical_agent_id,
            },
            {"_id": 1},
        )
        if not owned:
            raise HTTPException(status_code=404, detail="Thread not found")
        messages = await AgentRuntimeStore.get_messages_for_thread(
            thread_id=thread_id,
            user_id=user_id,
            agent_id=canonical_agent_id,
            limit=limit,
        )
        return {"thread_id": thread_id, "messages": messages}

    from services.external_thread_service import get_owned_thread
    from core.persistence.runtime_store import AgentRuntimeStore

    await get_owned_thread(
        thread_id=thread_id,
        user_id=user_id,
        agent_id=canonical_agent_id,
    )
    messages = await AgentRuntimeStore.get_messages_for_thread(
        thread_id=thread_id,
        user_id=user_id,
        agent_id=canonical_agent_id,
        limit=limit,
    )
    return {"thread_id": thread_id, "messages": messages}
