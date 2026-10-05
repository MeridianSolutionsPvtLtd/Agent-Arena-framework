"""Agent-level tool assignment and stricter-only governance enforcement."""

from __future__ import annotations

from typing import Any

from pymongo.errors import PyMongoError
from jsonschema import Draft202012Validator

from database import get_db
from models.agent import AgentToolGovernance
from models.capability import ExecutionContext, ToolDefinitionSpec, ToolRef


class AgentToolPolicyError(RuntimeError):
    pass


class AgentToolNotAssigned(AgentToolPolicyError):
    pass


_FORBIDDEN_DEFAULT_KEYS = {
    "access_token", "agent_id", "api_key", "client_secret", "credentials",
    "password", "private_key", "refresh_token", "role", "scopes", "secret",
    "tenant_id", "token", "trace_id", "user_id",
}


# Designed and implemented by Rajadurai R.
# Re-read saved ownership and assignment instead of trusting planner-provided state.
class AgentToolPolicy:
    """Resolve the current saved assignment instead of trusting planner state."""

    @staticmethod
    def collection():
        db = get_db()
        if db is None:
            raise AgentToolPolicyError("Agent assignment store is unavailable")
        return db["agents"]

    @classmethod
    async def resolve(
        cls, context: ExecutionContext, tool_ref: ToolRef
    ) -> AgentToolGovernance:
        try:
            agent = await cls.collection().find_one(
                {
                    "agent_id": context.agent_id,
                    "agent_kind": "custom",
                    "status": "active",
                    "user_id": context.user_id,
                    "tool_refs": {
                        "$elemMatch": {
                            "tool_id": tool_ref.tool_id,
                            "version": tool_ref.version,
                        }
                    },
                },
                {"tool_governance": 1},
            )
        except PyMongoError as exc:
            raise AgentToolPolicyError("Agent assignment lookup failed") from exc
        if agent is None:
            raise AgentToolNotAssigned("Tool is not assigned to the current agent")
        raw = (agent.get("tool_governance") or {}).get(tool_ref.tool_id) or {}
        return AgentToolGovernance.model_validate(raw)

    @staticmethod
    def validate_governance(
        governance: AgentToolGovernance, spec: ToolDefinitionSpec
    ) -> None:
        if governance.timeout_seconds is not None and governance.timeout_seconds > spec.timeout_seconds:
            raise ValueError("Agent tool timeout cannot exceed the platform maximum")
        defaults = governance.default_parameters
        lowered = {str(key).strip().lower() for key in defaults}
        if lowered & _FORBIDDEN_DEFAULT_KEYS:
            raise ValueError("Agent tool defaults cannot contain identity or credential fields")
        properties = spec.input_schema.get("properties") or {}
        if not isinstance(properties, dict):
            properties = {}
        unknown = sorted(set(defaults) - set(properties))
        if unknown:
            raise ValueError("Agent tool defaults contain fields outside the approved schema")
        if governance.max_results is not None and "max_results" not in properties:
            raise ValueError(
                "Agent max_results requires an approved max_results tool argument"
            )
        for key, value in defaults.items():
            if list(Draft202012Validator(properties[key]).iter_errors(value)):
                raise ValueError("Agent tool default does not match the approved schema")

    @staticmethod
    def effective_spec(
        spec: ToolDefinitionSpec, governance: AgentToolGovernance
    ) -> ToolDefinitionSpec:
        timeout = (
            min(spec.timeout_seconds, governance.timeout_seconds)
            if governance.timeout_seconds is not None
            else spec.timeout_seconds
        )
        return spec.model_copy(update={"timeout_seconds": timeout})

    @staticmethod
    def effective_arguments(
        arguments: dict[str, Any],
        governance: AgentToolGovernance,
        spec: ToolDefinitionSpec,
    ) -> dict[str, Any]:
        merged = {**governance.default_parameters, **arguments}
        if governance.max_results is not None and "max_results" in (
            spec.input_schema.get("properties") or {}
        ):
            supplied = merged.get("max_results")
            if supplied is None:
                merged["max_results"] = governance.max_results
            elif isinstance(supplied, int) and not isinstance(supplied, bool):
                merged["max_results"] = min(supplied, governance.max_results)
        return merged
