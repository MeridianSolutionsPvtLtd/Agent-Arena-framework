"""Security and lifecycle tests for the authenticated-user Agent Registry."""

import asyncio
from types import SimpleNamespace

import pytest
from bson import ObjectId
from fastapi import HTTPException
from pydantic import ValidationError

from models.agent_registry import RegistryAgentCreateRequest
from services import agent_registry_service, agent_service
from models.agent import AgentRunRequest


class FakeCollection:
    def __init__(self):
        self.documents: list[dict] = []

    async def insert_one(self, document):
        stored = dict(document)
        stored["_id"] = ObjectId()
        self.documents.append(stored)
        return SimpleNamespace(inserted_id=stored["_id"])

    async def find_one(self, query):
        return next(
            (
                document
                for document in self.documents
                if all(document.get(key) == value for key, value in query.items())
            ),
            None,
        )

    async def update_one(self, query, update):
        document = await self.find_one(query)
        if document and "$set" in update:
            document.update(update["$set"])
        return SimpleNamespace(matched_count=1 if document else 0)


def _request(agent_id: str = "registered-support") -> RegistryAgentCreateRequest:
    return RegistryAgentCreateRequest(
        agent_id=agent_id,
        name="Registered Support",
        description="A registered Foundry agent",
        tags=[" Support ", "support"],
        provider_config={
            "endpoint": "https://example.services.ai.azure.com/api/projects/demo",
            "provider_agent_id": "asst_example",
        },
    )


def test_registry_agent_id_is_safe_slug():
    with pytest.raises(ValidationError):
        _request("Unsafe Agent ID")


def test_registry_tags_are_normalized():
    assert _request().tags == ["support"]


def test_endpoint_validation_rejects_private_address():
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(agent_registry_service.validate_public_https_endpoint("https://127.0.0.1/agent"))

    assert exc_info.value.status_code == 400


def test_endpoint_validation_enforces_configured_host_allowlist(monkeypatch):
    monkeypatch.setattr(
        agent_registry_service.settings,
        "AGENT_REGISTRY_ALLOWED_HOST_SUFFIXES",
        ("services.ai.azure.com",),
    )

    with pytest.raises(HTTPException, match="allowlisted"):
        asyncio.run(
            agent_registry_service.validate_public_https_endpoint(
                "https://untrusted.example.com/project"
            )
        )


def test_registration_sets_server_owned_fields(monkeypatch):
    collection = FakeCollection()

    async def allow_endpoint(_endpoint):
        return None

    monkeypatch.setattr(agent_registry_service, "_collection", lambda: collection)
    monkeypatch.setattr(agent_registry_service, "validate_public_https_endpoint", allow_endpoint)

    result = asyncio.run(agent_registry_service.register_agent(_request(), "owner-id"))

    assert result["agent_kind"] == "prebuilt"
    assert result["runtime_type"] == "azure_ai_foundry"
    assert result["managed_by"] == "registry"
    assert result["status"] == "draft"
    assert result["authentication"] == {"type": "platform_identity"}


def test_code_owned_agent_id_cannot_be_registered(monkeypatch):
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(agent_registry_service.register_agent(_request("call_audit"), "owner-id"))

    assert exc_info.value.status_code == 409


def test_public_catalog_hides_provider_configuration():
    document = {
        "_id": ObjectId(),
        "agent_id": "registered-support",
        "name": "Registered Support",
        "description": "Support",
        "agent_kind": "prebuilt",
        "runtime_type": "azure_ai_foundry",
        "provider": "azure_ai_foundry",
        "visibility": "public",
        "status": "active",
        "provider_config": {
            "endpoint": "https://secret-provider.example.com",
            "provider_agent_id": "asst_secret",
        },
        "authentication": {"type": "platform_identity"},
    }

    result = agent_service.serialize_agent(document, "user-id", include_config=True)

    assert result["runtime_type"] == "azure_ai_foundry"
    assert result["provider"] == "azure_ai_foundry"
    assert "provider_config" not in result
    assert "authentication" not in result
    assert "secret-provider" not in str(result)


