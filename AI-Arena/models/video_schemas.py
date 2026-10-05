from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from enum import Enum


class JobStatus(str, Enum):
    """Status of a video analysis job."""
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


# ── Scene Detection ──────────────────────────────────────────────

class DetectedObject(BaseModel):
    """An object detected in a video frame."""
    name: str
    confidence: float = Field(..., ge=0, le=1)
    bounding_box: Optional[Dict[str, int]] = None


class SceneInfo(BaseModel):
    """Information about a detected scene in the video."""
    scene_index: int
    timestamp_seconds: float
    description: str
    tags: List[str] = []
    objects: List[DetectedObject] = []
    dominant_colors: List[str] = []
    brands: List[str] = []
    ocr_text: List[str] = []


# ── Transcript ───────────────────────────────────────────────────

class TranscriptSegment(BaseModel):
    """A segment of transcribed speech."""
    start_seconds: float
    end_seconds: float
    text: str
    confidence: Optional[float] = None
    speaker: Optional[str] = None


# ── Summarization ────────────────────────────────────────────────

class SentimentSummary(BaseModel):
    """Overall sentiment analysis of the video."""
    overall: str = Field(..., description="positive, negative, neutral, or mixed")
    score: float = Field(..., ge=-1, le=1)
    breakdown: Dict[str, float] = Field(
        default_factory=dict,
        description="e.g. {'positive': 0.6, 'negative': 0.1, 'neutral': 0.3}",
    )


class HighlightEntry(BaseModel):
    """A specific highlight with confidence and timestamp."""
    text: str
    confidence: float = Field(default=0.0, ge=0, le=1)
    timestamp: float = 0.0


class VideoSummary(BaseModel):
    """GPT-generated summary and insights."""
    concise_summary: str
    key_highlights: List[HighlightEntry] = []
    topics: List[str] = []
    sentiment: Optional[SentimentSummary] = None


class TimelineEntry(BaseModel):
    """A single entry on the video timeline."""
    timestamp_seconds: float
    event_type: str = Field(..., description="scene_change | speech | highlight | topic_shift")
    description: str
    ocr_text: Optional[str] = None


# ── Full Analysis Result ─────────────────────────────────────────

class VideoMetadata(BaseModel):
    """Technical metadata about the uploaded video."""
    filename: str
    duration_seconds: float
    resolution: Optional[str] = None
    fps: Optional[float] = None
    file_size_mb: float
    frame_count_extracted: int
    audio_extracted: bool


class VideoAnalysisResult(BaseModel):
    """Complete video analysis output."""
    metadata: VideoMetadata
    scenes: List[SceneInfo] = []
    transcript: List[TranscriptSegment] = []
    summary: Optional[VideoSummary] = None
    timeline: List[TimelineEntry] = []


# ── API Response Models ──────────────────────────────────────────

class VideoUploadResponse(BaseModel):
    """Response returned immediately after a successful upload + analysis."""
    job_id: str
    status: JobStatus
    message: str
    result: Optional[VideoAnalysisResult] = None


class ErrorResponse(BaseModel):
    """Standard error response."""
    error: str
    detail: Optional[str] = None
