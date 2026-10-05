"""
Audio utility functions for Call Audit Agent.
- FFmpeg path detection
- Audio metadata extraction
- Duration calculation
- WAV conversion
"""
import os
import re
import wave
import subprocess
import contextlib
from typing import Optional
import logging

logger = logging.getLogger(__name__)


def get_ffmpeg_path() -> str:
    """Locate the bundled ffmpeg binary from imageio_ffmpeg."""
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"


def get_audio_metadata(input_path: str) -> dict:
    """
    Perform a 'Full Decode' to discover the TRUE audio duration.
    Bypasses incorrect MP3 headers and hidden stream offsets.
    """
    meta = {"header_duration": 0.0, "start_time": 0.0, "decoded_duration": 0.0}
    try:
        ffmpeg_exe = get_ffmpeg_path()
        command = [ffmpeg_exe, "-i", input_path, "-f", "null", "-"]
        process = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=0x08000000 if os.name == "nt" else 0,
            text=True,
        )
        output = process.stderr

        dur_match = re.search(r"Duration:\s+(\d+):(\d+):(\d+\.\d+)", output)
        if dur_match:
            h, m, s = map(float, dur_match.groups())
            meta["header_duration"] = h * 3600 + m * 60 + s

        start_match = re.search(r"start:\s+(-?\d+\.\d+)", output)
        if start_match:
            meta["start_time"] = float(start_match.group(1))

        time_matches = re.findall(r"time=(\d+):(\d+):(\d+\.\d+)", output)
        if time_matches:
            h, m, s = map(float, time_matches[-1])
            meta["decoded_duration"] = h * 3600 + m * 60 + s
        else:
            meta["decoded_duration"] = max(
                0.0, meta["header_duration"] - max(0.0, meta["start_time"])
            )

        logger.info(f"🧬 Audio Analysis for {os.path.basename(input_path)}:")
        logger.info(f"   - Header says: {meta['header_duration']:.2f}s")
        logger.info(f"   - Start offset: {meta['start_time']:.2f}s")
        logger.info(f"   - Actual stream: {meta['decoded_duration']:.2f}s")

    except Exception as e:
        logger.warning(f"⚠️ Metadata extraction failed: {e}")
    return meta


async def get_audio_duration(file_path: str, format_type: str = "m.s") -> Optional[str]:
    """Highly accurate duration detection. Supports WAV natively, falls back to ffmpeg."""
    try:
        if not os.path.exists(file_path):
            return None

        ext = os.path.splitext(file_path)[1].lower()
        duration_seconds = 0.0

        if ext == ".wav":
            try:
                with contextlib.closing(wave.open(file_path, "rb")) as wf:
                    frames = wf.getnframes()
                    rate = wf.getframerate()
                    duration_seconds = frames / float(rate)
            except Exception:
                try:
                    import soundfile as sf
                    info_wav = sf.info(file_path)
                    duration_seconds = info_wav.duration
                except Exception:
                    duration_seconds = 0.0
        else:
            meta = get_audio_metadata(file_path)
            duration_seconds = meta["decoded_duration"]

        if format_type == "m.s":
            minutes = int(duration_seconds // 60)
            seconds = int(duration_seconds % 60)
            return f"{minutes}:{seconds:02d}"
        elif format_type == "float_minutes":
            return str(round(duration_seconds / 60, 2))
        else:
            return str(round(duration_seconds, 2))

    except Exception as e:
        logger.error(f"⚠️ Error fetching duration: {e}")
        return None


def format_duration(seconds: float) -> str:
    """Convert seconds to MM:SS format."""
    minutes = int(seconds // 60)
    secs = int(seconds % 60)
    return f"{minutes:02d}:{secs:02d}"


def convert_to_wav(input_path: str, output_path: str) -> bool:
    """Convert any FFmpeg-supported audio to 16 kHz mono 16-bit PCM WAV.

    Invoke the bundled FFmpeg executable directly.  Pydub probes input files
    with a separate ``ffprobe`` process, but imageio-ffmpeg bundles only
    ``ffmpeg`` on some platforms.  Direct invocation avoids that unnecessary
    runtime dependency and works with Windows paths containing spaces.
    """
    try:
        ffmpeg_exe = get_ffmpeg_path()
        command = [
            ffmpeg_exe,
            "-y",
            "-i",
            input_path,
            "-vn",
            "-acodec",
            "pcm_s16le",
            "-ar",
            "16000",
            "-ac",
            "1",
            output_path,
        ]
        logger.info(
            "Converting audio with bundled FFmpeg: %s -> %s",
            os.path.basename(input_path),
            os.path.basename(output_path),
        )
        process = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=0x08000000 if os.name == "nt" else 0,
            text=True,
        )
        if process.returncode != 0:
            logger.error("FFmpeg conversion failed: %s", process.stderr[-2000:])
            return False

        file_size = os.path.getsize(output_path)
        if file_size < 44:
            logger.error("FFmpeg produced truncated WAV output (%s bytes)", file_size)
            return False

        logger.info("Audio conversion succeeded: %s bytes", file_size)
        return True
    except Exception as e:
        logger.error("Audio conversion error with FFmpeg: %s", e, exc_info=True)
        return False
