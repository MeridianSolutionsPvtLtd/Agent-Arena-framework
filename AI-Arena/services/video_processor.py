"""
Video Processor Service
Extracts frames and audio from uploaded video files using OpenCV and MoviePy.
"""

import os
import cv2
import tempfile
import logging
from typing import List, Tuple, Optional

logger = logging.getLogger(__name__)


class VideoProcessor:
    """Handles frame extraction and audio extraction from video files."""

    def __init__(self, frame_interval_seconds: int = 2):
        self.frame_interval_seconds = frame_interval_seconds

    async def extract_frames(
        self, video_path: str, output_dir: str
    ) -> List[Tuple[str, float]]:
        """
        Extract key frames from a video at a fixed interval.

        Returns:
            List of (frame_path, timestamp_seconds) tuples.
        """
        frames: List[Tuple[str, float]] = []
        cap = cv2.VideoCapture(video_path)

        if not cap.isOpened():
            raise ValueError(f"Cannot open video file: {video_path}")

        fps = cap.get(cv2.CAP_PROP_FPS)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        duration = total_frames / fps if fps > 0 else 0
        frame_skip = int(fps * self.frame_interval_seconds)

        logger.info(
            f"Video: {duration:.1f}s, {fps:.1f} FPS, extracting every {self.frame_interval_seconds}s"
        )

        frame_idx = 0
        extracted = 0

        while True:
            ret, frame = cap.read()
            if not ret:
                break

            if frame_idx % frame_skip == 0:
                timestamp = frame_idx / fps
                frame_path = os.path.join(output_dir, f"frame_{extracted:04d}.jpg")
                cv2.imwrite(frame_path, frame)
                frames.append((frame_path, timestamp))
                extracted += 1

            frame_idx += 1

        cap.release()
        logger.info(f"Extracted {extracted} frames from video")
        return frames

    async def extract_audio(
        self, video_path: str, output_dir: str
    ) -> Optional[str]:
        """
        Extract audio track from the video as a WAV file using ffmpeg.

        Returns:
            Path to the extracted audio WAV file, or None if extraction failed or no audio.
        """
        import subprocess

        audio_path = os.path.join(output_dir, "audio.wav")
        
        # ffmpeg command:
        # -i video_path       : input file
        # -vn                 : disable video recording
        # -acodec pcm_s16le   : audio codec PCM 16-bit little endian
        # -ar 16000           : sample rate 16kHz (required for Azure Speech)
        # -ac 1               : audio channels 1 (mono)
        # -y                  : overwrite output file
        cmd = [
            "ffmpeg",
            "-i", video_path,
            "-vn",
            "-acodec", "pcm_s16le",
            "-ar", "16000",
            "-ac", "1",
            "-y",
            audio_path
        ]

        logger.info(f"Extracting audio with ffmpeg: {' '.join(cmd)}")

        try:
            # Run ffmpeg, capturing stdout/stderr
            process = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False  # We'll check returncode manually
            )

            if process.returncode != 0:
                # Check if it's because there's no audio stream
                if "does not contain any stream" in process.stderr:
                    logger.info("Video does not contain any audio stream.")
                else:
                    logger.error(f"ffmpeg failed with exit code {process.returncode}")
                    logger.debug(f"ffmpeg stderr: {process.stderr}")
                return None

            if os.path.exists(audio_path) and os.path.getsize(audio_path) > 0:
                logger.info(f"Extracted audio to {audio_path}")
                return audio_path
            else:
                logger.warning("ffmpeg finished but audio file is missing or empty")
                return None

        except Exception as e:
            logger.error(f"Audio extraction failed: {e}")
            return None

    async def get_video_metadata(self, video_path: str) -> dict:
        """Get basic metadata about the video file."""
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            raise ValueError(f"Cannot open video file: {video_path}")

        fps = cap.get(cv2.CAP_PROP_FPS)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        duration = total_frames / fps if fps > 0 else 0
        file_size_mb = os.path.getsize(video_path) / (1024 * 1024)

        cap.release()

        return {
            "duration_seconds": round(duration, 2),
            "resolution": f"{width}x{height}",
            "fps": round(fps, 2),
            "file_size_mb": round(file_size_mb, 2),
            "total_frames": total_frames,
        }
