"""Focused tests for unified-agent validation and ownership boundaries."""

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from bson import ObjectId
from fastapi import HTTPException
from pydantic import ValidationError

from models.agent import AgentRunRequest, AgentUpdateRequest
from services import agent_service
from config import settings, validate_security_settings
from core.file_uploads.validation import validate_referenced_file_paths
from core.orchestration.builder import AgentBuilder


class FakeAgentsCollection:
    def __init__(self):
        self.inserted = None
        self.deleted_query = None
        self.find_result = None

    async def insert_one(self, document):
        self.inserted = dict(document)
        return SimpleNamespace(inserted_id=ObjectId())

    async def delete_one(self, query):
        self.deleted_query = query
        return SimpleNamespace(deleted_count=1)

    async def find_one(self, query):
        return self.find_result


class FakeRunsCollection:
    def __init__(self):
        self.inserted = None
        self.updates = []
        self.run_id = ObjectId()

    async def insert_one(self, document):
        self.inserted = dict(document)
        return SimpleNamespace(inserted_id=self.run_id)

    async def update_one(self, query, update):
        self.updates.append((query, update))
        return SimpleNamespace(matched_count=1)


def test_agent_update_request_normalizes_tools():
    request = AgentUpdateRequest(tools=[" web_search ", "web_search", ""])

    assert request.tools == ["web_search"]


def test_agent_run_rejects_blank_message():
    with pytest.raises(ValidationError):
        AgentRunRequest(message="   ")


def test_serialize_agent_hides_private_prompt_from_non_owner():
    owner_id = str(ObjectId())
    document = {
        "_id": ObjectId(),
        "agent_id": "custom_test",
        "name": "Test",
        "agent_kind": "custom",
        "status": "active",
        "visibility": "private",
        "user_id": owner_id,
        "system_prompt": "private instructions",
        "config": {"model": "private-deployment"},
        "created_at": datetime.now(timezone.utc),
    }

    public_result = agent_service.serialize_agent(document, str(ObjectId()), include_config=True)
    owner_result = agent_service.serialize_agent(document, owner_id, include_config=True)

    assert public_result["config"] == {}
    assert public_result["system_prompt"] is None
    assert owner_result["system_prompt"] == "private instructions"
    assert owner_result["config"]["model"] == "private-deployment"


def test_blueprint_rejects_role_tool_outside_agent_allowlist():
    blueprint = {
        "name": "Research Agent",
        "system_prompt": "Research carefully.",
        "tools": ["web_search"],
        "crew_roles": [
            {
                "role": "Researcher",
                "goal": "Research",
                "assigned_tools": ["send_email"],
            }
        ],
    }

    with pytest.raises(HTTPException) as exc_info:
        agent_service._validate_blueprint(blueprint)

    assert exc_info.value.status_code == 400


def test_governed_blueprint_accepts_external_catalog_tool_and_normalizes_policy(monkeypatch):
    monkeypatch.setattr(settings, "ENABLE_GOVERNED_TOOL_RUNTIME", True)
    cleaned = agent_service._validate_blueprint({
        "name": "CRM Agent",
        "system_prompt": "Use approved CRM operations carefully.",
        "tools": ["crm.search_customer"],
        "tool_refs": [{"tool_id": "crm.search_customer", "version": "1.0.0"}],
        "tool_governance": {
            "crm.search_customer": {
                "confirmation_required": True,
                "timeout_seconds": 10,
            }
        },
    })
    assert cleaned["tool_governance"]["crm.search_customer"] == {
        "confirmation_required": True,
        "timeout_seconds": 10,
        "default_parameters": {},
    }


def test_builder_removes_unknown_tools_and_derives_exact_catalog_refs():
    blueprint = {
        "name": "Workspace Researcher",
        "system_prompt": "Research carefully.",
        "tools": ["notion.search", "friendly-notion-name", "notion.search"],
        "crew_roles": [
            {
                "role": "Researcher",
                "goal": "Find workspace documents",
                "backstory": "A careful researcher",
                "assigned_tools": ["friendly-notion-name", "notion.search"],
            }
        ],
    }
    available = [
        {
            "selection_key": "tool_001",
            "id": "notion.search",
            "version": "1.0.0",
            "name": "Notion Search",
            "description": "Search connected Notion documents",
        }
    ]

    result = AgentBuilder._apply_tool_allowlist(blueprint, available)

    assert result["tools"] == ["notion.search"]
    assert result["tool_refs"] == [
        {"tool_id": "notion.search", "version": "1.0.0"}
    ]
    assert result["crew_roles"][0]["assigned_tools"] == ["notion.search"]


