import json
import os
import logging
import tempfile
import time
import uuid
from typing import Type
from crewai.tools import BaseTool
from pydantic import BaseModel, Field
import azure.cognitiveservices.speech as speechsdk
from pydub import AudioSegment
import speech_recognition as sr

logger = logging.getLogger(__name__)

# ─── Output directory for transcribed .txt files ───
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUTPUTS_DIR = os.path.join(BASE_DIR, "outputs")
UPLOADS_DIR = os.path.join(BASE_DIR, "uploads")
os.makedirs(OUTPUTS_DIR, exist_ok=True)


# ─── Supported audio extensions ───
SUPPORTED_AUDIO_EXTENSIONS = {".wav", ".mp3", ".ogg", ".flac", ".m4a", ".webm", ".mp4", ".wma", ".aac"}


def _convert_to_wav(file_path: str) -> str:
    """
    Convert any supported audio format to WAV using pydub.
    Returns the path to the WAV file (may be a temp file).
    """
    ext = os.path.splitext(file_path)[1].lower()
    if ext == ".wav":
        return file_path

    try:
        logger.info(f"[STT] Converting {ext} → .wav")

        format_map = {
            ".mp3": "mp3",
            ".ogg": "ogg",
            ".flac": "flac",
            ".m4a": "m4a",
            ".webm": "webm",
            ".mp4": "mp4",
            ".wma": "wma",
            ".aac": "aac",
        }
        fmt = format_map.get(ext, ext.lstrip("."))

        audio = AudioSegment.from_file(file_path, format=fmt)
        wav_path = os.path.join(
            tempfile.gettempdir(), f"stt_{uuid.uuid4().hex[:8]}.wav"
        )
        audio.export(wav_path, format="wav")
        return wav_path

    except Exception as e:
        raise RuntimeError(f"Audio conversion failed: {e}")


def _transcribe_with_speech_recognition(wav_path: str) -> str:
    """Transcribe WAV audio using the SpeechRecognition library (Google free API)."""
    recognizer = sr.Recognizer()
    with sr.AudioFile(wav_path) as source:
        recognizer.adjust_for_ambient_noise(source, duration=0.5)
        audio_data = recognizer.record(source)

    logger.info("[STT] Sending audio to Google Speech Recognition API...")
    text = recognizer.recognize_google(audio_data)
    return text


def _transcribe_with_azure(wav_path: str) -> str:
    """Transcribe WAV audio using Azure Cognitive Services Speech SDK."""
    speech_key = os.getenv("AZURE_SPEECH_KEY", "")
    speech_region = os.getenv("AZURE_SPEECH_REGION", "")

    if not speech_key or not speech_region:
        raise RuntimeError("Azure Speech credentials not configured.")

    speech_config = speechsdk.SpeechConfig(
        subscription=speech_key, region=speech_region
    )
    speech_config.speech_recognition_language = "en-US"

    audio_config = speechsdk.audio.AudioConfig(filename=wav_path)
    recognizer = speechsdk.SpeechRecognizer(
        speech_config=speech_config, audio_config=audio_config
    )

    logger.info("[STT] Sending audio to Azure Speech Services...")

    # For longer audio, use continuous recognition
    all_text = []
    done = False

    def on_recognized(evt):
        if evt.result.reason == speechsdk.ResultReason.RecognizedSpeech:
            all_text.append(evt.result.text)

    def on_session_stopped(evt):
        nonlocal done
        done = True

    def on_canceled(evt):
        nonlocal done
        done = True

    recognizer.recognized.connect(on_recognized)
    recognizer.session_stopped.connect(on_session_stopped)
    recognizer.canceled.connect(on_canceled)

    recognizer.start_continuous_recognition()

    timeout = 300  # 5 min max
    elapsed = 0
    while not done and elapsed < timeout:
        time.sleep(0.5)
        elapsed += 0.5

    recognizer.stop_continuous_recognition()

    return " ".join(all_text)


