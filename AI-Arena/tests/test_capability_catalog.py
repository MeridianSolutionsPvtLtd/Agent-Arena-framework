"""Focused tests for Capability Catalog contracts and repository boundaries."""

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from core.tooling import capability_catalog
from core.tooling.capability_seed import build_code_owned_capabilities
from models.capability import (
    ApprovalState,
    ApprovalStatus,
    AuthenticationMode,
    AuthenticationSpec,
    CapabilityKind,
    CapabilityOwner,
    CapabilityRecord,
    CapabilityStatus,
    ExecutionTarget,
    ExecutionTargetKind,
    RiskLevel,
    ToolDefinitionSpec,
    VersionedCapabilityRef,
    ToolRef,
)


def _tool_record(*, status: CapabilityStatus = CapabilityStatus.DRAFT) -> CapabilityRecord:
    return CapabilityRecord(
        kind=CapabilityKind.TOOL,
        capability_id="summarize_content",
        version="1.0.0",
        status=status,
        name="Summarize Content",
        description="Summarizes supplied content.",
        owner=CapabilityOwner(team="platform"),
        spec=ToolDefinitionSpec(
            category="knowledge",
            risk_level=RiskLevel.READ_ONLY,
            input_schema={"type": "object"},
            output_schema={"type": "object"},
            execution_target=ExecutionTarget(
                kind=ExecutionTargetKind.NATIVE_MCP,
                target_ref=VersionedCapabilityRef(
                    capability_id="meridian_native_tools",
                    version="1.0.0",
                ),
                operation="summarize_content",
            ),
            idempotent=True,
            max_attempts=2,
        ).model_dump(mode="json"),
    )


def test_write_tool_cannot_enable_automatic_retries():
    with pytest.raises(ValidationError, match="write or destructive"):
        ToolDefinitionSpec(
            category="communication",
            risk_level=RiskLevel.WRITE,
            input_schema={"type": "object"},
            output_schema={"type": "object"},
            execution_target=ExecutionTarget(
                kind=ExecutionTargetKind.NATIVE_MCP,
                target_ref=VersionedCapabilityRef(
                    capability_id="meridian_native_tools",
                    version="1.0.0",
                ),
                operation="send_email",
            ),
            idempotent=True,
            max_attempts=2,
        )


def test_secret_authentication_requires_reference_only():
    with pytest.raises(ValidationError, match="requires secret_ref"):
        AuthenticationSpec(mode=AuthenticationMode.OAUTH2)

    authentication = AuthenticationSpec(
        mode=AuthenticationMode.OAUTH2,
        secret_ref="keyvault://graph-oauth",
    )
    assert authentication.secret_ref == "keyvault://graph-oauth"


def test_catalog_rejects_embedded_secret_material():
    record = _tool_record()
    record.spec["api_key"] = "raw-secret"

    with pytest.raises(ValueError, match="secret_ref"):
        asyncio.run(
            capability_catalog.CapabilityCatalog.create(
                record,
                actor_id="admin-user",
            )
        )


def test_invalid_lifecycle_transition_is_rejected_before_database_access():
    with pytest.raises(capability_catalog.InvalidLifecycleTransition):
        asyncio.run(
            capability_catalog.CapabilityCatalog.transition_status(
                CapabilityKind.TOOL,
                "summarize_content",
                "1.0.0",
                from_status=CapabilityStatus.DRAFT,
                to_status=CapabilityStatus.ACTIVE,
                actor_id="admin-user",
            )
        )


def test_required_approval_cannot_use_not_required_status():
    with pytest.raises(ValidationError, match="required approval"):
        ApprovalState(required=True, status=ApprovalStatus.NOT_REQUIRED)


class _FakeSeedCollection:
    def __init__(self):
        self.documents = {}

    async def update_one(self, query, update, upsert=False):
        key = query["_id"]
        inserted = key not in self.documents
        if inserted and upsert:
            self.documents[key] = dict(update["$setOnInsert"])
        return SimpleNamespace(upserted_id=key if inserted else None)

    async def find_one(self, query, projection=None):
        return self.documents.get(query.get("_id"))


