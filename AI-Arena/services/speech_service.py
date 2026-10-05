import azure.cognitiveservices.speech as speechsdk
import os
import tempfile
from config import settings
from utils.logger import get_logger

logger = get_logger(__name__)


def text_to_speech(text: str, credentials: dict = {}):
    creds = credentials or {}
    key = creds.get("AZURE_SPEECH_KEY") or settings.AZURE_SPEECH_KEY
    region = creds.get("AZURE_SPEECH_REGION") or settings.AZURE_SPEECH_REGION

    if not key or not region:
        logger.error("Azure Speech credentials missing")
        raise ValueError("Azure Speech credentials are not configured. Please add them in your profile.")

    speech_config = speechsdk.SpeechConfig(subscription=key, region=region)
    speech_config.speech_synthesis_voice_name = 'en-US-AvaMultilingualNeural'

    synthesizer = speechsdk.SpeechSynthesizer(speech_config=speech_config, audio_config=None)
    result = synthesizer.speak_text_async(text).get()

    if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
        return result.audio_data
    elif result.reason == speechsdk.ResultReason.Canceled:
        cancellation_details = result.cancellation_details
        logger.warning(f"Speech synthesis canceled: {cancellation_details.reason}")
        if cancellation_details.reason == speechsdk.CancellationReason.Error:
            logger.error(f"Error details: {cancellation_details.error_details}")
        raise Exception("Speech synthesis failed")


import time
import asyncio
import httpx

# ── Concurrency controls ──
MAX_CONCURRENT_STT_CHUNKS = 10  # Max parallel Azure Speech REST requests


