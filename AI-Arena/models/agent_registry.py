"""Validated API contracts for authenticated-user agent registrations."""

from typing import Literal, Optional

from pydantic import BaseModel, Field, HttpUrl, field_validator


class FoundryProviderConfig(BaseModel):
    endpoint: HttpUrl
    provider_agent_id: str = Field(min_length=3, max_length=200)

    @field_validator("provider_agent_id")
    @classmethod
    def normalize_provider_agent_id(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value


class RegistryAgentCreateRequest(BaseModel):
    agent_id: str = Field(min_length=3, max_length=80, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=1000)
    provider: Literal["azure_ai_foundry"] = "azure_ai_foundry"
    supports_files: Literal[False] = False
    tags: list[str] = Field(default_factory=list, max_length=20)
    provider_config: FoundryProviderConfig

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value

    @field_validator("description")
    @classmethod
    def normalize_description(cls, value: str) -> str:
        return value.strip()

    @field_validator("tags")
    @classmethod
    def normalize_tags(cls, values: list[str]) -> list[str]:
        normalized: list[str] = []
        for value in values:
            tag = value.strip().lower()
            if tag and len(tag) <= 50 and tag not in normalized:
                normalized.append(tag)
        return normalized


class RegistryAgentUpdateRequest(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    description: Optional[str] = Field(default=None, max_length=1000)
    tags: Optional[list[str]] = Field(default=None, max_length=20)
    provider_config: Optional[FoundryProviderConfig] = None

    @field_validator("name")
    @classmethod
    def normalize_optional_name(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value

    @field_validator("description")
    @classmethod
    def normalize_optional_description(cls, value: Optional[str]) -> Optional[str]:
        return value.strip() if value is not None else None

    @field_validator("tags")
    @classmethod
    def normalize_optional_tags(cls, values: Optional[list[str]]) -> Optional[list[str]]:
        if values is None:
            return None
        normalized: list[str] = []
        for value in values:
            tag = value.strip().lower()
            if tag and len(tag) <= 50 and tag not in normalized:
                normalized.append(tag)
        return normalized
