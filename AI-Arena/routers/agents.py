"""Unified catalog and execution endpoints for prebuilt and custom agents."""

import json
import os

from typing import Literal, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile, status
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from middleware.auth import get_current_user
from models.agent import (
    AgentBlueprintCreateRequest,
    AgentPreviewRequest,
    AgentResponse,
    AgentRunRequest,
    AgentRunResponse,
    AgentUpdateRequest,
)
from services.agent_service import (
    create_custom_agent_from_blueprint,
    clear_custom_agent_history,
    delete_custom_agent,
    export_custom_agent_blueprint,
    export_custom_agent_zip,
    get_custom_agent_config,
    get_custom_agent_context,
    get_custom_agent_runtime_metadata,
    get_agent_thread_messages,
    get_accessible_agent,
    list_agents,
    list_agent_threads,
    preview_custom_agent,
    run_agent,
    run_custom_agent_file,
    serialize_agent,
    update_custom_agent,
    update_custom_agent_config,
)


router = APIRouter(prefix="/api/agents", tags=["Agents"])


def _tenant_id(user: dict) -> str:
    return str(user.get("tenant_id") or user["_id"])


@router.post("/preview")
async def preview_agent(
    body: AgentPreviewRequest,
    current_user: dict = Depends(get_current_user),
):
    """Generate and validate a runtime blueprint without saving it."""
    return {
        "blueprint": await preview_custom_agent(
            body, current_user["_id"], _tenant_id(current_user)
        )
    }


@router.post("/blueprint", response_model=AgentResponse, status_code=status.HTTP_201_CREATED)
async def create_agent_from_blueprint(
    body: AgentBlueprintCreateRequest,
    current_user: dict = Depends(get_current_user),
):
    """Save a reviewed blueprint as a private custom agent."""
    return await create_custom_agent_from_blueprint(
        body.blueprint, current_user["_id"], _tenant_id(current_user)
    )


@router.get("", response_model=list[AgentResponse])
async def get_agents(
    agent_kind: Optional[Literal["prebuilt", "custom"]] = None,
    current_user: dict = Depends(get_current_user),
):
    """List public prebuilt agents and custom agents owned by the user."""
    return await list_agents(current_user["_id"], agent_kind)


@router.get("/{agent_id}", response_model=AgentResponse)
async def get_agent(
    agent_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Get an accessible agent; custom configuration is visible only to its owner."""
    agent = await get_accessible_agent(agent_id, current_user["_id"], include_inactive_owner=True)
    return serialize_agent(agent, current_user["_id"], include_config=True)


@router.patch("/{agent_id}", response_model=AgentResponse)
async def update_agent(
    agent_id: str,
    body: AgentUpdateRequest,
    current_user: dict = Depends(get_current_user),
):
    """Update a custom agent owned by the authenticated user."""
    return await update_custom_agent(
        agent_id, body, current_user["_id"], _tenant_id(current_user)
    )


@router.delete("/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_agent(
    agent_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Delete a custom agent owned by the authenticated user."""
    await delete_custom_agent(agent_id, current_user["_id"])
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{agent_id}/run", response_model=AgentRunResponse)
async def execute_agent(
    agent_id: str,
    body: AgentRunRequest,
    current_user: dict = Depends(get_current_user),
):
    """Execute either agent kind through a stable response contract."""
    return await run_agent(
        agent_id, body, current_user["_id"], _tenant_id(current_user)
    )


@router.get("/{agent_id}/threads")
async def get_threads(
    agent_id: str,
    limit: int = 100,
    current_user: dict = Depends(get_current_user),
):
    """List switchable conversations owned by the authenticated user."""
    return await list_agent_threads(agent_id, current_user["_id"], limit)


@router.get("/{agent_id}/threads/{thread_id}/messages")
async def get_thread_messages(
    agent_id: str,
    thread_id: str,
    limit: int = 100,
    current_user: dict = Depends(get_current_user),
):
    """Load one owned conversation for custom or supported prebuilt agents."""
    return await get_agent_thread_messages(
        agent_id,
        thread_id,
        current_user["_id"],
        limit,
    )


@router.post("/{agent_id}/run-file", response_model=AgentRunResponse)
async def execute_custom_agent_file(
    agent_id: str,
    file: UploadFile = File(...),
    message: str = Form("Analyze the uploaded file."),
    thread_id: Optional[str] = Form(None),
    chat_id: Optional[str] = Form(None),
    payload: str = Form("{}"),
    current_user: dict = Depends(get_current_user),
):
    """Upload a validated file and execute a file-capable custom agent."""
    try:
        parsed_payload = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="payload must be valid JSON") from exc
    if not isinstance(parsed_payload, dict):
        raise HTTPException(status_code=400, detail="payload must be a JSON object")
    return await run_custom_agent_file(
        agent_id,
        file,
        current_user["_id"],
        tenant_id=_tenant_id(current_user),
        message=message,
        thread_id=thread_id,
        chat_id=chat_id,
        payload=parsed_payload,
    )


@router.get("/{agent_id}/config")
async def get_agent_config(
    agent_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Return the complete editable configuration for an owned custom agent."""
    return {"agent_id": agent_id, "config": await get_custom_agent_config(agent_id, current_user["_id"])}


@router.patch("/{agent_id}/config")
async def update_agent_config(
    agent_id: str,
    body: dict,
    current_user: dict = Depends(get_current_user),
):
    """Validate and update advanced blueprint configuration."""
    config = await update_custom_agent_config(
        agent_id, body, current_user["_id"], _tenant_id(current_user)
    )
    return {"agent_id": agent_id, "config": config}


@router.delete("/{agent_id}/history")
async def clear_agent_history(
    agent_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Clear persisted threads, messages, summaries, vectors, and token history."""
    await clear_custom_agent_history(agent_id, current_user["_id"])
    return {"status": "success", "message": "Agent conversation history cleared"}


@router.get("/{agent_id}/context")
async def get_agent_context(
    agent_id: str,
    limit: int = 60,
    current_user: dict = Depends(get_current_user),
):
    """Return the latest custom-agent conversation context."""
    return await get_custom_agent_context(agent_id, current_user["_id"], limit)


@router.get("/{agent_id}/blackboard")
async def get_agent_blackboard(
    agent_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Return the latest shared orchestration blackboard."""
    return await get_custom_agent_runtime_metadata(agent_id, current_user["_id"], "blackboard")


@router.get("/{agent_id}/sub-agent-histories")
async def get_sub_agent_histories(
    agent_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Return isolated specialist-agent histories from the latest run."""
    return await get_custom_agent_runtime_metadata(
        agent_id, current_user["_id"], "sub_agent_histories"
    )


@router.get("/{agent_id}/export")
async def export_agent(
    agent_id: str,
    format: Literal["blueprint", "zip"] = "blueprint",
    current_user: dict = Depends(get_current_user),
):
    """Export an owned custom agent as JSON or a portable runtime ZIP."""
    if format == "blueprint":
        blueprint, filename = await export_custom_agent_blueprint(agent_id, current_user["_id"])
        return Response(
            content=json.dumps(blueprint, indent=2, default=str),
            media_type="application/json",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "Cache-Control": "no-store",
            },
        )
    zip_path, filename = await export_custom_agent_zip(agent_id, current_user["_id"])
    return FileResponse(
        zip_path,
        filename=filename,
        media_type="application/zip",
        headers={"Cache-Control": "no-store"},
        background=BackgroundTask(os.remove, zip_path),
    )
