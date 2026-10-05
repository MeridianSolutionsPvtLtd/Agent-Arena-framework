"""
agents/compliance/router.py
Compliance policy analysis endpoints.
"""
import asyncio
from typing import Optional

from fastapi import APIRouter, HTTPException, Depends, File, UploadFile, Form
from pydantic import BaseModel

from agents.compliance.service import ComplianceService
from core.persistence.runtime_store import AgentRuntimeStore
from middleware.auth import get_current_user
from middleware.hit_counter import increment_hit_count
from services.blob_service import upload_user_file
from services.external_thread_service import (
    complete_provider_thread,
    get_owned_thread,
    prepare_provider_thread,
)
from utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/compliance", tags=["Compliance"])

compliance_service_instance = ComplianceService()
AGENT_ID = "compliance_policy"


class ComplianceAnalyzeTextRequest(BaseModel):
    policy_text: str
    thread_id: Optional[str] = None


class ComplianceAnalysisResponse(BaseModel):
    thread_id: str
    response: str
    status: str


class ComplianceDocumentAnalysisResponse(BaseModel):
    thread_id: str
    filename: str
    response: str
    status: str


async def _run_owned_analysis(
    *,
    prompt: str,
    user_text: str,
    requested_thread_id: Optional[str],
    user_id: str,
) -> dict:
    """Run Compliance analysis through an application-owned thread."""
    provider_thread_id = await prepare_provider_thread(
        thread_id=requested_thread_id,
        user_id=user_id,
        agent_id=AGENT_ID,
        require_provider=True,
    )

    result = await asyncio.to_thread(
        compliance_service_instance.run_analysis,
        prompt,
        provider_thread_id,
    )
    provider_result_thread_id = result.get("thread_id")
    if not provider_result_thread_id:
        raise HTTPException(
            status_code=502,
            detail="Compliance provider did not return a valid thread.",
        )

    application_thread_id = await complete_provider_thread(
        requested_thread_id=requested_thread_id,
        provider_thread_id=provider_result_thread_id,
        user_id=user_id,
        agent_id=AGENT_ID,
    )
    if not application_thread_id:
        raise HTTPException(
            status_code=502,
            detail="Failed to establish the compliance thread.",
        )

    response_text = str(result.get("response") or "")
    await AgentRuntimeStore.append_message(
        thread_id=application_thread_id,
        user_id=user_id,
        agent_id=AGENT_ID,
        role="user",
        text=user_text,
        metadata={"source": "compliance_specialized"},
    )
    await AgentRuntimeStore.append_message(
        thread_id=application_thread_id,
        user_id=user_id,
        agent_id=AGENT_ID,
        role="assistant",
        text=response_text,
        metadata={"source": "compliance_specialized"},
    )

    public_result = dict(result)
    public_result["thread_id"] = application_thread_id
    return public_result


@router.post("/analyze/text", response_model=ComplianceAnalysisResponse)
async def compliance_analyze_text(request: ComplianceAnalyzeTextRequest, user=Depends(get_current_user)):
    logger.info("Text analysis query received (thread=%s, len=%d)",
                request.thread_id or "new", len(request.policy_text))

    prompt = compliance_service_instance.build_analysis_prompt(request.policy_text)

    try:
        result = await _run_owned_analysis(
            prompt=prompt,
            user_text=request.policy_text,
            requested_thread_id=request.thread_id,
            user_id=user["_id"],
        )

        # Update hits and tokens
        token_count = result.get("usage", {}).get("total_tokens", 0)
        await increment_hit_count(user["_id"], AGENT_ID, target_field="agent_hits", tokens=token_count)

        return ComplianceAnalysisResponse(**result)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Agent run failed")
        raise HTTPException(status_code=500, detail="Agent execution failed") from exc


@router.post("/analyze/document", response_model=ComplianceDocumentAnalysisResponse)
async def compliance_analyze_document(
    file: UploadFile = File(..., description="PDF, DOCX, DOC, or TXT policy document"),
    thread_id: Optional[str] = Form(None, description="Optional thread ID for continuation"),
    user=Depends(get_current_user),
):
    logger.info("Document upload received: %s", file.filename)

    try:
        # 1. Upload to Blob Storage and update storage tracking
        blob_info = await upload_user_file(user["_id"], file)

        # 2. Extract text from the content (using the bytes from blob_info)
        document_text = compliance_service_instance.read_text_from_content(blob_info["content"], file.filename)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to parse uploaded document")
        raise HTTPException(status_code=400, detail="Failed to parse the uploaded document.") from exc

    if not document_text.strip():
        raise HTTPException(status_code=400, detail="The uploaded document appears to be empty or unreadable.")

    prompt = compliance_service_instance.build_analysis_prompt(document_text)

    try:
        result = await _run_owned_analysis(
            prompt=prompt,
            user_text=f"Analyze document: {file.filename or 'Unknown'}",
            requested_thread_id=thread_id,
            user_id=user["_id"],
        )

        # Update hits and tokens
        token_count = result.get("usage", {}).get("total_tokens", 0)
        await increment_hit_count(user["_id"], AGENT_ID, target_field="agent_hits", tokens=token_count)

        return ComplianceDocumentAnalysisResponse(
            thread_id=result["thread_id"],
            filename=file.filename or "Unknown",
            response=result["response"],
            status=result["status"]
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Agent run failed")
        raise HTTPException(status_code=500, detail="Agent execution failed") from exc


@router.get("/thread/{thread_id}/messages")
async def compliance_get_thread_messages(thread_id: str, user=Depends(get_current_user)):
    try:
        await get_owned_thread(
            thread_id=thread_id,
            user_id=user["_id"],
            agent_id=AGENT_ID,
        )
        messages = await AgentRuntimeStore.get_messages_for_thread(
            thread_id=thread_id,
            user_id=user["_id"],
            agent_id=AGENT_ID,
        )
        return {"thread_id": thread_id, "messages": messages}
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to fetch thread messages")
        raise HTTPException(status_code=500, detail="Failed to fetch thread messages") from exc