def _resolve_audio_path(file_path: str) -> str:
    """Resolve the audio file path, checking uploads directory as fallback."""
    if os.path.exists(file_path):
        return file_path

    # Try to find in uploads directory (same logic as FileExtractorTool)
    base_name = os.path.basename(file_path or "")
    base_name_lower = base_name.lower()

    candidate_dirs = [
        UPLOADS_DIR,
        os.path.join(os.getcwd(), "uploads"),
        tempfile.gettempdir(),
    ]

    best_match = ""
    best_mtime = -1.0

    for root_dir in candidate_dirs:
        if not root_dir or not os.path.isdir(root_dir):
            continue
        for entry in os.listdir(root_dir):
            entry_path = os.path.join(root_dir, entry)
            if not os.path.isfile(entry_path):
                continue
            entry_lower = entry.lower()
            if (
                entry_lower == base_name_lower
                or entry_lower.endswith(f"_{base_name_lower}")
                or (
                    base_name_lower
                    and base_name_lower in entry_lower
                    and os.path.splitext(entry_lower)[1] in SUPPORTED_AUDIO_EXTENSIONS
                )
            ):
                mtime = os.path.getmtime(entry_path)
                if mtime > best_mtime:
                    best_mtime = mtime
                    best_match = entry_path

    return best_match or file_path


# ─── Input Schema ───
class SpeechToTextInput(BaseModel):
    file_path: str = Field(..., description="Absolute path to the audio file (WAV, MP3, OGG, FLAC, M4A, etc.)")


# ─── Main Tool ───
class SpeechToTextTool(BaseTool):
    name: str = "speech_to_text"
    description: str = (
        "Convert speech in an audio file to text. "
        "Supports WAV, MP3, OGG, FLAC, M4A, WEBM, MP4, WMA, AAC formats. "
        "Extracts spoken words and saves the transcription as a .txt file."
    )
    args_schema: Type[BaseModel] = SpeechToTextInput

    def _run(self, file_path: str) -> str:
        logger.info(f"[SpeechToText] Starting transcription for: {file_path}")

        # 1. Resolve file path
        resolved_path = _resolve_audio_path(file_path)
        if not resolved_path or not os.path.exists(resolved_path):
            return json.dumps({"error": f"Audio file not found: {file_path}"})

        # 2. Validate extension
        ext = os.path.splitext(resolved_path)[1].lower()
        if ext not in SUPPORTED_AUDIO_EXTENSIONS:
            return json.dumps({
                "error": f"Unsupported audio format: {ext}",
                "supported_formats": list(SUPPORTED_AUDIO_EXTENSIONS),
            })

        try:
            # 3. Convert to WAV if needed
            wav_path = _convert_to_wav(resolved_path)

            # 4. Transcribe — try Azure first, fall back to Google free API
            transcribed_text = ""
            engine_used = ""

            azure_key = os.getenv("AZURE_SPEECH_KEY", "")
            if azure_key:
                try:
                    transcribed_text = _transcribe_with_azure(wav_path)
                    engine_used = "azure_speech"
                except Exception as azure_err:
                    logger.warning(f"[STT] Azure Speech failed, falling back to Google: {azure_err}")

            if not transcribed_text:
                try:
                    transcribed_text = _transcribe_with_speech_recognition(wav_path)
                    engine_used = "google_free"
                except Exception as google_err:
                    logger.error(f"[STT] Google Speech Recognition failed: {google_err}")
                    return json.dumps({
                        "error": f"Transcription failed: {google_err}",
                        "hint": "Ensure the audio file contains clear speech.",
                    })

            if not transcribed_text or not transcribed_text.strip():
                return json.dumps({
                    "error": "No speech detected in the audio file.",
                    "engine": engine_used,
                })

            # 5. Save transcribed text to .txt file
            original_name = os.path.splitext(os.path.basename(resolved_path))[0]
            txt_filename = f"Transcription_{original_name}_{uuid.uuid4().hex[:6]}.txt"
            txt_path = os.path.join(OUTPUTS_DIR, txt_filename)

            with open(txt_path, "w", encoding="utf-8") as f:
                f.write(transcribed_text)

            logger.info(f"[SpeechToText] Transcription saved to: {txt_path}")

            # 6. Clean up temp WAV if we created one
            if wav_path != resolved_path and os.path.exists(wav_path):
                try:
                    os.remove(wav_path)
                except Exception:
                    pass

            return json.dumps({
                "status": "success",
                "engine": engine_used,
                "source_file": os.path.basename(resolved_path),
                "output_file": txt_path,
                "output_filename": txt_filename,
                "text_length": len(transcribed_text),
                "text_preview": transcribed_text[:5000],
                "full_text": transcribed_text,
            }, indent=2)

        except Exception as e:
            logger.error(f"[SpeechToText] Error: {e}")
            return json.dumps({"error": str(e)})