async def speech_to_text(audio_data: bytes, credentials: dict = {},
                   auto_detect_language: bool = False):
    """
    Convert speech audio to text using Azure Speech REST API.
    PARALLEL chunk processing — up to 10 concurrent requests.
    No SDK needed — pure HTTP calls, works in all environments including AKS.
    """
    import wave
    import io
    import math

    creds = credentials or {}
    key = creds.get("AZURE_SPEECH_KEY") or settings.AZURE_SPEECH_KEY
    region = creds.get("AZURE_SPEECH_REGION") or settings.AZURE_SPEECH_REGION

    if not key or not region:
        logger.error("[STT] Azure Speech credentials missing")
        raise ValueError("Azure Speech credentials are not configured.")

    # ── Determine speech region ──
    speech_region = region
    if speech_region.startswith("http"):
        try:
            speech_region = speech_region.split("//")[1].split(".")[0]
            logger.info(f"[STT] Auto-corrected region to '{speech_region}'")
        except Exception:
            pass

    logger.info(f"[STT] Using Region: {speech_region}")

    # ── Convert to WAV ──
    wav_data = _convert_to_wav(audio_data)
    logger.info(f"[STT] WAV data size: {len(wav_data)} bytes")

    # ── Extract PCM from WAV ──
    try:
        with wave.open(io.BytesIO(wav_data), 'rb') as wf:
            channels = wf.getnchannels()
            sample_width = wf.getsampwidth()
            framerate = wf.getframerate()
            n_frames = wf.getnframes()
            pcm_data = wf.readframes(n_frames)
            logger.info(
                f"[STT] WAV: {channels}ch, {sample_width*8}bit, {framerate}Hz, "
                f"{n_frames} frames, {len(pcm_data)} PCM bytes"
            )
    except Exception as e:
        logger.error(f"[STT] Failed to parse WAV: {e}", exc_info=True)
        raise ValueError(f"Failed to parse WAV data: {e}")

    if len(pcm_data) < 100:
        logger.warning(f"[STT] PCM data too small ({len(pcm_data)} bytes)")
        return {"text": "", "segments": []}

    # ── REST API endpoint ──
    language = "en-US"
    url = (
        f"https://{speech_region}.stt.speech.microsoft.com"
        "/speech/recognition/conversation/cognitiveservices/v1"
        f"?language={language}&format=detailed"
    )
    headers = {
        "Ocp-Apim-Subscription-Key": key,
        "Content-Type": f"audio/pcm; samplerate={framerate}; encoding=s16le; channels={channels}",
    }

    logger.info(f"[STT] Using REST API: {url}")

    # ── Chunk audio into ≤15-second segments (smaller = faster per-chunk) ──
    bytes_per_second = framerate * sample_width * channels
    chunk_duration_seconds = 15
    chunk_size = bytes_per_second * chunk_duration_seconds

    total_bytes = len(pcm_data)
    num_chunks = math.ceil(total_bytes / chunk_size)
    logger.info(
        f"[STT] Splitting into {num_chunks} chunks ({chunk_duration_seconds}s each) "
        f"— up to {MAX_CONCURRENT_STT_CHUNKS} in parallel"
    )

    # ── Semaphore for controlled parallelism ──
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_STT_CHUNKS)

    async def _transcribe_chunk(i: int, client: httpx.AsyncClient):
        """Transcribe a single chunk. Returns result dict or None."""
        async with semaphore:
            start_byte = i * chunk_size
            end_byte = min((i + 1) * chunk_size, total_bytes)
            chunk_payload = pcm_data[start_byte:end_byte]

            if not chunk_payload:
                return None

            time_offset = start_byte / bytes_per_second
            logger.info(
                f"[STT] Sending chunk {i + 1}/{num_chunks} "
                f"({len(chunk_payload)} bytes, offset {time_offset:.1f}s)"
            )

            try:
                response = await client.post(url, headers=headers, content=chunk_payload)

                if response.status_code != 200:
                    logger.error(
                        f"[STT] Chunk {i + 1} failed "
                        f"(HTTP {response.status_code}): {response.text[:300]}"
                    )
                    return None

                result = response.json()
                status = result.get("RecognitionStatus")

                if status == "Success":
                    nbest = result.get("NBest", [])
                    if nbest:
                        best = nbest[0]
                        text = best.get("Display", result.get("DisplayText", ""))
                        if text.strip():
                            offset_ticks = result.get("Offset", 0)
                            duration_ticks = result.get("Duration", 0)
                            logger.info(f"[STT] Chunk {i + 1} OK: '{text.strip()[:60]}...'")
                            return {
                                "chunk_index": i,
                                "text": text.strip(),
                                "offset": offset_ticks,
                                "duration": duration_ticks,
                                "speaker_id": "Guest"
                            }
                elif status == "NoMatch":
                    logger.info(f"[STT] Chunk {i + 1}: No speech detected")
                elif status == "InitialSilenceTimeout":
                    logger.info(f"[STT] Chunk {i + 1}: Silence")
                else:
                    logger.warning(f"[STT] Chunk {i + 1} unexpected: {status}")

            except httpx.TimeoutException:
                logger.error(f"[STT] Chunk {i + 1} timed out")
            except Exception as e:
                logger.error(f"[STT] Chunk {i + 1} error: {e}", exc_info=True)

            return None

    # ── Fire all chunks in parallel ──
    trans_start = time.time()
    limits = httpx.Limits(max_connections=MAX_CONCURRENT_STT_CHUNKS + 2, max_keepalive_connections=MAX_CONCURRENT_STT_CHUNKS)
    async with httpx.AsyncClient(timeout=120.0, limits=limits) as client:
        chunk_results = await asyncio.gather(
            *[_transcribe_chunk(i, client) for i in range(num_chunks)]
        )

    # ── Re-assemble in order ──
    rec_results = [cr for cr in chunk_results if cr is not None]
    # Sort by chunk_index to maintain order (gather preserves order, but be safe)
    rec_results.sort(key=lambda x: x["chunk_index"])

    logger.info(
        f"[STT] ⚡ Parallel transcription complete: {len(rec_results)} segments "
        f"in {time.time() - trans_start:.2f}s"
    )

    full_text = " ".join([r["text"] for r in rec_results])
    return {"text": full_text, "segments": rec_results}


def _convert_to_wav(audio_data: bytes) -> bytes:
    """Convert audio bytes (webm/opus or any ffmpeg-supported format) to WAV PCM."""
    from pydub import AudioSegment
    import io

    # Detect format by checking magic bytes
    # Use startswith for bytes
    suffix = ".webm"
    if audio_data.startswith(b'RIFF'):
        suffix = ".wav"

    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp_in:
        tmp_in.write(audio_data)
        tmp_in_path = tmp_in.name

    try:
        audio = AudioSegment.from_file(tmp_in_path)
        audio = audio.set_channels(1).set_frame_rate(16000).set_sample_width(2)

        wav_buffer = io.BytesIO()
        audio.export(wav_buffer, format="wav")
        return wav_buffer.getvalue()
    except Exception as e:
        logger.error(f"Audio conversion error: {e}", exc_info=True)
        raise ValueError(f"Failed to convert audio to WAV: {str(e)}")
    finally:
        os.unlink(tmp_in_path)
