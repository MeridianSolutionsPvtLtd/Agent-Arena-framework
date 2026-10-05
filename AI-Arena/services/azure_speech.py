"""
Azure Speech-to-Text Service (PARALLEL optimized)
Transcribes audio extracted from video using Azure Speech REST API.
Up to 10 concurrent chunk requests for maximum speed.
"""

import os
import logging
import math
import asyncio
import time
from typing import List, Dict, Any, Optional

import httpx

from config import settings

logger = logging.getLogger(__name__)

# ── Concurrency controls ──
MAX_CONCURRENT_CHUNKS = 10


class AzureSpeechService:
    """Transcribes audio using Azure Speech-to-Text REST API — parallel chunks."""

    def __init__(self):
        self.speech_key = settings.AZURE_VIDEO_SPEECH_KEY
        self.speech_region = settings.AZURE_VIDEO_SPEECH_REGION
        
        # Auto-fix region if it's a URL
        if self.speech_region.startswith("http"):
            try:
                self.speech_region = self.speech_region.split("//")[1].split(".")[0]
                logger.warning(f"Auto-corrected speech region to '{self.speech_region}'")
            except Exception:
                pass

    def _is_configured(self) -> bool:
        return (
            bool(self.speech_key)
            and bool(self.speech_region)
            and "your-" not in self.speech_key
        )

    async def transcribe_audio(
        self, audio_path: Optional[str]
    ) -> List[Dict[str, Any]]:
        """
        Transcribe an audio WAV file using Azure Speech REST API.
        Returns a list of transcript segment dicts with start, end, text.
        """
        if audio_path is None:
            logger.info("No audio file provided – skipping transcription")
            return []

        if not self._is_configured():
            return self._mock_transcription()

        url = (
            f"https://{self.speech_region}.stt.speech.microsoft.com"
            "/speech/recognition/conversation/cognitiveservices/v1"
            "?language=en-US&format=detailed"
        )
        headers = {
            "Ocp-Apim-Subscription-Key": self.speech_key,
            "Content-Type": "audio/wav; codecs=audio/pcm; samplerate=16000",
        }

        try:
            file_size = os.path.getsize(audio_path)
            logger.info(f"Transcribing audio: {file_size / 1024:.1f} KB")

            segments = await self._transcribe_chunks_parallel(audio_path, url, headers)
            logger.info(f"Transcription produced {len(segments)} segments")
            return segments

        except Exception as e:
            logger.error(f"Speech transcription failed: {e}")
            return self._mock_transcription(error=str(e))

    async def _transcribe_chunks_parallel(
        self, audio_path: str, url: str, headers: dict
    ) -> List[Dict[str, Any]]:
        """
        Send audio in ≤15-second raw PCM chunks — UP TO 10 IN PARALLEL.
        """
        # Update headers for raw PCM
        headers = dict(headers)
        headers["Content-Type"] = "audio/pcm; samplerate=16000; encoding=s16le; channels=1"

        try:
            with open(audio_path, "rb") as f:
                # WAV header is 44 bytes. Skip it to get raw PCM.
                f.read(44)
                audio_data = f.read()

            # PCM 16-bit Mono 16kHz = 32000 bytes/sec
            # 15 seconds = 480,000 bytes (smaller chunks = faster individual responses)
            bytes_per_second = 32000
            chunk_duration = 15
            chunk_size = bytes_per_second * chunk_duration
            
            total_bytes = len(audio_data)
            num_chunks = math.ceil(total_bytes / chunk_size)
            
            logger.info(
                f"Chunking raw audio ({total_bytes} bytes) into {num_chunks} segments "
                f"({chunk_duration}s each) — up to {MAX_CONCURRENT_CHUNKS} in parallel"
            )

            # ── Semaphore for controlled parallelism ──
            semaphore = asyncio.Semaphore(MAX_CONCURRENT_CHUNKS)

            async def _process_chunk(i: int, client: httpx.AsyncClient) -> Optional[Dict]:
                async with semaphore:
                    start_byte = i * chunk_size
                    end_byte = min((i + 1) * chunk_size, total_bytes)
                    chunk_payload = audio_data[start_byte:end_byte]
                    
                    if not chunk_payload:
                        return None
                        
                    time_offset = start_byte / bytes_per_second
                    logger.info(f"Uploading transcript chunk {i+1}/{num_chunks} (time offset: {time_offset:.1f}s)")

                    try:
                        response = await client.post(url, headers=headers, content=chunk_payload)
                        if response.status_code != 200:
                            logger.error(f"Chunk {i+1} failed ({response.status_code}): {response.text[:300]}")
                            return None
                            
                        result = response.json()
                        if result.get("RecognitionStatus") == "Success":
                            nbest = result.get("NBest", [])
                            if nbest:
                                best = nbest[0]
                                text = best.get("Display", result.get("DisplayText", ""))
                                duration_ticks = result.get("Duration", 0)
                                offset_ticks = result.get("Offset", 0)
                                
                                chunk_start_s = offset_ticks / 10_000_000
                                absolute_start_s = time_offset + chunk_start_s
                                duration_s = duration_ticks / 10_000_000
                                
                                logger.info(f"Chunk {i+1} Success: found '{text[:40]}...'")
                                
                                return {
                                    "chunk_index": i,
                                    "start_seconds": round(absolute_start_s, 2),
                                    "end_seconds": round(absolute_start_s + duration_s, 2),
                                    "text": text,
                                    "confidence": best.get("Confidence", None),
                                }
                        elif result.get("RecognitionStatus") == "NoMatch":
                            logger.debug(f"No speech in chunk {i+1}")
                        else:
                            logger.warning(f"Chunk {i+1} unexpected status: {result.get('RecognitionStatus')}")
                    except Exception as chunk_err:
                        logger.error(f"Error processing chunk {i+1}: {chunk_err}")
                    
                    return None

            # ── Fire all chunks in parallel ──
            trans_start = time.time()
            limits = httpx.Limits(
                max_connections=MAX_CONCURRENT_CHUNKS + 2,
                max_keepalive_connections=MAX_CONCURRENT_CHUNKS
            )
            async with httpx.AsyncClient(timeout=120.0, limits=limits) as client:
                chunk_results = await asyncio.gather(
                    *[_process_chunk(i, client) for i in range(num_chunks)]
                )

            # ── Re-assemble in order ──
            segments = [cr for cr in chunk_results if cr is not None]
            segments.sort(key=lambda x: x["chunk_index"])
            # Remove chunk_index from final output
            for seg in segments:
                seg.pop("chunk_index", None)

            logger.info(f"⚡ Parallel transcription: {len(segments)} segments in {time.time() - trans_start:.2f}s")
            return segments

        except Exception as e:
            logger.error(f"Critical error in _transcribe_chunks_parallel: {e}")
            return self._mock_transcription(error=str(e))

    def _mock_transcription(self, error: str = None) -> List[Dict[str, Any]]:
        """Return mock transcript when API is not configured."""
        note = (
            "Azure Speech credentials not configured"
            if not error
            else f"API error: {error}"
        )
        return [
            {
                "start_seconds": 0.0,
                "end_seconds": 5.0,
                "text": f"[Demo transcript] Welcome to the video. ({note})",
                "confidence": 0.95,
            },
            {
                "start_seconds": 5.0,
                "end_seconds": 12.0,
                "text": "[Demo transcript] This is a demonstration of the video summarisation pipeline.",
                "confidence": 0.92,
            },
            {
                "start_seconds": 12.0,
                "end_seconds": 20.0,
                "text": "[Demo transcript] The system extracts frames and audio, then uses AI to generate insights.",
                "confidence": 0.90,
            },
        ]
