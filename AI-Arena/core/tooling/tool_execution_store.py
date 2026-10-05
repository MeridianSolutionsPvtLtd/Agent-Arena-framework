"""MongoDB audit repository and state machine for governed tool executions."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from pymongo import ASCENDING, DESCENDING, ReturnDocument
from pymongo.errors import DuplicateKeyError, OperationFailure, PyMongoError

from database import get_db
from models.capability import (
    ApprovalState,
    ApprovalStatus,
    ExecutionContext,
    ToolExecutionStatus,
    ToolRef,
    ToolResult,
)
from models.agent import AgentToolGovernance
from core.security.payload_crypto import decrypt_payload, encrypt_payload


COLLECTION_NAME = "tool_executions"
TERMINAL_STATUSES = {
    ToolExecutionStatus.SUCCESS,
    ToolExecutionStatus.ERROR,
    ToolExecutionStatus.REJECTED,
    ToolExecutionStatus.EXPIRED,
    ToolExecutionStatus.CANCELLED,
}
ALLOWED_TRANSITIONS = {
    ToolExecutionStatus.CREATED: {ToolExecutionStatus.POLICY_CHECK, ToolExecutionStatus.CANCELLED},
    ToolExecutionStatus.POLICY_CHECK: {
        ToolExecutionStatus.PENDING_APPROVAL,
        ToolExecutionStatus.RUNNING,
        ToolExecutionStatus.REJECTED,
        ToolExecutionStatus.ERROR,
    },
    ToolExecutionStatus.PENDING_APPROVAL: {
        ToolExecutionStatus.RUNNING,
        ToolExecutionStatus.REJECTED,
        ToolExecutionStatus.EXPIRED,
        ToolExecutionStatus.CANCELLED,
    },
    ToolExecutionStatus.RUNNING: {
        ToolExecutionStatus.SUCCESS,
        ToolExecutionStatus.ERROR,
        ToolExecutionStatus.CANCELLED,
    },
    ToolExecutionStatus.SUCCESS: set(),
    ToolExecutionStatus.ERROR: set(),
    ToolExecutionStatus.REJECTED: set(),
    ToolExecutionStatus.EXPIRED: set(),
    ToolExecutionStatus.CANCELLED: set(),
}


# Designed and implemented by Rajadurai R.
# The execution collection is both an audit log and a resumable approval state machine.
class ToolExecutionStoreError(RuntimeError):
    pass


class ToolExecutionNotFound(ToolExecutionStoreError):
    pass


class ToolExecutionConflict(ToolExecutionStoreError):
    pass


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    """Normalize BSON datetimes, which Motor returns without UTC tzinfo by default."""

    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _input_hash(arguments: dict[str, Any]) -> str:
    encoded = json.dumps(arguments, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class ToolExecutionStore:
    hash_arguments = staticmethod(_input_hash)
    decrypt_arguments = staticmethod(decrypt_payload)

    @classmethod
    async def attach_continuation(
        cls, execution_id: str, *, user_id: str, agent_id: str,
        continuation: dict[str, Any],
    ) -> None:
        """Persist an encrypted, bounded checkpoint for post-approval resume."""
        encoded = json.dumps(continuation, separators=(",", ":"), default=str)
        if len(encoded.encode("utf-8")) > 256 * 1024:
            raise ToolExecutionStoreError("Continuation checkpoint is too large")
        try:
            result = await cls.collection().update_one(
                {"_id": execution_id, "user_id": user_id, "agent_id": agent_id,
                 "status": ToolExecutionStatus.PENDING_APPROVAL.value},
                {"$set": {"continuation_ciphertext": encrypt_payload(continuation),
                           "updated_at": _utcnow()}, "$inc": {"revision": 1}},
            )
        except PyMongoError as exc:
            raise ToolExecutionStoreError("Continuation checkpoint could not be saved") from exc
        if result.matched_count != 1:
            raise ToolExecutionConflict("Approval continuation is no longer pending")

    @classmethod
    def decrypt_continuation(cls, document: dict[str, Any]) -> Optional[dict[str, Any]]:
        ciphertext = document.get("continuation_ciphertext")
        if not ciphertext:
            return None
        value = decrypt_payload(ciphertext)
        return value if isinstance(value, dict) else None

    @classmethod
    async def clear_continuation(cls, execution_id: str, *, user_id: str) -> None:
        try:
            await cls.collection().update_one(
                {"_id": execution_id, "user_id": user_id},
                {"$unset": {"continuation_ciphertext": ""}, "$set": {"updated_at": _utcnow()}},
            )
        except PyMongoError as exc:
            raise ToolExecutionStoreError("Continuation checkpoint could not be cleared") from exc
    @staticmethod
    def collection():
        db = get_db()
        if db is None:
            raise ToolExecutionStoreError("MongoDB is unavailable")
        return db[COLLECTION_NAME]

    @classmethod
    async def ensure_indexes(cls) -> None:
        """Create indexes required by the tool execution store.

        Uses ensure_index() for full Cosmos DB compatibility.
        partialFilterExpression + unique is replaced with sparse=True
        (Cosmos DB code 20 — partialFilterExpression not supported).
        """
        from core.startup.indexes import ensure_index

        collection = cls.collection()

        # Drop the legacy index name if it exists (idempotent — ignore "not found").
        try:
            await collection.drop_index("uq_tool_execution_tenant_idempotency")
        except OperationFailure as exc:
            if getattr(exc, "code", None) != 27:   # 27 = IndexNotFound
                pass   # Cosmos DB may return a different code; safe to ignore

        # partialFilterExpression + unique is NOT supported by Cosmos DB (code 20).
        # sparse=True indexes only documents where idempotency_key exists (same effect).
        await ensure_index(
            collection,
            [
                ("user_id", ASCENDING),
                ("agent_id", ASCENDING),
                ("idempotency_key", ASCENDING),
            ],
            unique=True,
            sparse=True,
            name="uq_tool_execution_agent_idempotency",
        )
        await ensure_index(
            collection,
            [("user_id", ASCENDING), ("created_at", DESCENDING)],
            name="ix_tool_execution_user_created",
        )
        await ensure_index(
            collection,
            [("status", ASCENDING), ("approval.expires_at", ASCENDING)],
            name="ix_tool_execution_status_expiry",
        )
        await ensure_index(collection, "trace_id", name="ix_tool_execution_trace")


    @classmethod
    async def create(
        cls,
        tool_ref: ToolRef,
        context: ExecutionContext,
        arguments: dict[str, Any],
        *,
        idempotency_key: Optional[str] = None,
        agent_governance: Optional[AgentToolGovernance] = None,
    ) -> dict[str, Any]:
        if idempotency_key is not None:
            idempotency_key = idempotency_key.strip()
            if not idempotency_key or len(idempotency_key) > 200:
                raise ValueError("idempotency_key must be 1-200 characters")
        now = _utcnow()
        execution_id = f"tex_{uuid.uuid4().hex}"
        document = {
            "_id": execution_id,
            "tool_execution_id": execution_id,
            "tool_ref": tool_ref.model_dump(mode="json"),
            "user_id": context.user_id,
            "tenant_id": context.tenant_id,
            "agent_id": context.agent_id,
            "agent_run_id": context.agent_run_id,
            "thread_id": context.thread_id,
            "trace_id": context.trace_id,
            "role": context.role,
            "scopes": context.scopes,
            "file_ids": context.file_ids,
            "input_hash": _input_hash(arguments),
            "input_keys": sorted(str(key) for key in arguments),
            "payload_ciphertext": encrypt_payload(arguments),
            "agent_governance": (agent_governance or AgentToolGovernance()).model_dump(
                mode="json", exclude_none=True
            ),
            "idempotency_key": idempotency_key,
            "status": ToolExecutionStatus.CREATED.value,
            "approval": ApprovalState().model_dump(mode="python"),
            "created_at": now,
            "updated_at": now,
            "revision": 1,
        }
        try:
            await cls.collection().insert_one(document)
        except DuplicateKeyError:
            existing = await cls.collection().find_one(
                {
                    "user_id": context.user_id,
                    "agent_id": context.agent_id,
                    "idempotency_key": idempotency_key,
                }
            )
            if existing and existing.get("input_hash") == document["input_hash"] and existing.get("tool_ref") == document["tool_ref"]:
                return {**existing, "_deduplicated": True}
            raise ToolExecutionConflict("Idempotency key was already used for a different request")
        except PyMongoError as exc:
            raise ToolExecutionStoreError("Tool execution could not be created") from exc
        return {**document, "_deduplicated": False}

    @classmethod
    async def transition(
        cls,
        execution_id: str,
        *,
        from_status: ToolExecutionStatus,
        to_status: ToolExecutionStatus,
        approval: Optional[ApprovalState] = None,
        result: Optional[ToolResult] = None,
    ) -> dict[str, Any]:
        if to_status not in ALLOWED_TRANSITIONS[from_status]:
            raise ToolExecutionConflict(
                f"Invalid execution transition: {from_status.value} to {to_status.value}"
            )
        if to_status == ToolExecutionStatus.PENDING_APPROVAL:
            if approval is None or approval.status != ApprovalStatus.PENDING:
                raise ToolExecutionConflict("Pending approval transition requires pending approval state")
        if to_status in {ToolExecutionStatus.SUCCESS, ToolExecutionStatus.ERROR} and result is None:
            raise ToolExecutionConflict("Completed execution requires a normalized result")

        now = _utcnow()
        updates: dict[str, Any] = {"status": to_status.value, "updated_at": now}
        if approval is not None:
            updates["approval"] = approval.model_dump(mode="python")
        if result is not None:
            updates["result"] = result.model_dump(mode="json")
        if to_status in TERMINAL_STATUSES:
            updates["completed_at"] = now
        try:
            operation: dict[str, Any] = {"$set": updates, "$inc": {"revision": 1}}
            if to_status in TERMINAL_STATUSES:
                operation["$unset"] = {"payload_ciphertext": ""}
            document = await cls.collection().find_one_and_update(
                {"_id": execution_id, "status": from_status.value},
                operation,
                return_document=ReturnDocument.AFTER,
            )
        except PyMongoError as exc:
            raise ToolExecutionStoreError("Tool execution transition failed") from exc
        if document is None:
            existing = await cls.collection().find_one({"_id": execution_id}, {"status": 1})
            if existing is None:
                raise ToolExecutionNotFound("Tool execution was not found")
            raise ToolExecutionConflict("Execution status changed concurrently")
        return document

    @classmethod
    async def get_owned(cls, execution_id: str, user_id: str, tenant_id: str) -> dict[str, Any]:
        try:
            document = await cls.collection().find_one(
                {"_id": execution_id, "user_id": user_id, "tenant_id": tenant_id}
            )
        except PyMongoError as exc:
            raise ToolExecutionStoreError("Tool execution lookup failed") from exc
        if document is None:
            raise ToolExecutionNotFound("Tool execution was not found")
        return document

    @classmethod
    async def decide_approval(
        cls,
        execution_id: str,
        *,
        user_id: str,
        tenant_id: str,
        decision: ApprovalStatus,
        reason: Optional[str] = None,
    ) -> dict[str, Any]:
        if decision not in {ApprovalStatus.APPROVED, ApprovalStatus.REJECTED}:
            raise ValueError("Approval decision must be approved or rejected")
        now = _utcnow()
        status_after = (
            ToolExecutionStatus.PENDING_APPROVAL
            if decision == ApprovalStatus.APPROVED
            else ToolExecutionStatus.REJECTED
        )
        updates: dict[str, Any] = {
            "approval.status": decision.value,
            "approval.decided_at": now,
            "approval.decided_by": user_id,
            "approval.reason": reason.strip() if reason else None,
            "status": status_after.value,
            "updated_at": now,
        }
        if decision == ApprovalStatus.REJECTED:
            updates["completed_at"] = now
        try:
            operation: dict[str, Any] = {"$set": updates, "$inc": {"revision": 1}}
            if decision == ApprovalStatus.REJECTED:
                operation["$unset"] = {"payload_ciphertext": ""}
            document = await cls.collection().find_one_and_update(
                {
                    "_id": execution_id,
                    "user_id": user_id,
                    "tenant_id": tenant_id,
                    "status": ToolExecutionStatus.PENDING_APPROVAL.value,
                    "approval.status": ApprovalStatus.PENDING.value,
                    "approval.expires_at": {"$gt": now},
                },
                operation,
                return_document=ReturnDocument.AFTER,
            )
        except PyMongoError as exc:
            raise ToolExecutionStoreError("Approval decision failed") from exc
        if document is None:
            existing = await cls.get_owned(execution_id, user_id, tenant_id)
            expires_at = (existing.get("approval") or {}).get("expires_at")
            if expires_at and _as_utc(expires_at) <= now:
                await cls.transition(
                    execution_id,
                    from_status=ToolExecutionStatus.PENDING_APPROVAL,
                    to_status=ToolExecutionStatus.EXPIRED,
                )
                raise ToolExecutionConflict("Approval request has expired")
            raise ToolExecutionConflict("Approval was already decided or execution state changed")
        return document
