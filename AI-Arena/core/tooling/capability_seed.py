"""Code-owned baseline metadata for the governed Capability Catalog.

Code-owned native tools are seeded as ``active`` because their implementation
ships with this application and is available immediately after startup. Remote
MCP connections still follow their own review and activation lifecycle.
"""

from __future__ import annotations

from typing import Any

from core.tooling.capability_catalog import CapabilityCatalog
from models.capability import (
    AuthenticationMode,
    AuthenticationSpec,
    CapabilityKind,
    CapabilityOwner,
    CapabilityRecord,
    CapabilityStatus,
    ExecutionTarget,
    ExecutionTargetKind,
    McpServerDefinitionSpec,
    McpServerKind,
    McpServerPurpose,
    McpSetupField,
    McpTemplateMaturity,
    McpTemplateTrust,
    McpTransport,
    PolicyDefinitionSpec,
    RiskLevel,
    ToolDefinitionSpec,
    VersionedCapabilityRef,
)

VERSION = "1.0.0"
OWNER = CapabilityOwner(team="agent-platform")
SERVER_ID = "meridian_native_tools"
SERVER_REF = VersionedCapabilityRef(capability_id=SERVER_ID, version=VERSION)
AGENT_ASSIGNMENT_POLICY_REF = VersionedCapabilityRef(
    capability_id="agent_tool_assignment", version=VERSION
)
WRITE_POLICY_REF = VersionedCapabilityRef(
    capability_id="external_write_approval", version=VERSION
)
OBSOLETE_PREBUILT_TOOL_IDS = {
    "audit_customer_call", "analyze_compliance_document", "generate_data_insights",
    "analyze_group_discussion", "analyze_invoice_finance", "answer_legal_question",
    "generate_job_description", "query_uploaded_dataset",
}


def _object_schema(
    properties: dict[str, Any], required: list[str] | None = None
) -> dict[str, Any]:
    schema: dict[str, Any] = {
        "type": "object",
        "properties": properties,
        "additionalProperties": False,
    }
    if required:
        schema["required"] = required
    return schema


def _string(description: str, **constraints: Any) -> dict[str, Any]:
    return {"type": "string", "description": description, **constraints}


def _tool(
    capability_id: str,
    name: str,
    description: str,
    category: str,
    implementation_ref: str,
    input_schema: dict[str, Any],
    *,
    risk: RiskLevel = RiskLevel.READ_ONLY,
    supports_files: bool = False,
    timeout: int = 60,
) -> tuple[CapabilityRecord, str]:
    policies = [AGENT_ASSIGNMENT_POLICY_REF]
    if risk in {RiskLevel.WRITE, RiskLevel.DESTRUCTIVE}:
        policies.append(WRITE_POLICY_REF)
    spec = ToolDefinitionSpec(
        category=category,
        risk_level=risk,
        input_schema=input_schema,
        output_schema=_object_schema(
            {
                "status": _string("Normalized result status"),
                "data": {"type": "object"},
                "artifacts": {"type": "array", "items": {"type": "object"}},
                "citations": {"type": "array", "items": {"type": "object"}},
            },
            ["status", "data"],
        ),
        execution_target=ExecutionTarget(
            kind=ExecutionTargetKind.NATIVE_MCP,
            target_ref=SERVER_REF,
            operation=capability_id,
        ),
        policy_refs=policies,
        supports_files=supports_files,
        idempotent=risk in {RiskLevel.READ_ONLY, RiskLevel.SENSITIVE_READ},
        timeout_seconds=timeout,
        max_attempts=1,
    )
    return (
        CapabilityRecord(
            kind=CapabilityKind.TOOL,
            capability_id=capability_id,
            version=VERSION,
            status=CapabilityStatus.ACTIVE,
            name=name,
            description=description,
            owner=OWNER,
            tags=["internal", "mcp", category],
            spec=spec.model_dump(mode="json"),
        ),
        implementation_ref,
    )


