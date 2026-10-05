"""Typed contracts for the governed tool and integration ecosystem.

These models define the boundary between Agent Builder, the Capability Catalog,
the Execution Broker, MCP servers, connectors, and engines.  They intentionally
contain no MongoDB or network logic so introducing them cannot change the
current agent runtime behaviour.
"""

from __future__ import annotations

import re
from datetime import datetime
from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError


_IDENTIFIER_RE = re.compile(r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$")
_SEMVER_RE = re.compile(
    r"^(0|[1-9]\d*)\."
    r"(0|[1-9]\d*)\."
    r"(0|[1-9]\d*)"
    r"(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
    r"(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$"
)
_MCP_TOOL_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,199}$")


def _validate_identifier(value: str, field_name: str) -> str:
    normalized = (value or "").strip().lower()
    if not _IDENTIFIER_RE.fullmatch(normalized):
        raise ValueError(
            f"{field_name} must start with a lowercase letter and contain only "
            "lowercase letters, digits, dots, underscores, or hyphens"
        )
    return normalized


def _validate_semver(value: str) -> str:
    normalized = (value or "").strip()
    if not _SEMVER_RE.fullmatch(normalized):
        raise ValueError("version must be a valid semantic version such as 1.0.0")
    return normalized


class StrictModel(BaseModel):
    """Base contract that rejects unknown fields at trust boundaries."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class CapabilityKind(str, Enum):
    TOOL = "tool"
    CONNECTOR = "connector"
    ENGINE = "engine"
    POLICY = "policy"
    MCP_SERVER = "mcp_server"
    DATASET = "dataset"
    MCP_TOOL_CANDIDATE = "mcp_tool_candidate"


class CapabilityStatus(str, Enum):
    DRAFT = "draft"
    REVIEW = "review"
    APPROVED = "approved"
    ACTIVE = "active"
    DEPRECATED = "deprecated"
    RETIRED = "retired"
    REJECTED = "rejected"


class RiskLevel(str, Enum):
    READ_ONLY = "read_only"
    SENSITIVE_READ = "sensitive_read"
    WRITE = "write"
    DESTRUCTIVE = "destructive"


class ExecutionTargetKind(str, Enum):
    NATIVE_MCP = "native_mcp"
    EXTERNAL_MCP = "external_mcp"
    CONNECTOR = "connector"
    ENGINE = "engine"


class ConnectorType(str, Enum):
    NATIVE = "native"
    SDK = "sdk"
    REST = "rest"
    MCP = "mcp"
    DATABASE = "database"


class AuthenticationMode(str, Enum):
    NONE = "none"
    API_KEY = "api_key"
    BEARER_TOKEN = "bearer_token"
    OAUTH2 = "oauth2"
    JWT = "jwt"
    CERTIFICATE = "certificate"


class EngineType(str, Enum):
    FEDERATION = "federation"
    KNOWLEDGE = "knowledge"
    WORKFLOW = "workflow"
    DOCUMENT = "document"


class McpServerKind(str, Enum):
    INTERNAL = "internal"
    EXTERNAL = "external"


class McpTransport(str, Enum):
    IN_PROCESS = "in_process"
    STREAMABLE_HTTP = "streamable_http"
    STDIO = "stdio"


class McpServerPurpose(str, Enum):
    TEMPLATE = "template"
    CONNECTION = "connection"


class McpTemplateTrust(str, Enum):
    OFFICIAL_VERIFIED = "official_verified"
    INTERNAL = "internal"


class McpTemplateMaturity(str, Enum):
    STABLE = "stable"
    PREVIEW = "preview"
    EXPERIMENTAL = "experimental"
    DEPRECATED = "deprecated"


class McpHealthStatus(str, Enum):
    UNKNOWN = "unknown"
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"
    AUTHENTICATION_FAILED = "authentication_failed"
    SCHEMA_CHANGED = "schema_changed"


class ToolResultStatus(str, Enum):
    SUCCESS = "success"
    ERROR = "error"
    PENDING_APPROVAL = "pending_approval"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


class PolicyDecisionType(str, Enum):
    ALLOW = "allow"
    DENY = "deny"
    APPROVAL_REQUIRED = "approval_required"


class ApprovalStatus(str, Enum):
    NOT_REQUIRED = "not_required"
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"


class ToolExecutionStatus(str, Enum):
    CREATED = "created"
    POLICY_CHECK = "policy_check"
    PENDING_APPROVAL = "pending_approval"
    RUNNING = "running"
    SUCCESS = "success"
    ERROR = "error"
    REJECTED = "rejected"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class CapabilityOwner(StrictModel):
    team: str = Field(min_length=1, max_length=120)
    contact: Optional[str] = Field(default=None, max_length=320)


class VersionedCapabilityRef(StrictModel):
    capability_id: str = Field(min_length=1, max_length=160)
    version: str = Field(min_length=5, max_length=80)

    @field_validator("capability_id")
    @classmethod
    def validate_capability_id(cls, value: str) -> str:
        return _validate_identifier(value, "capability_id")

    @field_validator("version")
    @classmethod
    def validate_version(cls, value: str) -> str:
        return _validate_semver(value)

    @property
    def key(self) -> str:
        return f"{self.capability_id}@{self.version}"


class ToolRef(StrictModel):
    tool_id: str = Field(min_length=1, max_length=160)
    version: str = Field(min_length=5, max_length=80)

    @field_validator("tool_id")
    @classmethod
    def validate_tool_id(cls, value: str) -> str:
        return _validate_identifier(value, "tool_id")

    @field_validator("version")
    @classmethod
    def validate_version(cls, value: str) -> str:
        return _validate_semver(value)

    @property
    def key(self) -> str:
        return f"{self.tool_id}@{self.version}"


class ExecutionTarget(StrictModel):
    kind: ExecutionTargetKind
    target_ref: VersionedCapabilityRef
    operation: str = Field(min_length=1, max_length=200)

    @field_validator("operation")
    @classmethod
    def validate_operation(cls, value: str) -> str:
        normalized = (value or "").strip()
        if not _MCP_TOOL_NAME_RE.fullmatch(normalized):
            raise ValueError("operation contains unsupported MCP tool-name characters")
        return normalized


# Designed and implemented by Rajadurai R.
class ToolBuilderMetadata(StrictModel):
    """Searchable guidance for Agent Builder; never used as an execution contract."""

    capabilities: list[str] = Field(default_factory=list, max_length=20)
    use_when: list[str] = Field(default_factory=list, max_length=20)
    avoid_when: list[str] = Field(default_factory=list, max_length=20)
    operation_type: str = Field(default="unknown", pattern=r"^(read|write|destructive|unknown)$")
    # Optional builder hint only. Runtime approval is decided by the catalog
    # ToolDefinitionSpec and AgentToolPolicy, never by generated metadata.
    requires_approval: Optional[bool] = None
    inference_source: Literal["generated", "trusted_annotation", "owner_reviewed"] = "generated"

    @field_validator("capabilities", "use_when", "avoid_when")
    @classmethod
    def normalize_guidance(cls, values: list[str]) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for value in values:
            item = (value or "").strip()
            if not item:
                raise ValueError("builder metadata values must not be blank")
            if len(item) > 500:
                raise ValueError("builder metadata value must not exceed 500 characters")
            key = item.casefold()
            if key not in seen:
                seen.add(key)
                normalized.append(item)
        return normalized


class ToolDefinitionSpec(StrictModel):
    category: str = Field(min_length=1, max_length=100)
    risk_level: RiskLevel
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    execution_target: ExecutionTarget
    policy_refs: list[VersionedCapabilityRef] = Field(default_factory=list, max_length=20)
    allowed_roles: list[str] = Field(default_factory=list, max_length=100)
    supports_files: bool = False
    idempotent: bool = False
    timeout_seconds: int = Field(default=60, ge=1, le=3600)
    max_attempts: int = Field(default=1, ge=1, le=5)
    requires_approval: bool = False
    builder_metadata: ToolBuilderMetadata = Field(default_factory=ToolBuilderMetadata)

    @field_validator("category")
    @classmethod
    def validate_category(cls, value: str) -> str:
        return _validate_identifier(value, "category")

    @field_validator("allowed_roles")
    @classmethod
    def normalize_roles(cls, values: list[str]) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for value in values:
            role = (value or "").strip()
            if not role:
                raise ValueError("allowed_roles must not contain blank values")
            if len(role) > 200:
                raise ValueError("allowed role must not exceed 200 characters")
            key = role.casefold()
            if key not in seen:
                seen.add(key)
                normalized.append(role)
        return normalized

    @model_validator(mode="after")
    def validate_retry_policy(self) -> "ToolDefinitionSpec":
        try:
            Draft202012Validator.check_schema(self.input_schema)
            Draft202012Validator.check_schema(self.output_schema)
        except SchemaError as exc:
            raise ValueError("tool input_schema and output_schema must be valid JSON Schema") from exc
        if self.max_attempts > 1 and not self.idempotent:
            raise ValueError("non-idempotent tools cannot enable automatic retries")
        if self.risk_level in {RiskLevel.WRITE, RiskLevel.DESTRUCTIVE} and self.max_attempts > 1:
            raise ValueError("write or destructive tools cannot enable automatic retries")
        return self


# Designed and implemented by Rajadurai R.
# Catalog documents contain references only; secret material lives in a provider.
class AuthenticationSpec(StrictModel):
    mode: AuthenticationMode
    secret_ref: Optional[str] = Field(default=None, max_length=500)
    scopes: list[str] = Field(default_factory=list, max_length=100)
    deferred: bool = False

    @model_validator(mode="after")
    def validate_secret_reference(self) -> "AuthenticationSpec":
        modes_using_secrets = {
            AuthenticationMode.API_KEY,
            AuthenticationMode.BEARER_TOKEN,
            AuthenticationMode.OAUTH2,
            AuthenticationMode.JWT,
            AuthenticationMode.CERTIFICATE,
        }
        if self.mode in modes_using_secrets and not self.secret_ref and not self.deferred:
            raise ValueError(f"{self.mode.value} authentication requires secret_ref")
        if self.mode == AuthenticationMode.NONE and (self.secret_ref or self.deferred):
            raise ValueError(f"{self.mode.value} authentication must not contain secret_ref")
        return self


class ConnectorDefinitionSpec(StrictModel):
    connector_type: ConnectorType
    provider: str = Field(min_length=1, max_length=160)
    authentication: AuthenticationSpec
    endpoint_ref: Optional[str] = Field(default=None, max_length=2048)
    network_profile: str = Field(default="private", min_length=1, max_length=100)
    non_secret_config: dict[str, Any] = Field(default_factory=dict)

    @field_validator("provider", "network_profile")
    @classmethod
    def validate_identifiers(cls, value: str, info: Any) -> str:
        return _validate_identifier(value, info.field_name)

    @model_validator(mode="after")
    def reject_deferred_authentication(self) -> "ConnectorDefinitionSpec":
        if self.authentication.deferred:
            raise ValueError("connector authentication cannot be deferred")
        return self


class EngineDefinitionSpec(StrictModel):
    engine_type: EngineType
    implementation: str = Field(min_length=1, max_length=500)
    policy_refs: list[VersionedCapabilityRef] = Field(default_factory=list, max_length=20)
    authentication: AuthenticationSpec = Field(
        default_factory=lambda: AuthenticationSpec(mode=AuthenticationMode.NONE)
    )
    non_secret_config: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def reject_deferred_authentication(self) -> "EngineDefinitionSpec":
        if self.authentication.deferred:
            raise ValueError("engine authentication cannot be deferred")
        return self


class PolicyDefinitionSpec(StrictModel):
    requires_approval: bool = False
    allowed_roles: list[str] = Field(default_factory=list, max_length=100)
    required_scopes: list[str] = Field(default_factory=list, max_length=100)
    agent_assignment_required: bool = True
    audit_required: bool = True
    max_requests_per_minute: Optional[int] = Field(default=None, ge=1, le=1_000_000)
    rules: dict[str, Any] = Field(default_factory=dict)


# Designed and implemented by Rajadurai R.
class McpSetupField(StrictModel):
    key: str = Field(min_length=1, max_length=100, pattern=r"^[a-z][a-z0-9_]*$")
    label: str = Field(min_length=1, max_length=160)
    field_type: Literal["text", "url", "password"]
    required: bool = True
    secret: bool = False
    placeholder: Optional[str] = Field(default=None, max_length=500)
    help_text: Optional[str] = Field(default=None, max_length=1000)


# Designed and implemented by Rajadurai R.
# One model represents non-executable templates and owner-scoped live connections.
class McpServerDefinitionSpec(StrictModel):
    purpose: McpServerPurpose = McpServerPurpose.CONNECTION
    server_kind: McpServerKind
    transport: McpTransport
    endpoint_ref: Optional[str] = Field(default=None, max_length=2048)
    package_ref: Optional[str] = Field(default=None, max_length=1000)
    authentication: AuthenticationSpec
    api_center_asset_id: Optional[str] = Field(default=None, max_length=500)
    allowed_tool_names: list[str] = Field(default_factory=list, max_length=500)
    template_ref: Optional[VersionedCapabilityRef] = None
    category: Optional[str] = Field(default=None, max_length=100)
    icon: Optional[str] = Field(default=None, max_length=100)
    documentation_url: Optional[str] = Field(default=None, max_length=2048)
    setup_fields: list[McpSetupField] = Field(default_factory=list, max_length=20)
    setup_instructions: list[str] = Field(default_factory=list, max_length=20)
    trust_level: Optional[McpTemplateTrust] = None
    maturity: Optional[McpTemplateMaturity] = None
    oauth_client_key: Optional[str] = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]{1,60}$")
    endpoint_fingerprint: Optional[str] = Field(
        default=None, min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$"
    )
    @field_validator("allowed_tool_names")
    @classmethod
    def validate_tool_names(cls, values: list[str]) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for value in values:
            name = (value or "").strip()
            if not _MCP_TOOL_NAME_RE.fullmatch(name):
                raise ValueError("allowed_tool_name contains unsupported characters")
            if name not in seen:
                seen.add(name)
                normalized.append(name)
        return normalized

    @model_validator(mode="after")
    def validate_transport_location(self) -> "McpServerDefinitionSpec":
        if self.purpose == McpServerPurpose.TEMPLATE:
            authenticated = self.authentication.mode != AuthenticationMode.NONE
            if self.authentication.secret_ref or (authenticated and not self.authentication.deferred):
                raise ValueError("MCP templates must defer authenticated credentials")
            if self.template_ref or self.endpoint_fingerprint or self.allowed_tool_names:
                raise ValueError("MCP templates cannot contain connection state")
            if not self.trust_level or not self.maturity:
                raise ValueError("MCP templates require trust and maturity metadata")
            # OAuth client registration is discovered at connection time. The
            # legacy oauth_client_key remains readable for existing records but
            # is no longer required or used by new templates.
        elif self.authentication.deferred:
            raise ValueError("MCP connections cannot defer authentication")
        elif self.oauth_client_key:
            raise ValueError("oauth_client_key is only valid for MCP templates")
        if (
            self.purpose == McpServerPurpose.CONNECTION
            and self.transport == McpTransport.STREAMABLE_HTTP
            and not self.endpoint_ref
        ):
            raise ValueError("streamable_http MCP servers require endpoint_ref")
        if self.transport == McpTransport.STDIO and not self.package_ref:
            raise ValueError("stdio MCP servers require package_ref")
        if self.server_kind == McpServerKind.EXTERNAL and self.transport != McpTransport.STREAMABLE_HTTP:
            raise ValueError("external MCP servers must use streamable_http")
        if self.transport == McpTransport.IN_PROCESS and self.server_kind != McpServerKind.INTERNAL:
            raise ValueError("in_process MCP servers must be internal")
        return self


class PhysicalDatasetSource(StrictModel):
    catalog: str = Field(min_length=1, max_length=160)
    schema_name: str = Field(min_length=1, max_length=160)
    table: str = Field(min_length=1, max_length=160)

    @field_validator("catalog", "schema_name", "table")
    @classmethod
    def validate_source_names(cls, value: str, info: Any) -> str:
        return _validate_identifier(value, info.field_name)


class DatasetDefinitionSpec(StrictModel):
    engine_ref: VersionedCapabilityRef
    physical_source: PhysicalDatasetSource
    allowed_columns: list[str] = Field(min_length=1, max_length=1000)
    restricted_columns: list[str] = Field(default_factory=list, max_length=1000)
    tenant_filter_column: Optional[str] = Field(default=None, max_length=160)
    policy_refs: list[VersionedCapabilityRef] = Field(default_factory=list, max_length=20)

    @field_validator("allowed_columns", "restricted_columns")
    @classmethod
    def validate_columns(cls, values: list[str]) -> list[str]:
        normalized = [_validate_identifier(value, "column") for value in values]
        if len(normalized) != len(set(normalized)):
            raise ValueError("column lists must not contain duplicates")
        return normalized

    @field_validator("tenant_filter_column")
    @classmethod
    def validate_tenant_column(cls, value: Optional[str]) -> Optional[str]:
        return _validate_identifier(value, "tenant_filter_column") if value else None

    @model_validator(mode="after")
    def validate_column_boundaries(self) -> "DatasetDefinitionSpec":
        overlap = set(self.allowed_columns) & set(self.restricted_columns)
        if overlap:
            raise ValueError(f"columns cannot be both allowed and restricted: {sorted(overlap)}")
        if self.tenant_filter_column and self.tenant_filter_column in self.restricted_columns:
            raise ValueError("tenant_filter_column cannot be restricted")
        return self


# Designed and implemented by Rajadurai R.
# Candidates remain untrusted until the owner explicitly selects them.
class McpToolCandidateSpec(StrictModel):
    mcp_server_ref: VersionedCapabilityRef
    remote_tool_name: str = Field(min_length=1, max_length=200)
    remote_description: str = Field(default="", max_length=4000)
    input_schema: dict[str, Any]
    output_schema: dict[str, Any] = Field(default_factory=dict)
    schema_hash: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")
    suggested_risk_level: RiskLevel
    builder_metadata: ToolBuilderMetadata = Field(default_factory=ToolBuilderMetadata)
    discovered_at: datetime


class CapabilitySource(StrictModel):
    """Trace an imported capability to an enterprise control-plane asset."""

    provider: str = Field(min_length=1, max_length=80)
    asset_id: str = Field(min_length=1, max_length=500)
    asset_version: Optional[str] = Field(default=None, max_length=200)
    metadata_hash: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")
    synchronized_at: datetime

    @field_validator("provider")
    @classmethod
    def validate_provider(cls, value: str) -> str:
        return _validate_identifier(value, "provider")


# Designed and implemented by Rajadurai R.
class McpRuntimeHealth(StrictModel):
    """Latest safe operational snapshot for one registered MCP server."""

    status: McpHealthStatus = McpHealthStatus.UNKNOWN
    checked_at: datetime
    last_success_at: Optional[datetime] = None
    response_time_ms: Optional[int] = Field(default=None, ge=0)
    protocol_version: Optional[str] = Field(default=None, max_length=100)
    discovered_tool_count: int = Field(default=0, ge=0, le=10_000)
    schema_fingerprint: Optional[str] = Field(
        default=None, min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$"
    )
    consecutive_failures: int = Field(default=0, ge=0)
    last_error_code: Optional[str] = Field(default=None, max_length=120)


class CapabilityRecord(StrictModel):
    kind: CapabilityKind
    capability_id: str = Field(min_length=1, max_length=160)
    version: str = Field(min_length=5, max_length=80)
    status: CapabilityStatus = CapabilityStatus.DRAFT
    name: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=4000)
    owner: CapabilityOwner
    tags: list[str] = Field(default_factory=list, max_length=50)
    source: Optional[CapabilitySource] = None
    runtime_health: Optional[McpRuntimeHealth] = None
    spec: dict[str, Any]
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    approved_at: Optional[datetime] = None
    activated_at: Optional[datetime] = None

    @field_validator("capability_id")
    @classmethod
    def validate_capability_id(cls, value: str) -> str:
        return _validate_identifier(value, "capability_id")

    @field_validator("version")
    @classmethod
    def validate_version(cls, value: str) -> str:
        return _validate_semver(value)

    @field_validator("tags")
    @classmethod
    def normalize_tags(cls, values: list[str]) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for value in values:
            tag = _validate_identifier(value, "tag")
            if tag not in seen:
                seen.add(tag)
                normalized.append(tag)
        return normalized

    @model_validator(mode="after")
    def validate_kind_specific_spec(self) -> "CapabilityRecord":
        spec_models: dict[CapabilityKind, type[StrictModel]] = {
            CapabilityKind.TOOL: ToolDefinitionSpec,
            CapabilityKind.CONNECTOR: ConnectorDefinitionSpec,
            CapabilityKind.ENGINE: EngineDefinitionSpec,
            CapabilityKind.POLICY: PolicyDefinitionSpec,
            CapabilityKind.MCP_SERVER: McpServerDefinitionSpec,
            CapabilityKind.DATASET: DatasetDefinitionSpec,
            CapabilityKind.MCP_TOOL_CANDIDATE: McpToolCandidateSpec,
        }
        spec_models[self.kind].model_validate(self.spec)
        if self.runtime_health is not None and self.kind != CapabilityKind.MCP_SERVER:
            raise ValueError("runtime_health is only valid for MCP server capabilities")
        return self

    @property
    def key(self) -> str:
        return f"{self.kind.value}:{self.capability_id}@{self.version}"


class ExecutionContext(StrictModel):
    user_id: str = Field(min_length=1, max_length=200)
    tenant_id: str = Field(min_length=1, max_length=200)
    agent_id: str = Field(min_length=1, max_length=200)
    role: str = Field(min_length=1, max_length=200)
    trace_id: str = Field(min_length=1, max_length=200)
    agent_run_id: Optional[str] = Field(default=None, max_length=200)
    thread_id: Optional[str] = Field(default=None, max_length=200)
    file_ids: list[str] = Field(default_factory=list, max_length=20)
    scopes: list[str] = Field(default_factory=list, max_length=100)

    @field_validator("file_ids", "scopes")
    @classmethod
    def reject_blank_list_values(cls, values: list[str]) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for value in values:
            item = (value or "").strip()
            if not item:
                raise ValueError("list values must not be blank")
            if item not in seen:
                seen.add(item)
                normalized.append(item)
        return normalized


class ArtifactRef(StrictModel):
    artifact_id: str = Field(min_length=1, max_length=200)
    name: str = Field(min_length=1, max_length=255)
    media_type: Optional[str] = Field(default=None, max_length=200)
    size_bytes: Optional[int] = Field(default=None, ge=0)


class CitationRef(StrictModel):
    source_id: str = Field(min_length=1, max_length=500)
    label: Optional[str] = Field(default=None, max_length=500)
    uri: Optional[str] = Field(default=None, max_length=2048)


class ToolError(StrictModel):
    code: str = Field(min_length=1, max_length=120)
    message: str = Field(min_length=1, max_length=2000)
    retryable: bool = False
    trace_id: Optional[str] = Field(default=None, max_length=200)


class ToolResult(StrictModel):
    status: ToolResultStatus
    data: dict[str, Any] = Field(default_factory=dict)
    artifacts: list[ArtifactRef] = Field(default_factory=list, max_length=100)
    citations: list[CitationRef] = Field(default_factory=list, max_length=200)
    metadata: dict[str, Any] = Field(default_factory=dict)
    trace_id: str = Field(min_length=1, max_length=200)
    tool_execution_id: Optional[str] = Field(default=None, max_length=200)
    error: Optional[ToolError] = None

    @model_validator(mode="after")
    def validate_error_contract(self) -> "ToolResult":
        if self.status == ToolResultStatus.ERROR and self.error is None:
            raise ValueError("error details are required when status is error")
        if self.status == ToolResultStatus.SUCCESS and self.error is not None:
            raise ValueError("successful results cannot contain an error")
        return self


class PolicyDecision(StrictModel):
    decision: PolicyDecisionType
    policy_refs: list[VersionedCapabilityRef] = Field(default_factory=list, max_length=20)
    reason: str = Field(default="", max_length=2000)
    evaluated_at: datetime


class ApprovalDecisionRequest(StrictModel):
    decision: ApprovalStatus
    reason: Optional[str] = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def validate_decision(self) -> "ApprovalDecisionRequest":
        if self.decision not in {ApprovalStatus.APPROVED, ApprovalStatus.REJECTED}:
            raise ValueError("decision must be approved or rejected")
        return self


class ApprovalState(StrictModel):
    required: bool = False
    status: ApprovalStatus = ApprovalStatus.NOT_REQUIRED
    requested_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    decided_at: Optional[datetime] = None
    decided_by: Optional[str] = Field(default=None, max_length=200)
    reason: Optional[str] = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def validate_state(self) -> "ApprovalState":
        if self.required and self.status == ApprovalStatus.NOT_REQUIRED:
            raise ValueError("required approval cannot have not_required status")
        if not self.required and self.status != ApprovalStatus.NOT_REQUIRED:
            raise ValueError("optional approval must have not_required status")
        if self.status == ApprovalStatus.PENDING and self.requested_at is None:
            raise ValueError("pending approval requires requested_at")
        if self.expires_at and self.requested_at and self.expires_at <= self.requested_at:
            raise ValueError("expires_at must be later than requested_at")
        return self


class ToolExecutionResponse(StrictModel):
    tool_execution_id: str = Field(min_length=1, max_length=200)
    agent_run_id: Optional[str] = Field(default=None, max_length=200)
    trace_id: str = Field(min_length=1, max_length=200)
    tool_ref: ToolRef
    status: ToolExecutionStatus
    approval: ApprovalState = Field(default_factory=ApprovalState)
    result: Optional[ToolResult] = None
    created_at: datetime
    updated_at: datetime
    completed_at: Optional[datetime] = None

    @model_validator(mode="after")
    def validate_completion(self) -> "ToolExecutionResponse":
        terminal = {
            ToolExecutionStatus.SUCCESS,
            ToolExecutionStatus.ERROR,
            ToolExecutionStatus.REJECTED,
            ToolExecutionStatus.EXPIRED,
            ToolExecutionStatus.CANCELLED,
        }
        if self.status in terminal and self.completed_at is None:
            raise ValueError("terminal executions require completed_at")
        return self