def test_builder_maps_short_selection_keys_to_generated_catalog_ids():
    generated_id = "mcp-abc123.notion_search_f24a391b"
    blueprint = {
        "name": "Notion Researcher",
        "system_prompt": "Search the workspace.",
        "tools": ["tool_001"],
        "crew_roles": [{"assigned_tools": ["tool_001"]}],
    }
    available = [{
        "selection_key": "tool_001",
        "id": generated_id,
        "version": "1.0.0",
        "name": "notion-search",
        "description": "Search the connected Notion workspace",
    }]

    result = AgentBuilder._apply_tool_allowlist(blueprint, available)

    assert result["tools"] == [generated_id]
    assert result["tool_refs"] == [
        {"tool_id": generated_id, "version": "1.0.0"}
    ]
    assert result["crew_roles"][0]["assigned_tools"] == [generated_id]


def test_builder_does_not_fall_back_to_legacy_tools_for_empty_catalog(monkeypatch):
    blueprint = {
        "name": "No Tool Agent",
        "system_prompt": "Answer without tools.",
        "tools": ["web_search"],
        "crew_roles": [],
    }

    result = AgentBuilder._apply_tool_allowlist(blueprint, [])

    assert result["tools"] == []
    assert result["tool_refs"] == []


def test_blueprint_rejects_governance_for_unselected_tool(monkeypatch):
    monkeypatch.setattr(settings, "ENABLE_GOVERNED_TOOL_RUNTIME", True)
    with pytest.raises(HTTPException, match="only reference tools selected"):
        agent_service._validate_blueprint({
            "name": "CRM Agent",
            "system_prompt": "Use approved CRM operations carefully.",
            "tools": ["crm.search_customer"],
            "tool_refs": [{"tool_id": "crm.search_customer", "version": "1.0.0"}],
            "tool_governance": {"crm.delete_customer": {"confirmation_required": True}},
        })


def test_python_tool_is_disabled_by_default(monkeypatch):
    monkeypatch.setattr(settings, "ENABLE_UNSAFE_PYTHON_TOOL", False)

    assert "execute_python" not in agent_service._allowed_custom_tools()


def test_advanced_web_tool_is_disabled_by_default(monkeypatch):
    monkeypatch.setattr(settings, "ENABLE_ADVANCED_WEB_TOOL", False)

    assert "data_collector_visualizer" not in agent_service._allowed_custom_tools()


def test_export_blueprint_removes_database_ownership_fields():
    exported = agent_service._export_blueprint(
        {
            "_id": ObjectId(),
            "user_id": str(ObjectId()),
            "agent_kind": "custom",
            "visibility": "private",
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
            "agent_id": "custom_test",
            "name": "Test Agent",
            "system_prompt": "Be helpful",
        }
    )

    assert exported["agent_id"] == "custom_test"
    assert exported["system_prompt"] == "Be helpful"
    assert "_id" not in exported
    assert "user_id" not in exported


def test_delete_agent_scopes_query_to_owner(monkeypatch):
    collection = FakeAgentsCollection()
    monkeypatch.setattr(agent_service, "_collection", lambda: collection)
    agent_id = str(ObjectId())
    owner_id = str(ObjectId())
    collection.find_result = {
        "_id": ObjectId(agent_id),
        "agent_id": "custom_test",
        "agent_kind": "custom",
        "user_id": owner_id,
    }

    asyncio.run(agent_service.delete_custom_agent(agent_id, owner_id))

    assert collection.deleted_query == {
        "_id": ObjectId(agent_id),
        "agent_kind": "custom",
        "user_id": owner_id,
    }


def test_security_validation_rejects_short_jwt_secret(monkeypatch):
    monkeypatch.setattr(settings, "JWT_SECRET", "short")
    monkeypatch.setattr(settings, "JWT_REFRESH_SECRET", "r" * 32)

    with pytest.raises(RuntimeError, match="JWT_SECRET"):
        validate_security_settings()


def test_security_validation_rejects_shared_secrets(monkeypatch):
    shared = "s" * 32
    monkeypatch.setattr(settings, "JWT_SECRET", shared)
    monkeypatch.setattr(settings, "JWT_REFRESH_SECRET", shared)

    with pytest.raises(RuntimeError, match="different"):
        validate_security_settings()


def test_run_agent_records_success_without_storing_raw_prompt(monkeypatch):
    owner_id = str(ObjectId())
    agent_id = ObjectId()
    runs = FakeRunsCollection()
    calls = {"chat": 0, "usage": 0}

    async def fake_get_agent(*_args, **_kwargs):
        return {
            "_id": agent_id,
            "agent_id": "custom_test",
            "agent_kind": "custom",
            "user_id": owner_id,
        }

    async def fake_run_custom(*_args, **_kwargs):
        return {
            "response": "Safe response",
            "usage": {"prompt_tokens": 2, "completion_tokens": 3, "total_tokens": 5},
            "thread_id": "thread-1",
        }

    async def fake_append_chat(*_args, **_kwargs):
        calls["chat"] += 1

    async def fake_increment(*_args, **_kwargs):
        calls["usage"] += 1

    monkeypatch.setattr(agent_service, "get_accessible_agent", fake_get_agent)
    monkeypatch.setattr(agent_service, "_runs_collection", lambda: runs)
    monkeypatch.setattr(agent_service, "_run_custom", fake_run_custom)
    monkeypatch.setattr(agent_service, "_append_chat", fake_append_chat)
    monkeypatch.setattr(agent_service, "increment_hit_count", fake_increment)

    result = asyncio.run(
        agent_service.run_agent(
            str(agent_id),
            AgentRunRequest(message="Sensitive question", chat_id=str(ObjectId())),
            owner_id,
        )
    )

    assert result["status"] == "success"
    assert result["response"] == "Safe response"
    assert "message" not in runs.inserted
    assert "Sensitive question" not in str(runs.inserted)
    assert len(runs.inserted["input_hash"]) == 64
    assert runs.inserted["agent_id"] == "custom_test"
    assert runs.inserted["agent_document_id"] == str(agent_id)
    assert "agent_key" not in runs.inserted
    assert result["agent_id"] == "custom_test"
    assert result["metadata"]["agent_document_id"] == str(agent_id)
    assert calls == {"chat": 1, "usage": 1}


