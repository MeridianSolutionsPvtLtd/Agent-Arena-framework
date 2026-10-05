"""Ownership boundary for threads created by external agent providers."""

from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4

from fastapi import HTTPException

from database import get_db


def _collection():
    return get_db()["threads"]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def resolve_provider_thread(
    *,
    thread_id: str,
    user_id: str,
    agent_id: str,
) -> str:
    """Return the private provider thread only when the application thread is owned."""
    thread = await _collection().find_one(
        {
            "thread_id": thread_id,
            "user_id": user_id,
            "agent_id": agent_id,
            "agent_kind": "prebuilt",
            "status": "active",
        },
        {"_id": 0, "provider_thread_id": 1},
    )
    provider_thread_id = (thread or {}).get("provider_thread_id")
    if not provider_thread_id:
        # Do not reveal whether another user's thread exists.
        raise HTTPException(status_code=404, detail="Thread not found")
    return str(provider_thread_id)


async def get_owned_thread(
    *,
    thread_id: str,
    user_id: str,
    agent_id: str,
) -> dict[str, Any]:
    thread = await _collection().find_one(
        {
            "thread_id": thread_id,
            "user_id": user_id,
            "agent_id": agent_id,
            "agent_kind": "prebuilt",
            "status": "active",
        },
        {"_id": 0},
    )
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")
    return thread


async def create_application_thread(
    *,
    user_id: str,
    agent_id: str,
    thread_id: Optional[str] = None,
) -> str:
    """Create an application-owned thread even when no provider thread exists."""
    now = _utcnow()
    application_thread_id = thread_id or f"thread_{uuid4().hex}"
    query = {
        "thread_id": application_thread_id,
        "user_id": user_id,
        "agent_id": agent_id,
    }
    await _collection().update_one(
        query,
        {
            "$setOnInsert": {
                **query,
                "agent_kind": "prebuilt",
                "status": "active",
                "created_at": now,
                "turn_count": 0,
            },
            "$set": {"updated_at": now},
        },
        upsert=True,
    )
    return application_thread_id


async def bind_provider_thread(
    *,
    user_id: str,
    agent_id: str,
    provider_thread_id: str,
    provider: str = "azure_ai_agent",
    thread_id: Optional[str] = None,
) -> str:
    """Register a provider thread and return its public application thread ID."""
    if not provider_thread_id:
        raise ValueError("provider_thread_id is required")

    now = _utcnow()
    application_thread_id = thread_id or f"thread_{uuid4().hex}"
    query = {
        "thread_id": application_thread_id,
        "user_id": user_id,
        "agent_id": agent_id,
    }
    await _collection().update_one(
        query,
        {
            "$setOnInsert": {
                **query,
                "agent_kind": "prebuilt",
                "status": "active",
                "created_at": now,
                "turn_count": 0,
            },
            "$set": {
                "provider": provider,
                "provider_thread_id": provider_thread_id,
                "updated_at": now,
            },
        },
        upsert=True,
    )
    return application_thread_id


async def prepare_provider_thread(
    *,
    thread_id: Optional[str],
    user_id: str,
    agent_id: str,
    require_provider: bool = True,
) -> Optional[str]:
    """Resolve an existing application thread; new chats have no provider thread yet."""
    if not thread_id:
        return None
    thread = await get_owned_thread(
        thread_id=thread_id,
        user_id=user_id,
        agent_id=agent_id,
    )
    provider_thread_id = thread.get("provider_thread_id")
    if require_provider and not provider_thread_id:
        raise HTTPException(status_code=404, detail="Thread not found")
    return str(provider_thread_id) if provider_thread_id else None


async def complete_provider_thread(
    *,
    requested_thread_id: Optional[str],
    provider_thread_id: Optional[str],
    user_id: str,
    agent_id: str,
    provider: str = "azure_ai_agent",
) -> Optional[str]:
    """Bind a provider-created thread, or retain the verified application thread."""
    if not provider_thread_id:
        return requested_thread_id
    return await bind_provider_thread(
        thread_id=requested_thread_id,
        user_id=user_id,
        agent_id=agent_id,
        provider=provider,
        provider_thread_id=provider_thread_id,
    )


async def list_owned_threads(
    *,
    user_id: str,
    agent_id: str,
    limit: int = 100,
) -> list[dict[str, Any]]:
    bounded_limit = max(1, min(int(limit), 200))
    cursor = (
        _collection()
        .find(
            {"user_id": user_id, "agent_id": agent_id, "status": {"$ne": "deleted"}},
            {"_id": 0, "provider_thread_id": 0},
        )
        .sort("updated_at", -1)
        .limit(bounded_limit)
    )
    return await cursor.to_list(length=bounded_limit)