def test_activation_requires_current_verified_configuration(monkeypatch):
    collection = FakeCollection()
    document = {
        "_id": ObjectId(),
        "agent_id": "registered-support",
        "agent_kind": "prebuilt",
        "managed_by": "registry",
        "provider_config": {
            "endpoint": "https://example.services.ai.azure.com/project",
            "provider_agent_id": "asst_example",
        },
        "connection_test": {"status": "untested"},
        "created_by": "owner-id",
    }
    collection.documents.append(document)
    monkeypatch.setattr(agent_registry_service, "_collection", lambda: collection)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            agent_registry_service.set_registered_agent_status(
                "registered-support", "active", "owner-id"
            )
        )

    assert exc_info.value.status_code == 409


def test_user_cannot_manage_another_users_registration(monkeypatch):
    collection = FakeCollection()
    collection.documents.append(
        {
            "_id": ObjectId(),
            "agent_id": "registered-support",
            "agent_kind": "prebuilt",
            "managed_by": "registry",
            "created_by": "owner-id",
        }
    )
    monkeypatch.setattr(agent_registry_service, "_collection", lambda: collection)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            agent_registry_service.get_registered_agent(
                "registered-support", "different-user"
            )
        )

    assert exc_info.value.status_code == 404


def test_unified_runner_dispatches_registered_foundry_agent(monkeypatch):
    from core.persistence.runtime_store import AgentRuntimeStore
    from services import external_thread_service, registered_agent_service

    run_id = ObjectId()
    run_updates = []
    messages = []

    class Runs:
        async def insert_one(self, _document):
            return SimpleNamespace(inserted_id=run_id)

        async def update_one(self, query, update):
            run_updates.append((query, update))

    async def get_agent(*_args, **_kwargs):
        return {
            "_id": ObjectId(),
            "agent_id": "registered-support",
            "agent_kind": "prebuilt",
            "runtime_type": "azure_ai_foundry",
            "provider_config": {
                "endpoint": "https://example.services.ai.azure.com/project",
                "provider_agent_id": "asst_example",
            },
        }

    async def run_registered(_agent, message, provider_thread_id):
        assert message == "Help me"
        assert provider_thread_id is None
        return {
            "response": "How can I help?",
            "thread_id": "provider-thread",
            "usage": {"total_tokens": 4},
        }

    async def create_thread(**_kwargs):
        return "platform-thread"

    async def complete_thread(**kwargs):
        assert kwargs["provider_thread_id"] == "provider-thread"
        return kwargs["requested_thread_id"]

    async def append_message(**kwargs):
        messages.append(kwargs)

    async def noop(*_args, **_kwargs):
        return None

    monkeypatch.setattr(agent_service, "get_accessible_agent", get_agent)
    monkeypatch.setattr(agent_service, "_runs_collection", lambda: Runs())
    monkeypatch.setattr(registered_agent_service, "run_registered_agent", run_registered)
    monkeypatch.setattr(external_thread_service, "create_application_thread", create_thread)
    monkeypatch.setattr(external_thread_service, "complete_provider_thread", complete_thread)
    monkeypatch.setattr(AgentRuntimeStore, "append_message", append_message)
    monkeypatch.setattr(agent_service, "_append_chat", noop)
    monkeypatch.setattr(agent_service, "increment_hit_count", noop)

    result = asyncio.run(
        agent_service.run_agent(
            "registered-support",
            AgentRunRequest(message="Help me"),
            "user-id",
        )
    )

    assert result["status"] == "success"
    assert result["response"] == "How can I help?"
    assert result["thread_id"] == "platform-thread"
    assert [message["role"] for message in messages] == ["user", "assistant"]
    assert run_updates[-1][1]["$set"]["status"] == "success"
