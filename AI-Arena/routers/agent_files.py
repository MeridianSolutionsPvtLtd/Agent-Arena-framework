"""
Attachment routes for custom agent runs.
POST /api/agents/files, GET /api/agents/files/{file_id}, DELETE /api/agents/files/{file_id}.

Transport only: authenticate, read bytes, delegate to InputNormalizer, shape the
HTTP response. No extraction logic lives here. The client passes the returned
file_ids into POST /api/agents/{agent_id}/run.

Extraction runs here rather than during the agent run so that guardrails see
file content before any model does, the client learns immediately if a file is
unreadable, and a file can be reused across turns without paying to extract it
again.
"""
import logging
from typing import List

from fastapi import APIRouter, HTTPException, Depends, File, UploadFile

from core.ingestion import InputNormalizer, IngestionRejected
from core.ingestion.store import AttachmentStore, new_file_id, write_bytes
from core.security.audit import emit_audit_event
from middleware.auth import get_current_user

logger = logging.getLogger(__name__)

# Shares the /api/agents prefix with routers/agents.py. Registered before
# agents.router in main.py as defensive ordering only: /files/{file_id} and
# /{agent_id} differ in segment count, so neither order shadows the other today.
router = APIRouter(prefix="/api/agents", tags=["Agents"])


@router.post("/files")
async def upload_agent_files(
    files: List[UploadFile] = File(...),
    current_user: dict = Depends(get_current_user),
):
    """Upload and normalize one or more attachments for use in a later agent run."""
    user_id = current_user["_id"]

    if not files:
        raise HTTPException(status_code=400, detail="No files were provided.")

    if len(files) > InputNormalizer.MAX_ATTACHMENTS_PER_REQUEST:
        raise HTTPException(
            status_code=400,
            detail=f"Too many files in one request: {len(files)} "
                   f"(limit {InputNormalizer.MAX_ATTACHMENTS_PER_REQUEST}).",
        )

    results = []
    errors = []

    for upload in files:
        filename = upload.filename or "upload"

        try:
            data = await upload.read()
        except Exception as e:
            logger.error(f"[INGEST] Failed to read upload {filename}: {e}")
            errors.append({
                "filename": filename,
                "code": "read_failed",
                "detail": "Could not read the uploaded file.",
            })
            continue
        finally:
            await upload.close()

        # Cheap size check before spending anything on extraction.
        if len(data) > InputNormalizer.MAX_ATTACHMENT_BYTES:
            limit_mb = InputNormalizer.MAX_ATTACHMENT_BYTES // (1024 * 1024)
            errors.append({
                "filename": filename,
                "code": "file_too_large",
                "detail": f"Exceeds the {limit_mb}MB limit.",
            })
            continue

        file_id = new_file_id()

        try:
            attachment = await InputNormalizer.normalize_file(
                data,
                filename,
                content_type=upload.content_type or "",
                user_id=user_id,
                file_id=file_id,
                per_user_credentials=False,   # agent traffic uses platform credentials
            )
        except IngestionRejected as e:
            emit_audit_event(
                "agent_file_rejected",
                user_id=user_id,
                filename=filename,
                code=e.code,
                size_bytes=len(data),
            )
            errors.append({"filename": filename, "code": e.code, "detail": e.message})
            continue
        except Exception as e:
            logger.error(f"[INGEST] Normalization failed for {filename}: {e}", exc_info=True)
            errors.append({
                "filename": filename,
                "code": "normalization_failed",
                "detail": "Could not process file.",
            })
            continue

        # Keep the original bytes: executor tools re-open the file by path.
        try:
            attachment["stored_path"] = write_bytes(
                user_id, attachment["file_id"], attachment["filename"], data
            )
        except OSError as e:
            logger.error(f"[INGEST] Failed to store {filename}: {e}")
            errors.append({
                "filename": filename,
                "code": "storage_failed",
                "detail": "Could not store file.",
            })
            continue

        await AttachmentStore.save(attachment)
        results.append(InputNormalizer.public_view(attachment))

    if not results and errors:
        raise HTTPException(
            status_code=400,
            detail={"message": "No files could be processed.", "errors": errors},
        )

    emit_audit_event(
        "agent_files_uploaded",
        user_id=user_id,
        accepted=len(results),
        rejected=len(errors),
        file_ids=[r["file_id"] for r in results],
    )

    return {"files": results, "errors": errors}


@router.get("/files/{file_id}")
async def get_agent_file(file_id: str, current_user: dict = Depends(get_current_user)):
    """Metadata and preview for one attachment owned by the caller."""
    user_id = current_user["_id"]

    attachment = await AttachmentStore.get(file_id, user_id)
    if attachment is None:
        # Same response whether the file does not exist or belongs to someone
        # else: do not leak existence across tenants.
        raise HTTPException(status_code=404, detail="File not found.")
    return InputNormalizer.public_view(attachment)


@router.delete("/files/{file_id}")
async def delete_agent_file(file_id: str, current_user: dict = Depends(get_current_user)):
    """Remove the stored bytes and the attachment record."""
    user_id = current_user["_id"]

    deleted = await AttachmentStore.delete(file_id, user_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="File not found.")

    emit_audit_event("agent_file_deleted", user_id=user_id, file_id=file_id)
    return {"status": "deleted", "file_id": file_id}