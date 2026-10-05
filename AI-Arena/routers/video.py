"""
routers/video.py
Video upload and analysis endpoints.
"""
import os
import uuid

from fastapi import APIRouter, HTTPException, Depends, File, UploadFile

from config import settings
from models.video_schemas import VideoUploadResponse, VideoAnalysisResult, JobStatus, ErrorResponse
from services.blob_service import upload_user_file
from services.video_analyzer import VideoAnalyzer
from services.video_processor import VideoProcessor
from middleware.hit_counter import increment_hit_count
from middleware.auth import get_current_user
from utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(
    prefix="/api/video",
    tags=["Video Service"]
)

VIDEO_ALLOWED_EXTENSIONS = {".mp4", ".avi", ".mov", ".mkv", ".webm", ".wmv", ".flv"}


def _validate_video_upload_file(file: UploadFile) -> None:
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided")
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in VIDEO_ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{ext}'. Allowed: {', '.join(sorted(VIDEO_ALLOWED_EXTENSIONS))}",
        )


@router.post(
    "/upload",
    response_model=VideoUploadResponse,
    responses={400: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
    summary="Upload & analyze a video",
    description=(
        "Upload a video file (mp4, avi, mov, mkv, webm, wmv, flv). "
        "The video is processed synchronously through the full pipeline: "
        "frame extraction → Azure Vision → audio transcription → GPT-4 summarization. "
        "Returns the complete analysis result."
    ),
)
async def upload_video(
    file: UploadFile = File(..., description="Video file to analyze"),
    current_user: dict = Depends(get_current_user)
):
    _validate_video_upload_file(file)

    job_id = str(uuid.uuid4())
    upload_dir = os.path.abspath(settings.UPLOAD_DIR)
    os.makedirs(upload_dir, exist_ok=True)
    video_path = os.path.join(upload_dir, f"{job_id}_{file.filename}")

    try:
        # 1. Upload to Blob Storage and update storage tracking
        blob_info = await upload_user_file(current_user["_id"], file)
        content = blob_info["content"]

        # ── Save the uploaded file locally for analysis pipeline ────
        logger.info(f"[{job_id}] Saving uploaded file: {file.filename}")
        with open(video_path, "wb") as buffer:
            buffer.write(content)

        file_size = os.path.getsize(video_path)
        max_bytes = int(settings.MAX_VIDEO_SIZE_MB) * 1024 * 1024

        if file_size > max_bytes:
            os.remove(video_path)
            raise HTTPException(
                status_code=400,
                detail=f"File too large ({file_size / 1024 / 1024:.1f} MB). Max: {settings.MAX_VIDEO_SIZE_MB} MB.",
            )

        # ── Validate video duration ─────────────────────────────────
        processor = VideoProcessor()
        try:
            meta = await processor.get_video_metadata(video_path)
            duration_seconds = meta.get("duration_seconds", 0)
            max_duration_seconds = settings.MAX_VIDEO_DURATION_MINUTES * 60
            if duration_seconds > max_duration_seconds:
                os.remove(video_path)
                raise HTTPException(
                    status_code=400,
                    detail=f"Video too long ({duration_seconds / 60:.1f} min). Max: {settings.MAX_VIDEO_DURATION_MINUTES} min.",
                )
        except HTTPException:
            raise
        except Exception as e:
            logger.warning(f"[{job_id}] Could not validate video duration: {e}")

        logger.info(f"[{job_id}] File saved ({file_size / 1024 / 1024:.1f} MB, {duration_seconds / 60:.1f} min). Starting analysis...")

        # ── Run the full analysis pipeline ──────────────────────────
        analyzer = VideoAnalyzer()
        result: VideoAnalysisResult = await analyzer.analyze(video_path, file.filename)

        # Increment hit count for Video Analysis (unified)
        await increment_hit_count(current_user["_id"], "video_analysis")

        logger.info(f"[{job_id}] Analysis complete")
        return VideoUploadResponse(
            job_id=job_id,
            status=JobStatus.COMPLETED,
            message="Video analysis completed successfully",
            result=result,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"[{job_id}] Analysis failed")
        return VideoUploadResponse(
            job_id=job_id,
            status=JobStatus.FAILED,
            message=f"Video analysis failed: {str(e)}",
            result=None,
        )
    finally:
        # Cleanup uploaded file
        if os.path.exists(video_path):
            os.remove(video_path)
            logger.info(f"[{job_id}] Cleaned up uploaded file")


@router.get("/health")
async def video_service_health():
    """Health check for the video analysis service."""
    return {
        "status": "healthy",
        "service": "Video Summariser",
        "capabilities": [
            "scene_detection",
            "object_detection",
            "speech_transcription",
            "brand_detection",
            "gpt_summarization",
            "topic_extraction",
            "sentiment_analysis",
            "timeline_generation",
        ],
        "config": {
            "max_video_size_mb": settings.MAX_VIDEO_SIZE_MB,
            "frame_interval_seconds": settings.FRAME_INTERVAL_SECONDS,
            "azure_vision_configured": bool(settings.AZURE_VIDEO_VISION_API_KEY)
            and "your-" not in settings.AZURE_VIDEO_VISION_API_KEY,
            "azure_speech_configured": bool(settings.AZURE_VIDEO_SPEECH_KEY)
            and "your-" not in settings.AZURE_VIDEO_SPEECH_KEY,
            "azure_openai_configured": bool(settings.AZURE_OPENAI_API_KEY)
            and "your-" not in settings.AZURE_OPENAI_API_KEY,
        },
    }