def build_code_owned_capabilities() -> list[tuple[CapabilityRecord, str]]:
    """Build deterministic baseline records without importing tool providers."""

    tool_names = [
        "extract_data_from_file", "summarize_content", "generate_report",
        "web_search", "speech_to_text", "send_email", "mailbox_tracker_graph",
    ]
    server = CapabilityRecord(
        kind=CapabilityKind.MCP_SERVER,
        capability_id=SERVER_ID,
        version=VERSION,
        status=CapabilityStatus.ACTIVE,
        name="Meridian Native Tools MCP Server",
        description="Application-owned MCP boundary for reusable custom-agent native tools.",
        owner=OWNER,
        tags=["internal", "mcp"],
        spec=McpServerDefinitionSpec(
            server_kind=McpServerKind.INTERNAL,
            transport=McpTransport.IN_PROCESS,
            authentication=AuthenticationSpec(mode=AuthenticationMode.NONE),
            allowed_tool_names=tool_names,
        ).model_dump(mode="json"),
    )
    assignment_policy = CapabilityRecord(
        kind=CapabilityKind.POLICY, capability_id="agent_tool_assignment", version=VERSION,
        status=CapabilityStatus.ACTIVE, name="Agent Tool Assignment",
        description="Requires the exact active tool version to be assigned to the current owned agent.",
        owner=OWNER, tags=["security", "agent"],
        spec=PolicyDefinitionSpec(agent_assignment_required=True, audit_required=True).model_dump(mode="json"),
    )
    write_policy = CapabilityRecord(
        kind=CapabilityKind.POLICY, capability_id="external_write_approval", version=VERSION,
        status=CapabilityStatus.ACTIVE, name="External Write Approval",
        description="Requires explicit approval before a capability changes an external system.",
        owner=OWNER, tags=["security", "approval"],
        spec=PolicyDefinitionSpec(requires_approval=True, agent_assignment_required=True, audit_required=True).model_dump(mode="json"),
    )
    records: list[tuple[CapabilityRecord, str]] = [
        (server, "core.mcp.native_server"),
        (assignment_policy, "core.policy.agent_tool_assignment"),
        (write_policy, "core.policy.external_write_approval"),
    ]
    records.extend([
        _tool("extract_data_from_file", "Extract Data from File", "Extract structured data from an authorized uploaded file.", "document", "core.tools.extract_data_from_file.FileExtractorTool", _object_schema({"file_path": _string("Broker-resolved authorized file path")}, ["file_path"]), risk=RiskLevel.SENSITIVE_READ, supports_files=True, timeout=180),
        # Local Ollama summarization can require more time for multi-source web
        # results. Keep this governed timeout aligned with OLLAMA_TIMEOUT_SECONDS.
        _tool("summarize_content", "Summarize Content", "Summarize supplied text.", "knowledge", "core.tools.summarize_content.SummarizeTool", _object_schema({"text": _string("Content to summarize", minLength=1)}, ["text"]), timeout=300),
        # Report generation only creates a local artifact and does not modify an
        # external system, so it must not inherit the external-write approval policy.
        _tool("generate_report", "Generate Report", "Generate a Markdown or PDF business report.", "document", "core.tools.generate_report.ReportGeneratorTool", _object_schema({"content": _string("Report source content"), "title": _string("Report title"), "format": {"type": "string", "enum": ["markdown", "pdf", "both"], "default": "markdown"}, "persona": {"type": ["object", "null"]}}, ["content", "title"]), risk=RiskLevel.READ_ONLY, timeout=180),
        _tool("web_search", "Web Search", "Search the public web or scrape an approved public URL.", "research", "core.tools.web_search.web_search", _object_schema({"query": _string("Search query"), "action": {"type": "string", "enum": ["search", "scrape"], "default": "search"}, "target_url": _string("Public URL for scrape mode"), "region": _string("Search region"), "max_results": {"type": "integer", "minimum": 1, "maximum": 50, "default": 8}, "checkin": _string("Check-in date"), "checkout": _string("Check-out date"), "strict_mode": {"type": "boolean", "default": True}, "evidence_depth": {"type": "integer", "minimum": 0, "maximum": 10, "default": 3}}), timeout=180),
        _tool("speech_to_text", "Speech to Text", "Transcribe an authorized uploaded audio file.", "media", "core.tools.speech_to_text.SpeechToTextTool", _object_schema({"file_path": _string("Broker-resolved authorized audio path")}, ["file_path"]), risk=RiskLevel.SENSITIVE_READ, supports_files=True, timeout=600),
        _tool("send_email", "Send Email", "Send an email through the configured provider.", "communication", "core.tools.send_email.EmailTool", _object_schema({"recipient": _string("Recipient email address"), "subject": _string("Email subject"), "body": _string("Email body")}, ["recipient", "subject", "body"]), risk=RiskLevel.WRITE, timeout=60),
        _tool("mailbox_tracker_graph", "Mailbox Tracker", "Read, search, or mark messages through Microsoft Graph.", "communication", "core.tools.mail_tracker.MailboxTrackerGraphTool", _object_schema({"action": {"type": "string", "enum": ["fetch_new", "search", "mark_read"]}, "subject_contains": _string("Subject filter"), "sender_domain": _string("Sender-domain filter"), "max_results": {"type": "integer", "minimum": 1, "maximum": 50}, "include_attachments": {"type": "boolean"}, "mark_as_read": {"type": "boolean"}, "message_id": _string("Message ID for mark_read"), "target_user": _string("Authorized mailbox")}), risk=RiskLevel.WRITE, supports_files=True, timeout=120),
    ])
    return records