def test_run_agent_returns_pending_approval_with_execution_id(monkeypatch):
    owner_id = str(ObjectId())
    agent_id = ObjectId()
    runs = FakeRunsCollection()

    async def fake_get_agent(*_args, **_kwargs):
        return {
            "_id": agent_id,
            "agent_id": "custom_pending",
            "agent_kind": "custom",
            "user_id": owner_id,
        }

    async def fake_run_custom(*_args, **_kwargs):
        return {
            "response": "Tool approval is required",
            "thread_id": "thread-pending",
            "hitl_pending": True,
            "approval_type": "tool",
            "tool_execution_id": "tex-pending-123",
            "token_usage": {"total_tokens": 7},
        }

    async def no_op(*_args, **_kwargs):
        return None

    monkeypatch.setattr(agent_service, "get_accessible_agent", fake_get_agent)
    monkeypatch.setattr(agent_service, "_runs_collection", lambda: runs)
    monkeypatch.setattr(agent_service, "_run_custom", fake_run_custom)
    monkeypatch.setattr(agent_service, "_append_chat", no_op)
    monkeypatch.setattr(agent_service, "increment_hit_count", no_op)

    result = asyncio.run(
        agent_service.run_agent(
            str(agent_id),
            AgentRunRequest(message="Search Notion"),
            owner_id,
        )
    )

    assert result["status"] == "pending_approval"
    assert result["approval_type"] == "tool"
    assert result["tool_execution_id"] == "tex-pending-123"
    assert result["data"]["tool_execution_id"] == "tex-pending-123"
    stored_update = runs.updates[-1][1]["$set"]
    assert stored_update["status"] == "pending_approval"
    assert stored_update["approval_type"] == "tool"
    assert stored_update["tool_execution_id"] == "tex-pending-123"
    assert "completed_at" not in stored_update


def test_one_shot_prebuilt_run_gets_application_thread_and_messages(monkeypatch):
    from core.persistence.runtime_store import AgentRuntimeStore
    from services import external_thread_service

    owner_id = str(ObjectId())
    document_id = ObjectId()
    runs = FakeRunsCollection()
    messages = []

    async def fake_get_agent(*_args, **_kwargs):
        return {
            "_id": document_id,
            "agent_id": "recruitment",
            "agent_kind": "prebuilt",
            "config": {"handler": "recruitment"},
        }

    async def fake_run_prebuilt(*_args, **_kwargs):
        return {"response": "Generated job description"}

    async def fake_create_thread(**_kwargs):
        return "thread-application"

    async def fake_append_message(**kwargs):
        messages.append(kwargs)

    async def fake_noop(*_args, **_kwargs):
        return None

    monkeypatch.setattr(agent_service, "get_accessible_agent", fake_get_agent)
    monkeypatch.setattr(agent_service, "_runs_collection", lambda: runs)
    monkeypatch.setattr(agent_service, "_run_prebuilt", fake_run_prebuilt)
    monkeypatch.setattr(agent_service, "_append_chat", fake_noop)
    monkeypatch.setattr(agent_service, "increment_hit_count", fake_noop)
    monkeypatch.setattr(
        external_thread_service,
        "create_application_thread",
        fake_create_thread,
    )
    monkeypatch.setattr(AgentRuntimeStore, "append_message", fake_append_message)

    result = asyncio.run(
        agent_service.run_agent(
            "recruitment",
            AgentRunRequest(message="Create a Python developer JD"),
            owner_id,
        )
    )

    assert result["thread_id"] == "thread-application"
    assert result["data"]["thread_id"] == "thread-application"
    assert [message["role"] for message in messages] == ["user", "assistant"]
    assert all(message["thread_id"] == "thread-application" for message in messages)


def test_runtime_rejects_file_outside_authenticated_upload_root(tmp_path):
    outside_file = tmp_path / "secret.txt"
    outside_file.write_text("secret", encoding="utf-8")

    with pytest.raises(HTTPException) as exc_info:
        validate_referenced_file_paths([str(outside_file)], str(ObjectId()))

    assert exc_info.value.status_code == 400
