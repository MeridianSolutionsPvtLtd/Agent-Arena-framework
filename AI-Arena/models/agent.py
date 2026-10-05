"""Schemas for the unified prebuilt and custom agent API."""

from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator
from models.capability import ToolRef


AgentKind = Literal["prebuilt", "custom"]
AgentStatus = Literal["active", "inactive", "draft"]


class AgentToolGovernance(BaseModel):
    """Owner-editable restrictions for one tool assigned to one agent."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    purpose: Optional[str] = Field(default=None, max_length=1000)
    usage_instruction: Optional[str] = Field(default=None, max_length=4000)
    confirmation_required: bool = False
    timeout_seconds: Optional[int] = Field(default=None, ge=1, le=3600)
    max_results: Optional[int] = Field(default=None, ge=1, le=10000)
    default_parameters: dict[str, Any] = Field(default_factory=dict)

    @field_validator("purpose", "usage_instruction")
    @classmethod
    def reject_blank_optional_text(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        if not value.strip():
            raise ValueError("must not be blank")
        return value.strip()


def _normalize_tools(values: list[str]) -> list[str]:
    normalized = []
    seen = set()
    for value in values:
        tool = value.strip()
        if tool and tool not in seen:
            seen.add(tool)
            normalized.append(tool)
    return normalized


class AgentPreviewRequest(BaseModel):
    query: str = Field(min_length=3, max_length=10000)
    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    conversation_history: str = Field(default="", max_length=20000)


class AgentBlueprintCreateRequest(BaseModel):
    blueprint: dict[str, Any]


class AgentUpdateRequest(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    description: Optional[str] = Field(default=None, max_length=1000)
    system_prompt: Optional[str] = Field(default=None, min_length=1, max_length=30000)
    tools: Optional[list[str]] = Field(default=None, max_length=50)
    tool_refs: Optional[list[ToolRef]] = Field(default=None, max_length=50)
    tool_governance: Optional[dict[str, AgentToolGovernance]] = None
    supports_files: Optional[bool] = None
    status: Optional[AgentStatus] = None
    config: Optional[dict[str, Any]] = None

    @field_validator("name", "system_prompt")
    @classmethod
    def strip_optional_required_text(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value

    @field_validator("tools")
    @classmethod
    def normalize_optional_tools(cls, values: Optional[list[str]]) -> Optional[list[str]]:
        if values is None:
            return None
        return _normalize_tools(values)


class AgentRunRequest(BaseModel):
    message: str = Field(min_length=1, max_length=50000)
    thread_id: Optional[str] = Field(default=None, max_length=200)
    chat_id: Optional[str] = Field(default=None, max_length=100)
    file_ids: Optional[list[str]] = Field(default=None, max_length=10)
    payload: dict[str, Any] = Field(default_factory=dict)

    @field_validator("message")
    @classmethod
    def strip_message(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value


class AgentResponse(BaseModel):
    id: str
    agent_id: str
    name: str
    description: str = ""
    agent_kind: AgentKind
    status: AgentStatus
    visibility: Literal["public", "private"]
    supports_files: bool = False
    tools: list[str] = Field(default_factory=list)
    tool_refs: list[ToolRef] = Field(default_factory=list)
    tool_governance: dict[str, AgentToolGovernance] = Field(default_factory=dict)
    tool_metadata: list[dict[str, Any]] = Field(default_factory=list)
    runtime_type: Optional[str] = None
    provider: Optional[str] = None
    tags: list[str] = Field(default_factory=list)
    is_owner: bool = False
    system_prompt: Optional[str] = None
    config: dict[str, Any] = Field(default_factory=dict)
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class AgentRunResponse(BaseModel):
    agent_id: str
    agent_kind: AgentKind
    status: Literal["success", "error", "pending_approval"]
    response: str
    thread_id: Optional[str] = None
    chat_id: Optional[str] = None
    run_id: Optional[str] = None
    tool_execution_id: Optional[str] = None
    approval_type: Optional[Literal["plan", "tool", "input"]] = None
    data: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
