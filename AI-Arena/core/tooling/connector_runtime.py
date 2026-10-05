"""Fail-closed adapter registry for future SDK/REST/native connectors."""

from __future__ import annotations

from typing import Any, Protocol

from models.capability import ConnectorDefinitionSpec, ExecutionContext, ToolResult


class ConnectorAdapter(Protocol):
    async def execute(
        self,
        operation: str,
        arguments: dict[str, Any],
        context: ExecutionContext,
        connector: ConnectorDefinitionSpec,
    ) -> ToolResult: ...


class ConnectorRuntime:
    _adapters: dict[str, ConnectorAdapter] = {}

    @classmethod
    def register(cls, connector_id: str, version: str, adapter: ConnectorAdapter) -> None:
        key = f"{connector_id}@{version}"
        if key in cls._adapters:
            raise ValueError(f"Connector adapter is already registered: {key}")
        cls._adapters[key] = adapter

    @classmethod
    async def execute(
        cls,
        connector_id: str,
        version: str,
        operation: str,
        arguments: dict[str, Any],
        context: ExecutionContext,
        connector: ConnectorDefinitionSpec,
    ) -> ToolResult:
        adapter = cls._adapters.get(f"{connector_id}@{version}")
        if adapter is None:
            raise RuntimeError("Approved connector has no deployed runtime adapter")
        return await adapter.execute(operation, arguments, context, connector)
