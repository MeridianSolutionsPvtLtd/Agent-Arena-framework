"""
agents/call_audit/router.py
Call Audit agent endpoint — streaming SSE analysis.
"""
import os
import json
import asyncio
import shutil
import tempfile

from fastapi import APIRouter, HTTPException, Depends, File, UploadFile
from fastapi.responses import StreamingResponse

from agents.call_audit.service import analyze_audio
from services.blob_service import upload_user_file
from middleware.hit_counter import increment_hit_count
from middleware.auth import get_current_user
from utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/call-audit", tags=["call-audit"])


@router.post("/analyze")
async def call_audit_analyze(file: UploadFile = File(...), user=Depends(get_current_user)):
    """
    Accept an audio file upload, run the full Call Audit pipeline,
    and return a StreamingResponse of status updates and analysis results.
    """
    # 1. Upload to Blob Storage
    try:
        blob_info = await upload_user_file(user["_id"], file)
        content = blob_info["content"]
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Upload failed: {e}")
        raise HTTPException(status_code=500, detail="Failed to upload file to storage")

    # 2. Validate file type
    allowed_extensions = {".wav", ".mp3", ".m4a", ".ogg", ".flac", ".wma", ".aac", ".webm"}
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in allowed_extensions:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported format '{ext}'. Supported: {', '.join(allowed_extensions)}",
        )

    # Save to project local tmp to avoid long path issues on Windows.
    # __file__ is agents/call_audit/router.py, so dirname(__file__) == agents/call_audit/
    project_tmp = os.path.join(os.path.dirname(__file__), ".tmp")
    os.makedirs(project_tmp, exist_ok=True)
    temp_dir = tempfile.mkdtemp(prefix="call_audit_", dir=project_tmp)
    temp_path = os.path.join(temp_dir, f"upload{ext}")

    async def event_generator():
        # 3. Write uploaded content to temp file
        try:
            with open(temp_path, "wb") as f:
                f.write(content)
        except Exception as e:
            logger.error(f"Failed to write temp file: {e}")
            yield f"data: {json.dumps({'status': 'error', 'detail': 'Failed to prepare audio file'})}\n\n"
            return

        queue = asyncio.Queue()

        # Producer 1: Pipeline
        async def produce_pipeline():
            try:
                pipeline = analyze_audio(temp_path)
                async for step in pipeline:
                    await queue.put(step)
            except Exception as e:
                logger.error(f"❌ Pipeline failed: {e}", exc_info=True)
                await queue.put({"status": "error", "detail": str(e)})
            finally:
                await queue.put(None)  # Sentinel for completion

        # Producer 2: Keep-alive Pings
        async def produce_pings():
            try:
                while True:
                    await asyncio.sleep(20)
                    await queue.put({"status": "ping"})
            except asyncio.CancelledError:
                pass

        # Start producers
        producer_task = asyncio.create_task(produce_pipeline())
        ping_task = asyncio.create_task(produce_pings())

        try:
            while True:
                item = await queue.get()
                if item is None:
                    break

                yield f"data: {json.dumps(item)}\n\n"

                # If complete, record stats and exit
                if item.get("status") == "complete":
                    result = item.get("result", {})
                    token_count = result.get("token_usage", {}).get("total_tokens", 0)
                    await increment_hit_count(user["_id"], "call_audit", target_field="agent_hits", tokens=token_count)
                    break

                if item.get("status") == "error":
                    break

        finally:
            # Cleanup
            producer_task.cancel()
            ping_task.cancel()
            shutil.rmtree(temp_dir, ignore_errors=True)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "X-Accel-Buffering": "no",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        }
    )
