"""Authenticated user lifecycle API for dynamically registered agents."""

from fastapi import APIRouter, Depends, Response, status

from middleware.auth import get_current_user
from models.agent_registry import (
    RegistryAgentCreateRequest,
    RegistryAgentUpdateRequest,
)
from services.agent_registry_service import (
    get_registered_agent,
    list_registered_agents,
    record_connection_test,
    register_agent,
    serialize_registry_agent,
    set_registered_agent_status,
    update_registered_agent,
)
from services.registered_agent_service import test_registered_foundry_agent


router = APIRouter(prefix="/api/agent-registry", tags=["Agent Registry"])


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_registry_agent(
    body: RegistryAgentCreateRequest,
    current_user: dict = Depends(get_current_user),
):
    """Create a draft registration; activation requires a successful test."""
    return await register_agent(body, current_user["_id"])


@router.get("")
async def get_registry_agents(
    limit: int = 200,
    current_user: dict = Depends(get_current_user),
):
    return await list_registered_agents(current_user["_id"], limit)


@router.get("/{agent_id}")
async def get_registry_agent(
    agent_id: str,
    current_user: dict = Depends(get_current_user),
):
    return serialize_registry_agent(
        await get_registered_agent(agent_id, current_user["_id"])
    )


@router.patch("/{agent_id}")
async def patch_registry_agent(
    agent_id: str,
    body: RegistryAgentUpdateRequest,
    current_user: dict = Depends(get_current_user),
):
    return await update_registered_agent(agent_id, body, current_user["_id"])


@router.post("/{agent_id}/test")
async def test_registry_agent(
    agent_id: str,
    current_user: dict = Depends(get_current_user),
):
    agent = await get_registered_agent(agent_id, current_user["_id"])
    try:
        result = await test_registered_foundry_agent(agent)
    except Exception as exc:
        await record_connection_test(
            agent_id,
            current_user["_id"],
            success=False,
            error_code=type(exc).__name__,
        )
        raise
    test = await record_connection_test(
        agent_id, current_user["_id"], success=True, **result
    )
    return {"agent_id": agent_id, "connection_test": test}


@router.post("/{agent_id}/activate")
async def activate_registry_agent(
    agent_id: str,
    current_user: dict = Depends(get_current_user),
):
    return await set_registered_agent_status(
        agent_id, "active", current_user["_id"]
    )


@router.post("/{agent_id}/deactivate")
async def deactivate_registry_agent(
    agent_id: str,
    current_user: dict = Depends(get_current_user),
):
    return await set_registered_agent_status(
        agent_id, "inactive", current_user["_id"]
    )


@router.delete("/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_registry_agent(
    agent_id: str,
    current_user: dict = Depends(get_current_user),
):
    # Registry deletion is intentionally recoverable: historical runs retain
    # their foreign identifier and the registration becomes inactive.
    await set_registered_agent_status(
        agent_id, "inactive", current_user["_id"]
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
