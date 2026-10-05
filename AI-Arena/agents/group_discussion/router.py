"""
agents/group_discussion/router.py
Group Discussion agent endpoint.
"""
import os
import shutil
import tempfile
from typing import Optional

from fastapi import APIRouter, HTTPException, Depends, File, UploadFile, Form

from agents.group_discussion.service import analyze_gd, process_gd_audio
from services.blob_service import upload_user_file
from middleware.hit_counter import increment_hit_count
from middleware.auth import get_current_user
from utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/gd", tags=["group-discussion"])


@router.post("/analyze")
async def gd_analyze(
    topic: str = Form(...),
    transcript: Optional[str] = Form(None),
    file: Optional[UploadFile] = File(None),
    user=Depends(get_current_user)
):
    """Analyze GD via transcript text OR audio file."""
    try:
        if file:
            # 1. Upload to Blob Storage and update storage tracking
            try:
                blob_info = await upload_user_file(user["_id"], file)
                content = blob_info["content"]
            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"Upload failed: {e}")
                raise HTTPException(status_code=500, detail="Failed to upload file to storage")

            ext = os.path.splitext(file.filename or "")[1].lower()
            temp_dir = tempfile.mkdtemp()
            temp_path = os.path.join(temp_dir, f"gd_upload{ext}")

            try:
                with open(temp_path, "wb") as f:
                    f.write(content)
                result = await process_gd_audio(temp_path, topic)
            finally:
                shutil.rmtree(temp_dir, ignore_errors=True)

        elif transcript:
            result = await analyze_gd(transcript, topic)

        else:
            raise HTTPException(status_code=400, detail="Provide either a transcript or an audio file.")

        # Update stats
        token_count = result.get("token_usage", {}).get("total_tokens", 0)
        await increment_hit_count(user["_id"], "gd", target_field="agent_hits", tokens=token_count)

        return result

    except HTTPException as he:
        raise he
    except Exception as e:
        logger.error(f"GD Analysis failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