def test_code_owned_seed_is_idempotent_and_does_not_overwrite(monkeypatch):
    collection = _FakeSeedCollection()
    monkeypatch.setattr(
        capability_catalog.CapabilityCatalog,
        "collection",
        staticmethod(lambda: collection),
    )
    record = _tool_record(status=CapabilityStatus.ACTIVE)

    first = asyncio.run(
        capability_catalog.CapabilityCatalog.seed_code_owned(
            record,
            implementation_ref="core.tools.summarize_content.SummarizeTool",
        )
    )
    stored_id = "capability:tool:summarize_content:1.0.0"
    collection.documents[stored_id]["status"] = CapabilityStatus.DEPRECATED.value

    second = asyncio.run(
        capability_catalog.CapabilityCatalog.seed_code_owned(
            record,
            implementation_ref="core.tools.summarize_content.SummarizeTool",
        )
    )

    assert first["status"] == CapabilityStatus.ACTIVE.value
    assert second["status"] == CapabilityStatus.DEPRECATED.value
    assert len(collection.documents) == 1


def test_approved_seed_is_not_runnable_and_has_no_activation_timestamp(monkeypatch):
    collection = _FakeSeedCollection()
    monkeypatch.setattr(
        capability_catalog.CapabilityCatalog,
        "collection",
        staticmethod(lambda: collection),
    )
    record = _tool_record(status=CapabilityStatus.APPROVED)

    stored = asyncio.run(
        capability_catalog.CapabilityCatalog.seed_code_owned(
            record,
            implementation_ref="core.tools.summarize_content.SummarizeTool",
        )
    )

    assert stored["status"] == CapabilityStatus.APPROVED.value
    assert stored["approved_at"] is not None
    assert stored["activated_at"] is None


def test_code_owned_seed_rejects_unreviewed_draft():
    with pytest.raises(
        capability_catalog.InvalidLifecycleTransition,
        match="approved or active",
    ):
        asyncio.run(
            capability_catalog.CapabilityCatalog.seed_code_owned(
                _tool_record(status=CapabilityStatus.DRAFT),
                implementation_ref="core.tools.summarize_content.SummarizeTool",
            )
        )


def test_baseline_seed_is_complete_and_references_approved_internal_server():
    records = build_code_owned_capabilities()
    keys = {(record.kind, record.capability_id) for record, _ in records}
    expected_tools = {
        "extract_data_from_file", "summarize_content", "generate_report",
        "web_search", "speech_to_text", "send_email", "mailbox_tracker_graph",
    }

    assert len(records) == 10
    assert (CapabilityKind.MCP_SERVER, "meridian_native_tools") in keys
    assert (CapabilityKind.POLICY, "agent_tool_assignment") in keys
    assert (CapabilityKind.POLICY, "external_write_approval") in keys
    assert {
        capability_id
        for kind, capability_id in keys
        if kind == CapabilityKind.TOOL
    } == expected_tools
    assert all(record.status == CapabilityStatus.APPROVED for record, _ in records)

    for record, implementation_ref in records:
        assert implementation_ref
        if record.kind != CapabilityKind.TOOL:
            continue
        spec = ToolDefinitionSpec.model_validate(record.spec)
        assert spec.execution_target.target_ref.capability_id == "meridian_native_tools"
        assert spec.execution_target.operation == record.capability_id


def test_write_capability_seeds_require_approval_policy():
    records = build_code_owned_capabilities()
    write_tools = []
    for record, _ in records:
        if record.kind != CapabilityKind.TOOL:
            continue
        spec = ToolDefinitionSpec.model_validate(record.spec)
        if spec.risk_level == RiskLevel.WRITE:
            write_tools.append(record.capability_id)
            assert any(
                ref.capability_id == "external_write_approval"
                for ref in spec.policy_refs
            )
            assert spec.max_attempts == 1

    assert set(write_tools) == {
        "generate_report", "send_email", "mailbox_tracker_graph"
    }


def test_pending_approval_requires_request_timestamp():
    with pytest.raises(ValidationError, match="requested_at"):
        ApprovalState(required=True, status=ApprovalStatus.PENDING)

    state = ApprovalState(
        required=True,
        status=ApprovalStatus.PENDING,
        requested_at=datetime.now(timezone.utc),
    )
    assert state.status == ApprovalStatus.PENDING


def test_runtime_tool_lookup_requires_an_exact_active_version(monkeypatch):
    class _LookupCollection:
        def __init__(self):
            self.query = None

        async def find_one(self, query, projection=None):
            self.query = query
            return None

    collection = _LookupCollection()
    monkeypatch.setattr(
        capability_catalog.CapabilityCatalog,
        "collection",
        staticmethod(lambda: collection),
    )
    with pytest.raises(capability_catalog.CapabilityNotFound):
        asyncio.run(
            capability_catalog.CapabilityCatalog.get_active_tool(
                ToolRef(tool_id="crm.create_ticket", version="1.0.0")
            )
        )
    assert collection.query == {
        "kind": "tool",
        "capability_id": "crm.create_ticket",
        "version": "1.0.0",
        "status": {"$in": ["active"]},
    }
