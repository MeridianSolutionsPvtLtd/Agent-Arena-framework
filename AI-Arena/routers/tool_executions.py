"""Owned tool-execution audit and approval endpoints."""

from fastapi import APIRouter, Depends, HTTPException

from core.tooling.tool_execution_store import (
    ToolExecutionConflict,
    ToolExecutionNotFound,
    ToolExecutionStore,
    ToolExecutionStoreError,
)
from middleware.auth import get_current_user
from models.capability import ApprovalDecisionRequest
from models.capability import ExecutionContext
from core.tooling.execution_broker import ExecutionBroker
from core.orchestration.executor import AgentExecutor
from core.persistence.runtime_store import AgentRuntimeStore
from database import get_db
from bson import ObjectId
from datetime import datetime, timezone


router = APIRouter(prefix="/api/tool-executions", tags=["Tool Executions"])


def _identity(user: dict) -> tuple[str, str]:
    user_id = str(user.get("_id") or "")
    tenant_id = str(user.get("tenant_id") or user_id)
    return user_id, tenant_id


def _safe(document: dict) -> dict:
    result = dict(document)
    result.pop("_id", None)
    result.pop("input_hash", None)
    result.pop("scopes", None)
    result.pop("payload_ciphertext", None)
    result.pop("continuation_ciphertext", None)
    return result


def _error(exc: Exception) -> HTTPException:
    if isinstance(exc, ToolExecutionNotFound):
        return HTTPException(status_code=404, detail="Tool execution was not found")
    if isinstance(exc, ToolExecutionConflict):
        return HTTPException(status_code=409, detail=str(exc))
    return HTTPException(status_code=503, detail="Tool execution store is unavailable")


@router.get("/{execution_id}")
async def get_tool_execution(
    execution_id: str,
    current_user: dict = Depends(get_current_user),
):
    user_id, tenant_id = _identity(current_user)
    try:
        return _safe(await ToolExecutionStore.get_owned(execution_id, user_id, tenant_id))
    except (ToolExecutionNotFound, ToolExecutionStoreError) as exc:
        raise _error(exc) from exc


@router.post("/{execution_id}/approval")
async def decide_tool_execution(
    execution_id: str,
    body: ApprovalDecisionRequest,
    current_user: dict = Depends(get_current_user),
):
    user_id, tenant_id = _identity(current_user)
    try:
        document = await ToolExecutionStore.decide_approval(
            execution_id,
            user_id=user_id,
            tenant_id=tenant_id,
            decision=body.decision,
            reason=body.reason,
        )
        return _safe(document)
    except (ToolExecutionNotFound, ToolExecutionConflict, ToolExecutionStoreError) as exc:
        raise _error(exc) from exc


@router.post("/{execution_id}/resume")
async def resume_tool_execution(
    execution_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Resume an owned approved execution using its encrypted original payload."""
    user_id, tenant_id = _identity(current_user)
    try:
        execution = await ToolExecutionStore.get_owned(execution_id, user_id, tenant_id)
        continuation = ToolExecutionStore.decrypt_continuation(execution)
        context = ExecutionContext(
            user_id=user_id,
            tenant_id=tenant_id,
            agent_id=execution["agent_id"],
            role=execution["role"],
            trace_id=execution["trace_id"],
            agent_run_id=execution.get("agent_run_id"),
            thread_id=execution.get("thread_id"),
            file_ids=execution.get("file_ids") or [],
            scopes=execution.get("scopes") or [],
        )
        tool_result = await ExecutionBroker.resume_approved(
            execution_id, None, context
        )
        if not continuation:
            return tool_result

        # Continue the original custom-agent run from its encrypted checkpoint.
        # The provider result is injected as data; the LLM never chooses a new
        # tool identifier during this hand-off.
        agent_id = execution["agent_id"]
        from services.agent_service import get_accessible_agent
        agent = await get_accessible_agent(agent_id, user_id, include_inactive_owner=True)
        pending_step = continuation.get("pending_step") or {}
        blackboard = dict(continuation.get("blackboard") or {})
        blackboard.pop("pending_tool_execution_id", None)
        output_key = pending_step.get("output_key") or f"step_{pending_step.get('step', 1)}"
        blackboard[output_key] = tool_result.data
        remaining = (continuation.get("plan") or [])[int(continuation.get("next_step_index") or 0):]
        if remaining:
            resumed = await AgentExecutor.run_async(
                blueprint=agent,
                query=continuation.get("query") or "Continue the approved task",
                trace_id=execution.get("trace_id"),
                pre_approved_plan=remaining,
                blackboard=blackboard,
                user_id=user_id,
                tenant_id=tenant_id,
                agent_id=agent_id,
                thread_id=execution.get("thread_id") or "",
                file_ids=execution.get("file_ids") or [],
                agent_run_id=execution.get("agent_run_id") or "",
            )
        else:
            resumed = {"status": "success", "message": str(tool_result.data or "Tool completed")}

        run_id = execution.get("agent_run_id")
        if run_id:
            try:
                run_filter = {"_id": ObjectId(run_id), "user_id": user_id}
            except Exception:
                run_filter = {"_id": run_id, "user_id": user_id}
            status = "pending_approval" if resumed.get("hitl_pending") else ("success" if resumed.get("status") != "error" else "error")
            await get_db()["agent_runs"].update_one(
                run_filter,
                {"$set": {"status": status, "updated_at": datetime.now(timezone.utc),
                          "completed_at": datetime.now(timezone.utc) if status == "success" else None,
                          "tool_execution_id": resumed.get("tool_execution_id")}},
            )
        await ToolExecutionStore.clear_continuation(execution_id, user_id=user_id)
        return {
            "status": "success" if resumed.get("status") != "error" else "error",
            "response": resumed.get("message") or resumed.get("response") or "Tool completed",
            "tool_execution_id": execution_id,
            "agent_run_id": run_id,
            "thread_id": execution.get("thread_id"),
            "data": resumed,
        }
    except (ToolExecutionNotFound, ToolExecutionConflict, ToolExecutionStoreError) as exc:
        raise _error(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
