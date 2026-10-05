"""
Attachment persistence for the ingestion layer.

Two responsibilities:
  1. Durably store original bytes so executor tools can re-open a file mid-run
     (CrewAI tools take paths, not bytes).
  2. Store the normalized record so a file_id can be resolved on a later turn
     without re-extracting, and so ownership can be verified.

Ownership is enforced at the query level: get() and get_many() always filter on
user_id, so a guessed or leaked file_id from another tenant resolves to nothing.
Do not add a lookup that resolves a file_id without a user_id.
"""
import logging
import os
import uuid
from typing import Any, Dict, List, Optional

from core.persistence.runtime_store import AgentRuntimeStore

logger = logging.getLogger(__name__)

# Mirrors the UPLOADS_DIR convention in main.py. core/ingestion/store.py is two
# levels below the project root.
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
UPLOADS_DIR = os.path.join(BASE_DIR, "uploads")
os.makedirs(UPLOADS_DIR, exist_ok=True)

COLLECTION_NAME = "agent_attachments"


def _collection():
    """Attachment collection, or None if Mongo is not connected yet."""
    db = getattr(AgentRuntimeStore, "db", None)
    if db is None:
        return None
    return db[COLLECTION_NAME]


async def ensure_indexes() -> None:
    """Call once at startup, next to AgentRuntimeStore.ensure_indexes()."""
    from pymongo import ASCENDING, DESCENDING
    from core.startup.indexes import ensure_index

    collection = _collection()
    if collection is None:
        logger.warning("[INGEST] Mongo not connected; attachment indexes skipped")
        return
    try:
        await ensure_index(collection, [("user_id", ASCENDING), ("created_at", DESCENDING)], name="ix_attachments_user_created")
        await ensure_index(collection, [("user_id", ASCENDING), ("sha256", ASCENDING)], name="ix_attachments_user_sha256")
        await ensure_index(collection, [("thread_id", ASCENDING), ("created_at", DESCENDING)], name="ix_attachments_thread_created")
        logger.info("[INGEST] Attachment indexes ensured")
    except Exception as e:
        logger.warning(f"[INGEST] Attachment index creation skipped: {e}")


def new_file_id() -> str:
    return f"file_{uuid.uuid4().hex[:16]}"


def _user_dir(user_id: str) -> str:
    """
    Per-user upload directory. user_id comes from the JWT rather than the request
    body, but it is still sanitized: a directory name is not a place to trust
    anything.
    """
    safe = "".join(c for c in (user_id or "anon") if c.isalnum() or c in "-_")[:64] or "anon"
    path = os.path.join(UPLOADS_DIR, safe)
    os.makedirs(path, exist_ok=True)
    return path


def write_bytes(user_id: str, file_id: str, filename: str, data: bytes) -> str:
    """Persist raw bytes and return the absolute path. The path is never client supplied."""
    target_dir = _user_dir(user_id)
    stored_name = f"{file_id}_{filename}"[:200]
    path = os.path.join(target_dir, stored_name)
    with open(path, "wb") as buffer:
        buffer.write(data)
    return path


class AttachmentStore:
    """Ownership-scoped persistence for normalized attachment dicts."""

    @classmethod
    async def save(cls, attachment: Dict[str, Any]) -> Dict[str, Any]:
        collection = _collection()
        if collection is None:
            logger.warning(f"[INGEST] Mongo unavailable; attachment {attachment.get('file_id')} not persisted")
            return attachment
        try:
            doc = dict(attachment)
            doc["_id"] = attachment.get("file_id")
            await collection.replace_one({"_id": doc["_id"]}, doc, upsert=True)
        except Exception as e:
            logger.error(f"[INGEST] Failed to persist attachment {attachment.get('file_id')}: {e}")
        return attachment

    @classmethod
    async def get(cls, file_id: str, user_id: str) -> Optional[Dict[str, Any]]:
        collection = _collection()
        if collection is None or not file_id or not user_id:
            return None
        doc = await collection.find_one({"_id": file_id, "user_id": user_id})
        return _strip_id(doc)

    @classmethod
    async def get_many(cls, file_ids: List[str], user_id: str) -> List[Dict[str, Any]]:
        """
        Resolve file_ids for one user, preserving the caller's ordering.
        Unknown or foreign ids are dropped; the caller compares counts if it
        wants to surface that as an error.
        """
        collection = _collection()
        ids = [f for f in (file_ids or []) if f]
        if collection is None or not ids or not user_id:
            return []

        found = {}
        cursor = collection.find({"_id": {"$in": ids}, "user_id": user_id})
        async for doc in cursor:
            attachment = _strip_id(doc)
            if attachment:
                found[attachment.get("file_id")] = attachment
        return [found[f] for f in ids if f in found]

    @classmethod
    async def get_for_thread(cls, thread_id: str, user_id: str, agent_id: str) -> List[Dict[str, Any]]:
        """Recover owned attachments bound to a continuing agent thread."""
        collection = _collection()
        if collection is None or not thread_id or not user_id or not agent_id:
            return []
        cursor = collection.find(
            {"thread_id": thread_id, "agent_id": agent_id, "user_id": user_id}
        ).sort("created_at", 1)
        results = []
        async for doc in cursor:
            attachment = _strip_id(doc)
            if attachment:
                results.append(attachment)
        return results

    @classmethod
    async def bind_to_thread(cls, file_ids: List[str], user_id: str, thread_id: str, agent_id: str) -> None:
        """Record which run consumed a file. Used for retention and audit."""
        collection = _collection()
        if collection is None or not file_ids:
            return
        try:
            await collection.update_many(
                {"_id": {"$in": file_ids}, "user_id": user_id},
                {"$set": {"thread_id": thread_id, "agent_id": agent_id}},
            )
        except Exception as e:
            logger.warning(f"[INGEST] Failed to bind attachments to thread {thread_id}: {e}")

    @classmethod
    async def delete(cls, file_id: str, user_id: str) -> bool:
        collection = _collection()
        if collection is None:
            return False

        attachment = await cls.get(file_id, user_id)
        if attachment is None:
            return False

        stored_path = attachment.get("stored_path")
        if stored_path and os.path.exists(stored_path):
            try:
                os.unlink(stored_path)
            except OSError as e:
                logger.warning(f"[INGEST] Could not remove {stored_path}: {e}")

        result = await collection.delete_one({"_id": file_id, "user_id": user_id})
        return bool(result.deleted_count)


def _strip_id(doc: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Mongo _id duplicates file_id; drop it so the dict matches what the normalizer emits."""
    if not doc:
        return None
    attachment = dict(doc)
    attachment.pop("_id", None)
    return attachment
