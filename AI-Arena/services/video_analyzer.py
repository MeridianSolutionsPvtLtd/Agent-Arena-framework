"""
Video Analyzer — Orchestrator Service
Wires together the full pipeline:
  Video → Frame Extraction → Audio Extraction → Vision Analysis → Speech Transcription → GPT Summary
"""

import os
import uuid
import shutil
import tempfile
import logging
import json
import asyncio
from typing import Dict, Any

from config import settings
from services.video_processor import VideoProcessor
from services.azure_vision import AzureVisionService
from services.azure_speech import AzureSpeechService
from services.azure_openai import AzureOpenAIService
from models.video_schemas import (
    VideoAnalysisResult,
    VideoMetadata,
    SceneInfo,
    DetectedObject,
    TranscriptSegment,
    VideoSummary,
    SentimentSummary,
    TimelineEntry,
    HighlightEntry,
)

logger = logging.getLogger(__name__)


class VideoAnalyzer:
    """Orchestrates the full video analysis pipeline."""

    def __init__(self):
        self.processor = VideoProcessor(
            frame_interval_seconds=settings.FRAME_INTERVAL_SECONDS
        )
        self.vision = AzureVisionService()
        self.speech = AzureSpeechService()
        self.openai = AzureOpenAIService()

    async def analyze(self, video_path: str, filename: str) -> VideoAnalysisResult:
        """
        Run the full analysis pipeline on an uploaded video.

        Steps:
            1. Extract video metadata
            2. Extract frames at intervals
            3. Extract audio track
            4. Analyze frames with Azure Vision
            5. Transcribe audio with Azure Speech
            6. Summarize everything with GPT-4
            7. Assemble final result
        """
        work_dir = tempfile.mkdtemp(prefix="videosumm_")
        logger.info(f"Working directory: {work_dir}")

        try:
            # ── Step 1: Metadata ─────────────────────────────────────
            print("Step 1")
            raw_meta = await self.processor.get_video_metadata(video_path)

            # ── Steps 2+3: Frame + Audio extraction (PARALLEL) ───────
            print("Steps 2+3 (parallel)")
            frames, audio_path = await asyncio.gather(
                self.processor.extract_frames(video_path, work_dir),
                self.processor.extract_audio(video_path, work_dir),
            )
            logger.info(f"⚡ Parallel extraction: {len(frames)} frames + audio")

            # ── Steps 4+5: Vision + Speech analysis (PARALLEL) ───────
            print("Steps 4+5 (parallel)")
            frame_analyses, transcript_raw = await asyncio.gather(
                self.vision.analyze_frames(frames),
                self.speech.transcribe_audio(audio_path),
            )
            logger.info(f"⚡ Parallel analysis: {len(frame_analyses)} frames + {len(transcript_raw)} transcript segments")

            # ── Step 6: GPT-4 summarization ──────────────────────────
            print("Step 6")
            gpt_result = await self.openai.generate_summary(
                frame_analyses, transcript_raw, raw_meta
            )
            # print("GPT result", gpt_result)

            # ── Step 7: Assemble result ──────────────────────────────
            print("Step 7")
            logger.info(f"GPT Result for assembly: {json.dumps(gpt_result)}")
            
            metadata = VideoMetadata(
                filename=filename,
                duration_seconds=raw_meta["duration_seconds"],
                resolution=raw_meta.get("resolution"),
                fps=raw_meta.get("fps"),
                file_size_mb=raw_meta["file_size_mb"],
                frame_count_extracted=len(frames),
                audio_extracted=audio_path is not None,
            )

            try:
                scenes = self._build_scenes(frame_analyses)
                transcript = self._build_transcript(transcript_raw)
                summary = self._build_summary(gpt_result)
                timeline = self._build_timeline(gpt_result)
                
                return VideoAnalysisResult(
                    metadata=metadata,
                    scenes=scenes,
                    transcript=transcript,
                    summary=summary,
                    timeline=timeline,
                )
            except Exception as ve:
                logger.error(f"Validation Error during result assembly: {ve}", exc_info=True)
                raise ve

        finally:
            # Cleanup temp directory
            shutil.rmtree(work_dir, ignore_errors=True)
            logger.info("Cleaned up working directory")

    # ── Builders ────────────────────────────────────────────────────

    def _build_scenes(self, frame_analyses: list) -> list:
        scenes = []
        for idx, fa in enumerate(frame_analyses):
            objects = [
                DetectedObject(
                    name=obj["name"],
                    confidence=obj["confidence"],
                    bounding_box=obj.get("bounding_box"),
                )
                for obj in fa.get("objects", [])
            ]
            scenes.append(
                SceneInfo(
                    scene_index=idx,
                    timestamp_seconds=fa["timestamp"],
                    description=fa["description"],
                    tags=fa.get("tags", []),
                    objects=objects,
                    brands=fa.get("brands", []),
                    ocr_text=fa.get("text_in_frame", []),
                )
            )
        logger.info(f"Built {len(scenes)} scenes with OCR and tag data")
        return scenes

    def _build_transcript(self, transcript_raw: list) -> list:
        return [
            TranscriptSegment(
                start_seconds=seg["start_seconds"],
                end_seconds=seg["end_seconds"],
                text=seg["text"],
                confidence=seg.get("confidence"),
            )
            for seg in transcript_raw
        ]

    def _build_summary(self, gpt_result: dict) -> VideoSummary:
        sentiment_data = gpt_result.get("sentiment")
        sentiment = None
        if sentiment_data:
            sentiment = SentimentSummary(
                overall=sentiment_data.get("overall", "neutral"),
                score=sentiment_data.get("score", 0.0),
                breakdown=sentiment_data.get("breakdown", {}),
            )

        highlights = []
        for h in gpt_result.get("key_highlights", []):
            if isinstance(h, dict):
                highlights.append(
                    HighlightEntry(
                        text=h.get("text", ""),
                        confidence=h.get("confidence", 0.0),
                        timestamp=h.get("timestamp", 0.0),
                    )
                )
            else:
                highlights.append(HighlightEntry(text=str(h)))

        # Sort highlights chronologically by timestamp
        highlights.sort(key=lambda x: x.timestamp)
        logger.info(f"Sorted {len(highlights)} highlights chronologically")

        return VideoSummary(
            concise_summary=gpt_result.get("concise_summary", ""),
            key_highlights=highlights,
            topics=gpt_result.get("topics", []),
            sentiment=sentiment,
        )

    def _build_timeline(self, gpt_result: dict) -> list:
        return [
            TimelineEntry(
                timestamp_seconds=entry.get("timestamp_seconds", 0),
                event_type=entry.get("event_type", "highlight"),
                description=entry.get("description", ""),
                ocr_text=entry.get("ocr_text"),
            )
            for entry in gpt_result.get("timeline", [])
        ]
