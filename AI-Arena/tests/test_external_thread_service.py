"""Security tests for application-owned external provider threads."""

import asyncio

import pytest
from fastapi import HTTPException

from services import external_thread_service


class FakeThreadCollection:
    def __init__(self):
        self.documents = []

    async def find_one(self, query, projection=None):
        for document in self.documents:
            if all(document.get(key) == value for key, value in query.items()):
                if not projection:
                    return dict(document)
                if projection and not any(projection.values()):
                    return {
                        key: value
                        for key, value in document.items()
                        if projection.get(key, 1)
                    }
                return {
                    key: value
                    for key, value in document.items()
                    if projection.get(key)
                }
        return None

    async def update_one(self, query, update, upsert=False):
        existing = await self.find_one(query)
        if existing:
            for document in self.documents:
                if all(document.get(key) == value for key, value in query.items()):
                    document.update(update.get("$set", {}))
                    break
        elif upsert:
            document = dict(update.get("$setOnInsert", {}))
            document.update(update.get("$set", {}))
            self.documents.append(document)


def test_external_thread_is_bound_to_user_and_agent(monkeypatch):
    collection = FakeThreadCollection()
    monkeypatch.setattr(external_thread_service, "_collection", lambda: collection)

    application_id = asyncio.run(
        external_thread_service.bind_provider_thread(
            user_id="user-a",
            agent_id="compliance_policy",
            provider_thread_id="azure-secret-thread",
        )
    )
    provider_id = asyncio.run(
        external_thread_service.resolve_provider_thread(
            thread_id=application_id,
            user_id="user-a",
            agent_id="compliance_policy",
        )
    )

    assert application_id.startswith("thread_")
    assert application_id != "azure-secret-thread"
    assert provider_id == "azure-secret-thread"


def test_other_user_cannot_resolve_external_thread(monkeypatch):
    collection = FakeThreadCollection()
    monkeypatch.setattr(external_thread_service, "_collection", lambda: collection)
    application_id = asyncio.run(
        external_thread_service.bind_provider_thread(
            user_id="user-a",
            agent_id="legal_agent",
            provider_thread_id="azure-secret-thread",
        )
    )

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            external_thread_service.resolve_provider_thread(
                thread_id=application_id,
                user_id="user-b",
                agent_id="legal_agent",
            )
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Thread not found"


def test_thread_cannot_be_reused_across_agents(monkeypatch):
    collection = FakeThreadCollection()
    monkeypatch.setattr(external_thread_service, "_collection", lambda: collection)
    application_id = asyncio.run(
        external_thread_service.bind_provider_thread(
            user_id="user-a",
            agent_id="legal_agent",
            provider_thread_id="azure-secret-thread",
        )
    )

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            external_thread_service.resolve_provider_thread(
                thread_id=application_id,
                user_id="user-a",
                agent_id="compliance_policy",
            )
        )

    assert exc_info.value.status_code == 404


def test_one_shot_prebuilt_thread_does_not_require_provider_id(monkeypatch):
    collection = FakeThreadCollection()
    monkeypatch.setattr(external_thread_service, "_collection", lambda: collection)
    application_id = asyncio.run(
        external_thread_service.create_application_thread(
            user_id="user-a",
            agent_id="recruitment",
        )
    )

    provider_id = asyncio.run(
        external_thread_service.prepare_provider_thread(
            thread_id=application_id,
            user_id="user-a",
            agent_id="recruitment",
            require_provider=False,
        )
    )

    assert application_id.startswith("thread_")
    assert provider_id is None
