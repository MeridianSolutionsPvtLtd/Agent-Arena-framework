"""MongoDB repository for the unified governed Capability Catalog.

The collection stores tools, connectors, engines, policies, MCP servers,
datasets, and discovered MCP tool candidates.  Runtime execution is deliberately
out of scope here; the Execution Broker consumes this repository later.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, AsyncIterator, Iterable, Optional

from pymongo import ASCENDING, DESCENDING, ReturnDocument
from pymongo.errors import DuplicateKeyError, PyMongoError

from database import get_db
from models.capability import (
    CapabilityKind,
    CapabilityRecord,
    CapabilityStatus,
    McpRuntimeHealth,
    ToolDefinitionSpec,
    ToolRef,
)
from utils.logger import get_logger


logger = get_logger(__name__)

CAPABILITY_CATALOG_COLLECTION = "capability_catalog"
DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200


class CapabilityCatalogError(RuntimeError):
    """Base error for catalog operations."""


class CapabilityCatalogUnavailable(CapabilityCatalogError):
    """Raised when the database or catalog collection cannot be used."""


class CapabilityNotFound(CapabilityCatalogError):
    """Raised when an exact capability version cannot be found."""


class CapabilityConflict(CapabilityCatalogError):
    """Raised for duplicate versions or concurrent lifecycle updates."""


class InvalidLifecycleTransition(CapabilityCatalogError):
    """Raised when a requested lifecycle transition is not permitted."""


_ALLOWED_TRANSITIONS: dict[CapabilityStatus, set[CapabilityStatus]] = {
    CapabilityStatus.DRAFT: {CapabilityStatus.REVIEW, CapabilityStatus.REJECTED},
    CapabilityStatus.REVIEW: {
        CapabilityStatus.DRAFT,
        CapabilityStatus.APPROVED,
        CapabilityStatus.REJECTED,
    },
    CapabilityStatus.APPROVED: {
        CapabilityStatus.ACTIVE,
        CapabilityStatus.REJECTED,
    },
    CapabilityStatus.ACTIVE: {CapabilityStatus.DEPRECATED},
    CapabilityStatus.DEPRECATED: {CapabilityStatus.RETIRED},
    CapabilityStatus.REJECTED: {CapabilityStatus.DRAFT},
    CapabilityStatus.RETIRED: set(),
}

_SENSITIVE_FIELD_NAMES = {
    "access_token",
    "api_key",
    "client_secret",
    "credential",
    "credentials",
    "password",
    "private_key",
    "refresh_token",
    "secret",
    "token",
}
_SAFE_REFERENCE_FIELDS = {
    "endpoint_ref",
    "package_ref",
    "secret_ref",
}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _bounded_limit(limit: int) -> int:
    try:
        value = int(limit)
    except (TypeError, ValueError):
        value = DEFAULT_PAGE_SIZE
    return max(1, min(value, MAX_PAGE_SIZE))


def _catalog_document_id(kind: CapabilityKind, capability_id: str, version: str) -> str:
    return f"capability:{kind.value}:{capability_id}:{version}"


def _serialize_document(document: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
    if document is None:
        return None
    serialized = dict(document)
    catalog_id = serialized.pop("_id", None)
    if catalog_id is not None:
        serialized["catalog_id"] = str(catalog_id)
    return serialized


def _reject_embedded_secret_material(value: Any, path: str = "spec") -> None:
    """Reject likely secret values; the catalog may contain references only."""

    if isinstance(value, dict):
        for raw_key, nested in value.items():
            key = str(raw_key).strip().lower()
            child_path = f"{path}.{raw_key}"
            # `McpSetupField.secret` is a boolean UI hint indicating that the
            # eventual user input must be stored in the secret provider. It is
            # metadata, not secret material itself.
            if key == "secret" and isinstance(nested, bool):
                continue
            if key in _SENSITIVE_FIELD_NAMES and key not in _SAFE_REFERENCE_FIELDS:
                raise ValueError(
                    f"{child_path} may contain secret material; store a secret_ref instead"
                )
            _reject_embedded_secret_material(nested, child_path)
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            _reject_embedded_secret_material(nested, f"{path}[{index}]")


# Designed and implemented by Rajadurai R.
# MongoDB is the authoritative lifecycle and ownership boundary for governed tools.
class CapabilityCatalog:
    """Production repository for versioned capability definitions."""

    @staticmethod
    def collection():
        db = get_db()
        if db is None:
            raise CapabilityCatalogUnavailable("MongoDB is unavailable")
        return db[CAPABILITY_CATALOG_COLLECTION]

    @classmethod
    async def ensure_indexes(cls) -> None:
        """Create correctness and query indexes required by the catalog.

        All calls go through ensure_index() which provides Cosmos DB
        compatibility: name-first deduplication, graceful handling of
        code 13 (unique index cannot be modified) and code 20
        (partialFilterExpression not supported). Direct create_index()
        calls would crash on existing Cosmos DB collections.
        """
        from core.startup.indexes import ensure_index

        collection = cls.collection()
        await ensure_index(
            collection,
            [
                ("kind", ASCENDING),
                ("capability_id", ASCENDING),
                ("version", ASCENDING),
            ],
            unique=True,
            name="uq_capability_kind_id_version",
        )
        await ensure_index(
            collection,
            [("kind", ASCENDING), ("status", ASCENDING), ("_id", ASCENDING)],
            name="ix_capability_kind_status_page",
        )
        await ensure_index(
            collection,
            [
                ("kind", ASCENDING),
                ("status", ASCENDING),
                ("owner.contact", ASCENDING),
            ],
            name="ix_builder_tools_by_owner",
        )
        await ensure_index(
            collection,
            [
                ("kind", ASCENDING),
                ("status", ASCENDING),
                ("code_owned", ASCENDING),
            ],
            name="ix_builder_platform_tools",
        )
        await ensure_index(
            collection,
            [("status", ASCENDING), ("owner.team", ASCENDING)],
            name="ix_capability_status_owner",
        )
        await ensure_index(
            collection,
            [("updated_at", DESCENDING)],
            name="ix_capability_updated",
        )
        await ensure_index(
            collection,
            [("source.provider", ASCENDING), ("source.asset_id", ASCENDING)],
            name="ix_capability_source_asset",
            sparse=True,
        )
        await ensure_index(
            collection,
            [("kind", ASCENDING), ("runtime_health.status", ASCENDING)],
            name="ix_mcp_server_health",
            sparse=True,
        )
        # Designed and implemented by Rajadurai R.
        # partialFilterExpression + unique is NOT supported by Azure Cosmos DB
        # (code 20). sparse=True achieves the same effect: only documents that
        # have the endpoint_fingerprint field are included in the index.
        await ensure_index(
            collection,
            [("owner.contact", ASCENDING), ("spec.endpoint_fingerprint", ASCENDING)],
            name="ix_mcp_connection_owner_endpoint",
            sparse=True,
        )


    @classmethod
    async def reject_obsolete_approved_seeds(cls, capability_ids: Iterable[str]) -> int:
        """Disable mistakenly seeded metadata without touching active/admin records."""
        ids = sorted({str(item).strip() for item in capability_ids if str(item).strip()})
        if not ids:
            return 0
        now = _utcnow()
        try:
            result = await cls.collection().update_many(
                {
                    "kind": CapabilityKind.TOOL.value,
                    "capability_id": {"$in": ids},
                    "status": CapabilityStatus.APPROVED.value,
                    "code_owned": True,
                    "implementation_ref": {"$regex": r"^agents\."},
                },
                {
                    "$set": {
                        "status": CapabilityStatus.REJECTED.value,
                        "updated_at": now,
                        "updated_by": "system-migration",
                        "lifecycle_reason": "Prebuilt agent workflows remain outside MCP",
                    },
                    "$inc": {"revision": 1},
                },
            )
        except PyMongoError as exc:
            raise CapabilityCatalogUnavailable("Obsolete capability reconciliation failed") from exc
        return int(result.modified_count)

    @classmethod
    async def reject_obsolete_policy_seed(cls, capability_id: str) -> int:
        """Disable the approved code-owned tenant policy replaced by agent assignment."""
        now = _utcnow()
        try:
            result = await cls.collection().update_many(
                {
                    "kind": CapabilityKind.POLICY.value,
                    "capability_id": capability_id,
                    "status": CapabilityStatus.APPROVED.value,
                    "code_owned": True,
                },
                {
                    "$set": {
                        "status": CapabilityStatus.REJECTED.value,
                        "updated_at": now,
                        "updated_by": "system-migration",
                        "lifecycle_reason": "Replaced by exact agent tool assignment",
                    },
                    "$inc": {"revision": 1},
                },
            )
        except PyMongoError as exc:
            raise CapabilityCatalogUnavailable("Obsolete policy reconciliation failed") from exc
        return int(result.modified_count)

    @classmethod
    async def create(
        cls,
        record: CapabilityRecord,
        *,
        actor_id: str,
    ) -> dict[str, Any]:
        """Create a human-managed draft capability version."""

        if record.status != CapabilityStatus.DRAFT:
            raise InvalidLifecycleTransition("new capabilities must begin in draft status")
        if record.runtime_health is not None:
            raise CapabilityConflict(
                "MCP runtime health can only be written by server validation"
            )
        return await cls._insert(record, actor_id=actor_id, code_owned=False)

    @classmethod
    async def seed_code_owned(
        cls,
        record: CapabilityRecord,
        *,
        implementation_ref: str,
    ) -> dict[str, Any]:
        """Idempotently insert an approved or active definition owned by code.

        Existing documents are returned unchanged.  Startup therefore never
        overwrites an administrator's lifecycle decision or silently changes an
        immutable production contract.
        """

        if record.status not in {CapabilityStatus.APPROVED, CapabilityStatus.ACTIVE}:
            raise InvalidLifecycleTransition(
                "code-owned seed records must be approved or active"
            )
        if not implementation_ref or len(implementation_ref) > 500:
            raise ValueError("implementation_ref is required and must not exceed 500 characters")

        _reject_embedded_secret_material(record.spec)
        now = _utcnow()
        document = record.model_dump(mode="json")
        document.update(
            {
                "_id": _catalog_document_id(record.kind, record.capability_id, record.version),
                "created_at": record.created_at or now,
                "updated_at": record.updated_at or now,
                "approved_at": record.approved_at or now,
                "activated_at": (
                    record.activated_at or now
                    if record.status == CapabilityStatus.ACTIVE
                    else None
                ),
                "revision": 1,
                "code_owned": True,
                "implementation_ref": implementation_ref,
                "created_by": "system",
                "updated_by": "system",
            }
        )

        collection = cls.collection()
        try:
            result = await collection.update_one(
                {"_id": document["_id"]},
                {"$setOnInsert": document},
                upsert=True,
            )
            stored = await collection.find_one({"_id": document["_id"]})
            # Code-owned native definitions are safe to activate automatically
            # when a previous deployment seeded them as approved. User-owned
            # and remote MCP records never pass through this seed path.
            if (
                record.status == CapabilityStatus.ACTIVE
                and stored
                and stored.get("status") == CapabilityStatus.APPROVED.value
                and stored.get("code_owned") is True
            ):
                await collection.update_one(
                    {"_id": document["_id"], "code_owned": True},
                    {"$set": {
                        "status": CapabilityStatus.ACTIVE.value,
                        "activated_at": now,
                        "updated_at": now,
                        "updated_by": "system",
                    }},
                )
                stored = await collection.find_one({"_id": document["_id"]})
            # Remove the legacy generated approval hint from code-owned local
            # tools. The actual spec/policy remains unchanged and authoritative.
            if (
                stored
                and stored.get("code_owned") is True
                and (record.spec.get("builder_metadata") or {}).get("requires_approval") is None
                and (stored.get("spec", {}).get("builder_metadata") or {}).get("requires_approval") is not None
            ):
                await collection.update_one(
                    {"_id": document["_id"], "code_owned": True},
                    {"$set": {"spec.builder_metadata.requires_approval": None,
                              "updated_at": now, "updated_by": "system"}},
                )
                stored = await collection.find_one({"_id": document["_id"]})
        except DuplicateKeyError as exc:
            raise CapabilityConflict(f"Capability version already exists: {record.key}") from exc
        except PyMongoError as exc:
            raise CapabilityCatalogUnavailable("Capability seed failed") from exc

        if stored is None:
            raise CapabilityCatalogUnavailable("Capability seed did not return a stored document")
        if result.upserted_id is not None:
            logger.info("Seeded code-owned capability %s", record.key)
        return _serialize_document(stored) or {}

    @classmethod
    async def _insert(
        cls,
        record: CapabilityRecord,
        *,
        actor_id: str,
        code_owned: bool,
    ) -> dict[str, Any]:
        actor = (actor_id or "").strip()
        if not actor or len(actor) > 200:
            raise ValueError("actor_id is required and must not exceed 200 characters")
        _reject_embedded_secret_material(record.spec)

        now = _utcnow()
        document = record.model_dump(mode="json")
        document.update(
            {
                "_id": _catalog_document_id(record.kind, record.capability_id, record.version),
                "created_at": record.created_at or now,
                "updated_at": now,
                "revision": 1,
                "code_owned": code_owned,
                "created_by": actor,
                "updated_by": actor,
            }
        )

        try:
            await cls.collection().insert_one(document)
        except DuplicateKeyError as exc:
            raise CapabilityConflict(f"Capability version already exists: {record.key}") from exc
        except PyMongoError as exc:
            raise CapabilityCatalogUnavailable("Capability creation failed") from exc
        return _serialize_document(document) or {}

    @classmethod
    async def get(
        cls,
        kind: CapabilityKind,
        capability_id: str,
        version: str,
        *,
        allowed_statuses: Optional[Iterable[CapabilityStatus]] = None,
    ) -> dict[str, Any]:
        query: dict[str, Any] = {
            "kind": kind.value,
            "capability_id": capability_id,
            "version": version,
        }
        if allowed_statuses is not None:
            statuses = [status.value for status in allowed_statuses]
            if not statuses:
                raise ValueError("allowed_statuses must not be empty")
            query["status"] = {"$in": statuses}

        try:
            document = await cls.collection().find_one(query)
        except PyMongoError as exc:
            raise CapabilityCatalogUnavailable("Capability lookup failed") from exc
        if document is None:
            raise CapabilityNotFound(
                f"Capability not found: {kind.value}:{capability_id}@{version}"
            )
        return _serialize_document(document) or {}

    @classmethod
    async def get_active_tool(
        cls, tool_ref: ToolRef, *, owner_user_id: Optional[str] = None
    ) -> dict[str, Any]:
        record = await cls.get(
            CapabilityKind.TOOL,
            tool_ref.tool_id,
            tool_ref.version,
            allowed_statuses={CapabilityStatus.ACTIVE},
        )
        if owner_user_id and not record.get("code_owned"):
            if (record.get("owner") or {}).get("contact") != owner_user_id:
                raise CapabilityNotFound(
                    f"Capability not found: tool:{tool_ref.tool_id}@{tool_ref.version}"
                )
        return record

    @classmethod
    async def list_capabilities(
        cls,
        *,
        kind: Optional[CapabilityKind] = None,
        status: Optional[CapabilityStatus] = None,
        owner_team: Optional[str] = None,
        owner_user_id: Optional[str] = None,
        after_id: Optional[str] = None,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> list[dict[str, Any]]:
        query: dict[str, Any] = {}
        if kind is not None:
            query["kind"] = kind.value
        if status is not None:
            query["status"] = status.value
        if owner_team:
            query["owner.team"] = owner_team.strip()
        if owner_user_id:
            query["$or"] = [
                {"code_owned": True},
                {"owner.contact": owner_user_id},
            ]
        if after_id:
            query["_id"] = {"$gt": after_id}

        bounded = _bounded_limit(limit)
        try:
            cursor = cls.collection().find(query).sort("_id", ASCENDING).limit(bounded)
            documents = await cursor.to_list(length=bounded)
        except PyMongoError as exc:
            raise CapabilityCatalogUnavailable("Capability listing failed") from exc
        return [_serialize_document(document) or {} for document in documents]

    @classmethod
    async def list_mcp_templates(cls, *, limit: int = MAX_PAGE_SIZE) -> list[dict[str, Any]]:
        """Return active platform templates without operational or secret fields."""

        projection = {
            "_id": 0, "capability_id": 1, "version": 1, "name": 1,
            "description": 1, "tags": 1, "spec.category": 1, "spec.icon": 1,
            "spec.documentation_url": 1, "spec.setup_fields": 1,
            "spec.setup_instructions": 1, "spec.authentication.mode": 1,
            "spec.trust_level": 1, "spec.maturity": 1,
        }
        query = {
            "kind": CapabilityKind.MCP_SERVER.value,
            "status": CapabilityStatus.ACTIVE.value,
            "spec.purpose": "template",
            "code_owned": True,
        }
        try:
            cursor = cls.collection().find(query, projection).sort("name", ASCENDING)
            return await cursor.limit(_bounded_limit(limit)).to_list(length=_bounded_limit(limit))
        except PyMongoError as exc:
            raise CapabilityCatalogUnavailable("MCP template listing failed") from exc

    @classmethod
    async def list_owned_mcp_connections(
        cls, owner_user_id: str, *, limit: int = MAX_PAGE_SIZE
    ) -> list[dict[str, Any]]:
        # Connections are private to their authenticated owner.
        query = {
            "kind": CapabilityKind.MCP_SERVER.value,
            "spec.purpose": "connection",
            "owner.contact": owner_user_id,
            "status": {"$nin": [CapabilityStatus.RETIRED.value]},
        }
        try:
            cursor = cls.collection().find(query).sort("updated_at", DESCENDING)
            documents = await cursor.limit(_bounded_limit(limit)).to_list(length=_bounded_limit(limit))
            return [_serialize_document(item) or {} for item in documents]
        except PyMongoError as exc:
            raise CapabilityCatalogUnavailable("MCP connection listing failed") from exc

    @classmethod
    async def get_owned(
        cls, kind: CapabilityKind, capability_id: str, version: str, owner_user_id: str
    ) -> dict[str, Any]:
        record = await cls.get(kind, capability_id, version)
        if record.get("code_owned") or (record.get("owner") or {}).get("contact") != owner_user_id:
            raise CapabilityNotFound(
                f"Capability not found: {kind.value}:{capability_id}@{version}"
            )
        return record

    @classmethod
    async def get_visible(
        cls, kind: CapabilityKind, capability_id: str, version: str, owner_user_id: str
    ) -> dict[str, Any]:
        record = await cls.get(kind, capability_id, version)
        if not record.get("code_owned") and (record.get("owner") or {}).get("contact") != owner_user_id:
            raise CapabilityNotFound(
                f"Capability not found: {kind.value}:{capability_id}@{version}"
            )
        return record

    @classmethod
    async def get_active_tools_for_builder(
        cls, *, owner_user_id: Optional[str] = None, limit: int = MAX_PAGE_SIZE
    ) -> list[dict[str, Any]]:
        """Return only safe business metadata needed for automatic tool selection."""

        bounded = _bounded_limit(limit)
        projection = {
            "_id": 0,
            "capability_id": 1,
            "version": 1,
            "name": 1,
            "description": 1,
            "spec.category": 1,
            "spec.risk_level": 1,
            "spec.input_schema": 1,
            "spec.output_schema": 1,
            "spec.builder_metadata": 1,
            "spec.supports_files": 1,
            "spec.timeout_seconds": 1,
            "spec.max_attempts": 1,
            "spec.requires_approval": 1,
        }
        query: dict[str, Any] = {
            "kind": CapabilityKind.TOOL.value,
            "status": CapabilityStatus.ACTIVE.value,
        }
        if owner_user_id:
            query["$or"] = [
                {"code_owned": True},
                {"owner.contact": owner_user_id},
            ]
        try:
            cursor = (
                cls.collection()
                .find(query, projection)
                .sort([("name", ASCENDING), ("version", DESCENDING)])
                .limit(bounded)
            )
            return await cursor.to_list(length=bounded)
        except PyMongoError as exc:
            raise CapabilityCatalogUnavailable("Active tool listing failed") from exc

    @classmethod
    async def stream_active_tools_for_builder(
        cls, *, owner_user_id: str
    ) -> AsyncIterator[dict[str, Any]]:
        """Stream safe active-tool metadata for bounded-memory retrieval.

        Retrieval may inspect a large owned catalog, but only the retriever's
        small ranked shortlist is later placed in an LLM prompt.
        """

        projection = {
            "_id": 0,
            "capability_id": 1,
            "version": 1,
            "name": 1,
            "description": 1,
            "spec.category": 1,
            "spec.risk_level": 1,
            "spec.builder_metadata": 1,
            "spec.supports_files": 1,
            "spec.timeout_seconds": 1,
            "spec.max_attempts": 1,
            "spec.requires_approval": 1,
        }
        query = {
            "kind": CapabilityKind.TOOL.value,
            "status": CapabilityStatus.ACTIVE.value,
            "$or": [
                {"code_owned": True},
                {"owner.contact": owner_user_id},
            ],
        }
        try:
            cursor = cls.collection().find(query, projection).sort(
                [("name", ASCENDING), ("version", DESCENDING)]
            )
            async for document in cursor:
                yield _serialize_document(document) or {}
        except PyMongoError as exc:
            raise CapabilityCatalogUnavailable("Active tool retrieval failed") from exc

    @classmethod
    # Designed and implemented by Rajadurai R.
    async def assert_external_endpoint_available(
        cls, endpoint_fingerprint: str, *, capability_id: str, owner_user_id: str
    ) -> None:
        """Prevent two logical MCP servers from claiming the same endpoint."""

        query = {
            "kind": CapabilityKind.MCP_SERVER.value,
            "capability_id": {"$ne": capability_id},
            "owner.contact": owner_user_id,
            "status": {
                "$nin": [
                    CapabilityStatus.REJECTED.value,
                    CapabilityStatus.RETIRED.value,
                ]
            },
        }
        try:
            existing = await cls.collection().find_one(
                {**query, "spec.endpoint_fingerprint": endpoint_fingerprint},
                {"capability_id": 1},
            )
            if existing is None:
                # Migration compatibility: compare legacy records created before
                # endpoint fingerprints existed.
                legacy = await cls.collection().find(
                    {**query, "spec.endpoint_fingerprint": {"$exists": False}},
                    {"capability_id": 1, "spec.endpoint_ref": 1},
                ).limit(MAX_PAGE_SIZE).to_list(length=MAX_PAGE_SIZE)
                from core.tooling.external_mcp import canonical_endpoint

                for item in legacy:
                    endpoint = ((item.get("spec") or {}).get("endpoint_ref") or "")
                    if endpoint.startswith("https://"):
                        try:
                            _, legacy_fingerprint = canonical_endpoint(endpoint)
                        except ValueError:
                            continue
                        if legacy_fingerprint == endpoint_fingerprint:
                            existing = item
                            break
        except PyMongoError as exc:
            raise CapabilityCatalogUnavailable("MCP endpoint lookup failed") from exc
        if existing is not None:
            raise CapabilityConflict("MCP endpoint is already registered to another server")

    @classmethod
    # Designed and implemented by Rajadurai R.
    async def update_mcp_runtime_health(
        cls,
        capability_id: str,
        version: str,
        health: McpRuntimeHealth,
        *,
        actor_id: str,
    ) -> dict[str, Any]:
        """Update operational health without changing the immutable server contract."""

        actor = (actor_id or "").strip()
        if not actor or len(actor) > 200:
            raise ValueError("actor_id is required and must not exceed 200 characters")
        try:
            document = await cls.collection().find_one_and_update(
                {
                    "kind": CapabilityKind.MCP_SERVER.value,
                    "capability_id": capability_id,
                    "version": version,
                },
                {
                    "$set": {
                        "runtime_health": health.model_dump(mode="json"),
                        "updated_at": _utcnow(),
                        "updated_by": actor,
                    },
                    "$inc": {"revision": 1},
                },
                return_document=ReturnDocument.AFTER,
            )
        except PyMongoError as exc:
            raise CapabilityCatalogUnavailable("MCP health update failed") from exc
        if document is None:
            raise CapabilityNotFound(
                f"Capability not found: mcp_server:{capability_id}@{version}"
            )
        return _serialize_document(document) or {}

    @classmethod
    async def set_owned_mcp_allowed_tools(
        cls,
        capability_id: str,
        version: str,
        owner_user_id: str,
        allowed_tool_names: list[str],
    ) -> dict[str, Any]:
        """Persist an owner's reviewed selection while the connection is mutable."""

        from models.capability import McpServerDefinitionSpec

        # Persist exact reviewed remote names before server activation.
        record = await cls.get_owned(
            CapabilityKind.MCP_SERVER, capability_id, version, owner_user_id
        )
        if record.get("status") != CapabilityStatus.DRAFT.value:
            # Active versions are immutable execution contracts. Adding a fallback
            # tool requires a reviewed successor version; silently mutating the
            # current allowlist would change existing agents after approval.
            raise CapabilityConflict(
                "This MCP tool set is locked after activation; create a new connection version to review a different tool set"
            )
        spec = McpServerDefinitionSpec.model_validate(record["spec"])
        values = spec.model_dump(mode="json")
        values["allowed_tool_names"] = allowed_tool_names
        normalized = McpServerDefinitionSpec.model_validate(values)
        try:
            document = await cls.collection().find_one_and_update(
                {
                    "_id": record["catalog_id"],
                    "status": CapabilityStatus.DRAFT.value,
                    "owner.contact": owner_user_id,
                },
                {
                    "$set": {
                        "spec": normalized.model_dump(mode="json"),
                        "updated_at": _utcnow(),
                        "updated_by": owner_user_id,
                    },
                    "$inc": {"revision": 1},
                },
                return_document=ReturnDocument.AFTER,
            )
        except PyMongoError as exc:
            raise CapabilityCatalogUnavailable("MCP tool selection update failed") from exc
        if document is None:
            raise CapabilityConflict("MCP connection changed while tools were selected")
        return _serialize_document(document) or {}

    @classmethod
    async def retire_owned_mcp_connection(
        cls, capability_id: str, version: str, owner_user_id: str
    ) -> dict[str, Any]:
        """Fail closed, retire an unused connection and its generated tools."""

        # Refuse retirement while an agent still references a generated tool.
        record = await cls.get_owned(
            CapabilityKind.MCP_SERVER, capability_id, version, owner_user_id
        )
        tool_query = {
            "kind": CapabilityKind.TOOL.value,
            "owner.contact": owner_user_id,
            "spec.execution_target.target_ref.capability_id": capability_id,
            "spec.execution_target.target_ref.version": version,
        }
        try:
            tools = await cls.collection().find(
                tool_query, {"capability_id": 1, "version": 1}
            ).to_list(length=10_000)
            tool_ids = [item["capability_id"] for item in tools]
            if tool_ids:
                agents = get_db()["agents"]
                referenced = await agents.find_one({
                    "user_id": owner_user_id,
                    "tool_refs": {"$elemMatch": {"tool_id": {"$in": tool_ids}}},
                }, {"agent_id": 1})
                if referenced:
                    raise CapabilityConflict(
                        "Remove this connection's tools from all agents before disconnecting"
                    )
            now = _utcnow()
            document = await cls.collection().find_one_and_update(
                {
                    "_id": record["catalog_id"],
                    "owner.contact": owner_user_id,
                    "status": {"$ne": CapabilityStatus.RETIRED.value},
                },
                {"$set": {
                    "status": CapabilityStatus.RETIRED.value,
                    "updated_at": now,
                    "updated_by": owner_user_id,
                    "lifecycle_reason": "Owner disconnected MCP server",
                }, "$inc": {"revision": 1}},
                return_document=ReturnDocument.AFTER,
            )
            await cls.collection().update_many(
                tool_query,
                {"$set": {
                    "status": CapabilityStatus.RETIRED.value,
                    "updated_at": now,
                    "updated_by": owner_user_id,
                    "lifecycle_reason": "Owning MCP connection was disconnected",
                }, "$inc": {"revision": 1}},
            )
        except CapabilityConflict:
            raise
        except PyMongoError as exc:
            raise CapabilityCatalogUnavailable("MCP connection could not be disconnected") from exc
        if not document:
            raise CapabilityConflict("MCP connection is already disconnected")
        return _serialize_document(document) or {}

    @classmethod
    async def transition_status(
        cls,
        kind: CapabilityKind,
        capability_id: str,
        version: str,
        *,
        from_status: CapabilityStatus,
        to_status: CapabilityStatus,
        actor_id: str,
        reason: Optional[str] = None,
    ) -> dict[str, Any]:
        """Atomically transition one immutable capability version's lifecycle."""

        if to_status not in _ALLOWED_TRANSITIONS[from_status]:
            raise InvalidLifecycleTransition(
                f"Cannot transition capability from {from_status.value} to {to_status.value}"
            )
        actor = (actor_id or "").strip()
        if not actor or len(actor) > 200:
            raise ValueError("actor_id is required and must not exceed 200 characters")
        if reason is not None and len(reason.strip()) > 2000:
            raise ValueError("reason must not exceed 2000 characters")

        now = _utcnow()
        updates: dict[str, Any] = {
            "status": to_status.value,
            "updated_at": now,
            "updated_by": actor,
            "lifecycle_reason": reason.strip() if reason else None,
        }
        if to_status == CapabilityStatus.APPROVED:
            updates["approved_at"] = now
            updates["approved_by"] = actor
        elif to_status == CapabilityStatus.ACTIVE:
            updates["activated_at"] = now
            updates["activated_by"] = actor
        elif to_status == CapabilityStatus.RETIRED:
            updates["retired_at"] = now
            updates["retired_by"] = actor

        query = {
            "kind": kind.value,
            "capability_id": capability_id,
            "version": version,
            "status": from_status.value,
        }
        try:
            document = await cls.collection().find_one_and_update(
                query,
                {"$set": updates, "$inc": {"revision": 1}},
                return_document=ReturnDocument.AFTER,
            )
        except PyMongoError as exc:
            raise CapabilityCatalogUnavailable("Capability lifecycle update failed") from exc
        if document is None:
            existing = await cls.collection().find_one(
                {
                    "kind": kind.value,
                    "capability_id": capability_id,
                    "version": version,
                },
                {"status": 1},
            )
            if existing is None:
                raise CapabilityNotFound(
                    f"Capability not found: {kind.value}:{capability_id}@{version}"
                )
            raise CapabilityConflict(
                "Capability status changed concurrently or does not match the requested source status"
            )
        return _serialize_document(document) or {}
