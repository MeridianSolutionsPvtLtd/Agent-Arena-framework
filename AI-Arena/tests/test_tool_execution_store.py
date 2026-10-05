"""State-machine and privacy tests for tool execution audit records."""

import asyncio
from types import SimpleNamespace

import pytest

from core.tooling.tool_execution_store import ToolExecutionConflict, ToolExecutionStore
from models.capability import (
    ApprovalState,
    ApprovalStatus,
    ExecutionContext,
    ToolExecutionStatus,
    ToolRef,
)


class _Collection:
    def __init__(self):
        self.documents = {}

    async def insert_one(self, document):
        self.documents[document["_id"]] = dict(document)
        return SimpleNamespace(inserted_id=document["_id"])

    async def find_one(self, query, projection=None):
        for document in self.documents.values():
            if all(document.get(key) == value for key, value in query.items()):
                if projection:
                    return {key: document.get(key) for key in projection}
                return dict(document)
        return None

    async def find_one_and_update(self, query, update, return_document=None):
        document = await self.find_one(query)
        if document is None:
            return None
        stored = self.documents[document["_id"]]
        stored.update(update.get("$set", {}))
        stored["revision"] += update.get("$inc", {}).get("revision", 0)
        return dict(stored)


def _context():
    return ExecutionContext(
        user_id="user-1", tenant_id="tenant-1", agent_id="agent-1",
        role="analyst", trace_id="trace-1",
    )


def test_audit_record_hashes_arguments_without_storing_values(monkeypatch):
    collection = _Collection()
    monkeypatch.setattr(ToolExecutionStore, "collection", staticmethod(lambda: collection))
    stored = asyncio.run(
        ToolExecutionStore.create(
            ToolRef(tool_id="send_email", version="1.0.0"),
            _context(),
            {"recipient": "private@example.com", "body": "confidential"},
        )
    )
    serialized = str(stored)
    assert "private@example.com" not in serialized
    assert "confidential" not in serialized
    assert stored["input_keys"] == ["body", "recipient"]
    assert len(stored["input_hash"]) == 64


def test_pending_approval_requires_consistent_state(monkeypatch):
    collection = _Collection()
    monkeypatch.setattr(ToolExecutionStore, "collection", staticmethod(lambda: collection))
    created = asyncio.run(
        ToolExecutionStore.create(
            ToolRef(tool_id="send_email", version="1.0.0"), _context(), {}
        )
    )
    asyncio.run(
        ToolExecutionStore.transition(
            created["_id"],
            from_status=ToolExecutionStatus.CREATED,
            to_status=ToolExecutionStatus.POLICY_CHECK,
        )
    )
    with pytest.raises(ToolExecutionConflict, match="pending approval state"):
        asyncio.run(
            ToolExecutionStore.transition(
                created["_id"],
                from_status=ToolExecutionStatus.POLICY_CHECK,
                to_status=ToolExecutionStatus.PENDING_APPROVAL,
                approval=ApprovalState(),
            )
        )


def test_terminal_execution_cannot_transition_again():
    with pytest.raises(ToolExecutionConflict, match="Invalid execution transition"):
        asyncio.run(
            ToolExecutionStore.transition(
                "tex-1",
                from_status=ToolExecutionStatus.SUCCESS,
                to_status=ToolExecutionStatus.RUNNING,
            )
        )