# Designed and implemented by Rajadurai R.
def build_mcp_templates() -> list[tuple[CapabilityRecord, str]]:
    """Curated official remote-server templates; never executable themselves."""

    definitions = [
        (
            "template.github", "GitHub", "Connect repositories, issues and pull requests.",
            "development", "github", "https://api.githubcopilot.com/mcp/", AuthenticationMode.OAUTH2,
            McpTemplateMaturity.STABLE, "https://docs.github.com/en/copilot/customizing-copilot/extending-copilot-chat-with-mcp",
        ),
        (
            "template.notion", "Notion", "Search, read and update an authorized Notion workspace.",
            "knowledge", "notion", "https://mcp.notion.com/mcp", AuthenticationMode.OAUTH2,
            McpTemplateMaturity.STABLE, "https://developers.notion.com/guides/mcp/overview",
        ),
        (
            "template.atlassian", "Atlassian", "Connect Jira, Confluence and other authorized Atlassian apps.",
            "productivity", "atlassian", "https://mcp.atlassian.com/v2/mcp", AuthenticationMode.OAUTH2,
            McpTemplateMaturity.STABLE, "https://developer.atlassian.com/cloud/rovo-mcp/",
        ),
        (
            "template.microsoft-learn", "Microsoft Learn", "Search current official Microsoft documentation.",
            "documentation", "microsoft", "https://learn.microsoft.com/api/mcp", AuthenticationMode.NONE,
            McpTemplateMaturity.STABLE, "https://learn.microsoft.com/training/",
        ),
        (
            "template.google-drive", "Google Drive", "Search and work with authorized Google Drive files.",
            "documents", "google-drive", "https://drivemcp.googleapis.com/mcp/v1", AuthenticationMode.OAUTH2,
            McpTemplateMaturity.PREVIEW, "https://developers.google.com/workspace/drive/api/reference/mcp",
        ),
    ]
    records: list[tuple[CapabilityRecord, str]] = []
    for capability_id, name, description, category, icon, endpoint, auth_mode, maturity, docs in definitions:
        authentication = AuthenticationSpec(
            mode=auth_mode,
            deferred=auth_mode != AuthenticationMode.NONE,
        )
        fields = [
            McpSetupField(
                key="connection_name", label="Connection name", field_type="text",
                placeholder=f"My {name}",
            )
        ]
        records.append((
            CapabilityRecord(
                kind=CapabilityKind.MCP_SERVER,
                capability_id=capability_id,
                version=VERSION,
                status=CapabilityStatus.ACTIVE,
                name=name,
                description=description,
                owner=OWNER,
                tags=["template", "official", category],
                spec=McpServerDefinitionSpec(
                    purpose=McpServerPurpose.TEMPLATE,
                    server_kind=McpServerKind.EXTERNAL,
                    transport=McpTransport.STREAMABLE_HTTP,
                    endpoint_ref=endpoint,
                    authentication=authentication,
                    category=category,
                    icon=icon,
                    documentation_url=docs,
                    setup_fields=fields,
                    setup_instructions=[
                        f"Select Connect {name}.",
                        "Grant only the permissions required by your agent.",
                        "Review the discovered tools before adding them.",
                    ],
                    trust_level=McpTemplateTrust.OFFICIAL_VERIFIED,
                    maturity=maturity,
                ).model_dump(mode="json"),
            ),
            f"core.mcp.template.{capability_id.removeprefix('template.')}",
        ))
    return records


async def seed_code_owned_capabilities() -> None:
    """Insert baseline definitions without overwriting administrator changes."""

    await CapabilityCatalog.reject_obsolete_approved_seeds(OBSOLETE_PREBUILT_TOOL_IDS)
    await CapabilityCatalog.reject_obsolete_policy_seed("tenant_isolation")
    for record, implementation_ref in build_code_owned_capabilities():
        await CapabilityCatalog.seed_code_owned(
            record, implementation_ref=implementation_ref
        )
    for record, implementation_ref in build_mcp_templates():
        await CapabilityCatalog.seed_code_owned(
            record, implementation_ref=implementation_ref
        )
