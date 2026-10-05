"""
Call Audit Service — the core pipeline (ULTRA-OPTIMIZED).
1. Convert audio to WAV  +  Pre-initialize Azure Agent (concurrent)
2. Transcribe with Azure Speech REST API — parallel chunks (HTTP/2 + global client)
3. Analyze with Azure OpenAI (gpt-4o) — parallel transcript chunking
4. Merge results — Restores single object for frontend compatibility (Fixes "N/A" issue)
"""
import os
import json
import tempfile
import asyncio
import logging
import time
import math
import httpx
import wave
from io import BytesIO
from typing import Optional, List, Dict, Any

from config import settings
from agents.common.azure_agent_client import AzureAgentClient
from .utils import convert_to_wav, get_audio_duration
from .prompts import get_analysis_prompt

logger = logging.getLogger(__name__)

# ── Configuration ──
AZURE_SPEECH_KEY = os.getenv("AZURE_SPEECH_KEY") or settings.AZURE_SPEECH_KEY
AZURE_SPEECH_REGION = os.getenv("AZURE_SPEECH_REGION") or settings.AZURE_SPEECH_REGION

# ── Concurrency & Performance ──
MAX_CONCURRENT_STT_CHUNKS = 50  # Azure S0 capacity
STT_CHUNK_DURATION_SECONDS = 8  # Faster individual responses
GPT_CHUNK_MAX_CHARS = 4000      # Split transcript for parallel GPT

# 🚀 GLOBAL HTTP CLIENT (connection reuse + HTTP/2)
HTTP_CLIENT = httpx.AsyncClient(
    http2=True,
    timeout=60.0,
    limits=httpx.Limits(max_connections=100, max_keepalive_connections=100)
)


# 🔥 AZURE WARMUP (avoids cold start latency)
async def warmup_azure_stt():
    try:
        speech_region = AZURE_SPEECH_REGION
        if speech_region.startswith("http"):
            speech_region = speech_region.split("//")[1].split(".")[0]

        url = f"https://{speech_region}.stt.speech.microsoft.com/speech/recognition/conversation/cognitiveservices/v1?language=en-IN"

        await HTTP_CLIENT.post(
            url,
            headers={"Ocp-Apim-Subscription-Key": AZURE_SPEECH_KEY},
            content=b"00"
        )

        logger.info("🔥 Azure STT warmed up")

    except Exception as e:
        logger.warning(f"Warmup failed: {e}")


# ── Dynamic Tuning Helpers ──

def _parse_duration(duration) -> float:
    if isinstance(duration, (int, float)):
        return float(duration)
    if isinstance(duration, str):
        try:
            parts = duration.split(':')
            if len(parts) == 3:
                return float(parts[0])*3600 + float(parts[1])*60 + float(parts[2])
            elif len(parts) == 2:
                return float(parts[0])*60 + float(parts[1])
            else:
                return float(parts[0])
        except Exception:
            return 300.0  # fallback to 5 minutes
    return 300.0

def compute_chunk_duration(duration_sec) -> int:
    """
    🔥 CHANGE:
    Small audio → VERY LARGE chunks (reduce API calls)
    Large audio → balanced chunking
    """
    d = _parse_duration(duration_sec)

    if d <= 3 * 60:
        return 8

    elif d <= 10 * 60:
        return 10

    elif d <= 30 * 60:
        return 12

    else:
        return 15


def compute_gpt_chunk_size(duration_sec) -> int:
    d = _parse_duration(duration_sec)
    if d < 5 * 60:
        return 3000
    elif d < 20 * 60:
        return 5000
    else:
        return 8000


def adjust_concurrency(num_chunks: int, duration_sec: float) -> int:
    """
    🔥 CHANGE:
    Small audio → LOW concurrency (avoid overhead)
    Large audio → scale up
    """
    d = _parse_duration(duration_sec)

    if d <= 3 * 60:
        return min(2, num_chunks)

    if num_chunks < 10:
        return num_chunks
    elif num_chunks < 50:
        return 20
    elif num_chunks < 150:
        return 50
    else:
        return 80


def _init_agent_client() -> Optional[AzureAgentClient]:
    """Pre-initialize the Azure Agent client (runs in thread pool)."""
    agent_id = os.getenv("CALL_AUDIT_AGENT_ID", "asst_ZH6eJ2lC272d2uZszXVQu9yz")
    try:
        client = AzureAgentClient(agent_id)
        logger.info("🤖 Agent pre-initialized successfully")
        return client
    except Exception as e:
        logger.error(f"Failed to pre-initialize Azure Agent: {e}")
        return None

def _run_agent_analysis(agent_client: Optional[AzureAgentClient], transcript_text: str, segment_context: str) -> dict:
    """Run analysis using a pre-initialized agent. Returns parsed JSON."""
    if agent_client is None:
        agent_id = os.getenv("CALL_AUDIT_AGENT_ID", "asst_ZH6eJ2lC272d2uZszXVQu9yz")
        try:
            agent_client = AzureAgentClient(agent_id)
        except Exception as e:
            logger.error(f"Agent fallback init failed: {e}")
            return {"analysis": {"error": f"Agent init failed: {e}"}, "usage": {}}

    prompt = get_analysis_prompt(transcript_text, segment_context)
    result = agent_client.run_analysis(prompt)
    raw = result.get("response", "").strip()

    # Clean markdown
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
        if raw.endswith("```"): raw = raw[:-3]
        raw = raw.strip()

    try:
        analysis_result = json.loads(raw)
    except json.JSONDecodeError:
        logger.error(f"Failed to parse Agent JSON: {raw[:500]}")
        analysis_result = {"error": "JSON parse error", "raw": raw[:1000]}

    return {
        "analysis": analysis_result,
        "usage": result.get("usage", {}) or {},
        "thread_id": result.get("thread_id"),
    }



async def _transcribe_with_rest_api(wav_path: str) -> dict:
    """Parallelized transcription pipeline with HTTP/2 and global client."""
    if not os.path.exists(wav_path):
        raise FileNotFoundError(f"WAV not found: {wav_path}")

    with wave.open(wav_path, 'rb') as wf:
        channels = wf.getnchannels()
        sample_width = wf.getsampwidth()
        framerate = wf.getframerate()
        n_frames = wf.getnframes()
        pcm_data = wf.readframes(n_frames)

    duration_sec = n_frames / framerate

    def _wav_payload(pcm_chunk: bytes) -> bytes:
        """Wrap raw PCM frames in the WAV container required by Azure STT."""
        output = BytesIO()
        with wave.open(output, "wb") as chunk_wav:
            chunk_wav.setnchannels(channels)
            chunk_wav.setsampwidth(sample_width)
            chunk_wav.setframerate(framerate)
            chunk_wav.writeframes(pcm_chunk)
        return output.getvalue()

    # 🔥 Dynamic tuning
    chunk_duration = compute_chunk_duration(duration_sec)
    bytes_per_second = framerate * sample_width * channels
    chunk_size = int(bytes_per_second * chunk_duration)

    total_bytes = len(pcm_data)
    num_chunks = math.ceil(total_bytes / chunk_size)

    # max_concurrency = adjust_concurrency(num_chunks)
    max_concurrency = adjust_concurrency(num_chunks, duration_sec)
    semaphore = asyncio.Semaphore(max_concurrency)

    logger.info(f"""
    🎯 Dynamic STT Config:
    Duration: {duration_sec:.2f}s
    Chunk Duration: {chunk_duration}s
    Num Chunks: {num_chunks}
    Concurrency: {max_concurrency}
    """)

    speech_region = AZURE_SPEECH_REGION
    if speech_region.startswith("http"):
        speech_region = speech_region.split("//")[1].split(".")[0]

    url = f"https://{speech_region}.stt.speech.microsoft.com/speech/recognition/conversation/cognitiveservices/v1?language=en-IN&format=detailed"
    headers = {
        "Ocp-Apim-Subscription-Key": AZURE_SPEECH_KEY,
        "Content-Type": f"audio/wav; codecs=audio/pcm; samplerate={framerate}",
        "Accept": "application/json",
    }

    # 🚀 ULTRA FAST PATH FOR SMALL AUDIO (<= 3 min)
    if duration_sec <= 180:
        logger.info("⚡ Using FAST PATH for small audio")
    
        try:
            response = await HTTP_CLIENT.post(
                url, headers=headers, content=_wav_payload(pcm_data)
            )
    
            if response.status_code == 200:
                result = response.json()
    
                if result.get("RecognitionStatus") == "Success":
                    nbest = result.get("NBest", [])
                    if nbest:
                        text = nbest[0].get("Display", "").strip()
    
                        if text:
                            return {
                                "transcript": f"[00:00:00] Speaker 1: {text}",
                                "segments": [{
                                    "speaker": "Speaker 1",
                                    "text": text,
                                    "timestamp": "00:00:00",
                                    "offset_seconds": 0,
                                    "duration_seconds": duration_sec,
                                }]
                            }
    
        except Exception as e:
            logger.warning("Fast path failed, falling back: %r", e)

    # bytes_per_second = framerate * sample_width * channels
    # chunk_size = bytes_per_second * STT_CHUNK_DURATION_SECONDS
    # total_bytes = len(pcm_data)
    # num_chunks = math.ceil(total_bytes / chunk_size)

    # semaphore = asyncio.Semaphore(MAX_CONCURRENT_STT_CHUNKS)

    async def _transcribe_single_chunk(i: int):
        async with semaphore:
            start_byte = i * chunk_size
            end_byte = min((i + 1) * chunk_size, total_bytes)
            chunk_payload = pcm_data[start_byte:end_byte]
            if not chunk_payload: return None

            retries = 3
            backoff = 1

            for attempt in range(retries):
                try:
                    response = await HTTP_CLIENT.post(
                        url, headers=headers, content=_wav_payload(chunk_payload)
                    )
                    if response.status_code == 429:
                        await asyncio.sleep(backoff)
                        backoff *= 2
                        continue
                    if response.status_code != 200:
                        if attempt == retries - 1:
                            logger.warning(
                                "STT chunk %s failed with status %s",
                                i,
                                response.status_code,
                            )
                        return None
                    result = response.json()

                    if result.get("RecognitionStatus") == "Success":
                        nbest = result.get("NBest", [])
                        if not nbest:
                            return None

                        best = nbest[0]
                        text = best.get("Display", "").strip()

                        if not text:
                            return None

                        absolute_start = (start_byte / bytes_per_second) + (
                            result.get("Offset", 0) / 10_000_000
                        )

                        return {
                            "chunk_index": i,
                            "text": text,
                            "offset_seconds": absolute_start,
                            "duration_seconds": result.get("Duration", 0) / 10_000_000,
                        }
                    if attempt == retries - 1:
                        logger.warning(
                            "STT chunk %s recognition status: %s",
                            i,
                            result.get("RecognitionStatus"),
                        )

                except Exception as exc:
                    if attempt == retries - 1:
                        logger.warning("STT chunk %s failed with exception: %r", i, exc)
                    await asyncio.sleep(backoff)
                    backoff *= 2

            return None

    tasks = [asyncio.create_task(_transcribe_single_chunk(i)) for i in range(num_chunks)]
    segments = []
    transcript_parts = []
    speaker_counter = 0

    for coro in asyncio.as_completed(tasks):
        cr = await coro
        if cr:
            speaker_counter += 1
            speaker = f"Speaker {(speaker_counter % 2) + 1}"
            ts = int(cr["offset_seconds"])
            ts_str = f"{ts//3600:02d}:{(ts%3600)//60:02d}:{ts%60:02d}"

            segments.append({
                "speaker": speaker, "text": cr["text"], "timestamp": ts_str,
                "offset_seconds": round(cr["offset_seconds"], 2),
                "duration_seconds": round(cr["duration_seconds"], 2),
            })
            transcript_parts.append(f"[{ts_str}] {speaker}: {cr['text']}")

    segments.sort(key=lambda x: x["offset_seconds"])
    if segments:
        return {
            "transcript": "\n".join(
                f"[{segment['timestamp']}] {segment['speaker']}: {segment['text']}"
                for segment in segments
            ),
            "segments": segments,
        }

    logger.warning(
        "Primary chunked STT produced no text. Retrying with conservative settings."
    )

    conservative_chunk_duration = 6
    conservative_chunk_size = int(bytes_per_second * conservative_chunk_duration)
    conservative_num_chunks = math.ceil(total_bytes / conservative_chunk_size)
    conservative_semaphore = asyncio.Semaphore(1)

    async def _transcribe_conservative_chunk(i: int):
        async with conservative_semaphore:
            start_byte = i * conservative_chunk_size
            end_byte = min((i + 1) * conservative_chunk_size, total_bytes)
            chunk_payload = pcm_data[start_byte:end_byte]
            if not chunk_payload:
                return None

            try:
                response = await HTTP_CLIENT.post(
                    url, headers=headers, content=_wav_payload(chunk_payload)
                )
                if response.status_code != 200:
                    logger.warning(
                        "Conservative STT chunk %s failed with status %s",
                        i,
                        response.status_code,
                    )
                    return None
                result = response.json()
                if result.get("RecognitionStatus") != "Success":
                    return None
                nbest = result.get("NBest", [])
                if not nbest:
                    return None
                text = nbest[0].get("Display", "").strip()
                if not text:
                    return None
                absolute_start = (start_byte / bytes_per_second) + (
                    result.get("Offset", 0) / 10_000_000
                )
                return {
                    "text": text,
                    "offset_seconds": absolute_start,
                    "duration_seconds": result.get("Duration", 0) / 10_000_000,
                }
            except Exception as exc:
                logger.warning("Conservative STT chunk %s failed with exception: %r", i, exc)
                return None

    conservative_tasks = [
        asyncio.create_task(_transcribe_conservative_chunk(i))
        for i in range(conservative_num_chunks)
    ]
    conservative_segments = []
    conservative_transcript_parts = []
    speaker_counter = 0
    for coro in asyncio.as_completed(conservative_tasks):
        cr = await coro
        if cr:
            speaker_counter += 1
            speaker = f"Speaker {(speaker_counter % 2) + 1}"
            ts = int(cr["offset_seconds"])
            ts_str = f"{ts//3600:02d}:{(ts%3600)//60:02d}:{ts%60:02d}"
            conservative_segments.append({
                "speaker": speaker,
                "text": cr["text"],
                "timestamp": ts_str,
                "offset_seconds": round(cr["offset_seconds"], 2),
                "duration_seconds": round(cr["duration_seconds"], 2),
            })
            conservative_transcript_parts.append(f"[{ts_str}] {speaker}: {cr['text']}")

    conservative_segments.sort(key=lambda x: x["offset_seconds"])
    return {
        "transcript": "\n".join(
            f"[{segment['timestamp']}] {segment['speaker']}: {segment['text']}"
            for segment in conservative_segments
        ),
        "segments": conservative_segments,
    }

def _merge_analysis_results(chunks: list) -> dict:
    """Intelligently merges parallel analysis results into a single object (Fixes N/A)."""
    if not chunks: return {}
    
    # Filter out empty or error chunks
    valid_chunks = [c for c in chunks if isinstance(c, dict) and "error" not in c]
    if not valid_chunks: return chunks[0] if chunks else {}

    # Use first valid chunk as the base template
    merged = json.loads(json.dumps(valid_chunks[0]))

    # 1. Merge Bullet Points
    all_bullets = []
    for chunk in valid_chunks:
        bullets = chunk.get("Call_Summary", {}).get("Summary_Bullet_Points", [])
        if isinstance(bullets, list):
            for b in bullets:
                if b not in all_bullets: all_bullets.append(b)
    merged.setdefault("Call_Summary", {})["Summary_Bullet_Points"] = all_bullets

    # 2. Merge Audio Markers
    all_markers = []
    for chunk in valid_chunks:
        markers = chunk.get("Audio_Markers", [])
        if isinstance(markers, list): all_markers.extend(markers)
    try:
        all_markers.sort(key=lambda x: x.get("time", "00:00:00"))
    except: pass
    merged["Audio_Markers"] = all_markers

    # 3. Numeric Scores (Averaging)
    score_keys = ["Professionalism", "Product_Knowledge", "Communication_Skills", "Problem_Solving"]
    score_totals = {k: 0 for k in score_keys}
    scored_count = 0
    for chunk in valid_chunks:
        s = chunk.get("Scores", {})
        if s and any(s.get(k, 0) > 0 for k in score_keys):
            scored_count += 1
            for k in score_keys: 
                val = s.get(k, 0)
                # Clamp to 10 if LLM hallucinates higher numbers
                if isinstance(val, (int, float)) and val > 10:
                    val = 10
                score_totals[k] += val
    
    if scored_count > 0:
        avg_scores = {k: round(score_totals[k] / scored_count) for k in score_keys}
        total_sum = sum(avg_scores.values())
        avg_scores["TotalScore"] = total_sum
        if total_sum >= 32: avg_scores["Category"] = "Excellent"
        elif total_sum >= 20: avg_scores["Category"] = "Average"
        else: avg_scores["Category"] = "Poor"
        merged["Scores"] = avg_scores

    # 4. Audit Parameters (OR logic for Yes)
    if "Audit_Parameters" in merged:
        for chunk in valid_chunks:
            p = chunk.get("Audit_Parameters", {})
            for k, v in p.items():
                if str(v).lower() in ["yes", "true"]: merged["Audit_Parameters"][k] = v

    # 5. Metadata/Eligibility (Fill non-empty)
    for chunk in valid_chunks:
        meta = chunk.get("Call_Metadata", {})
        elig = chunk.get("Eligibility", {})
        if merged["Call_Metadata"].get("Agent_Name") in ["not provided", ""]:
            merged["Call_Metadata"]["Agent_Name"] = meta.get("Agent_Name", "not provided")
        if merged["Call_Metadata"].get("Student_Name") in ["not provided", ""]:
            merged["Call_Metadata"]["Student_Name"] = meta.get("Student_Name", "not provided")
        if merged["Eligibility"].get("DOB") in ["not provided", ""]:
            merged["Eligibility"]["DOB"] = elig.get("DOB", "not provided")

    # 6. Call Status (OR logic for disconnection)
    for chunk in valid_chunks:
        cs = chunk.get("Call_Status", {})
        if str(cs.get("Call_Disconnected")).lower() == "true":
            merged.setdefault("Call_Status", {})["Call_Disconnected"] = "True"

    return merged

async def analyze_audio(audio_path: str):
    """Full parallel pipeline with result merging."""
    start_time = time.time()
    loop = asyncio.get_event_loop()

    yield {"status": "converting", "log": "Initializing pipeline & converting audio..."}
    os.makedirs(os.path.join(os.path.dirname(__file__), ".tmp"), exist_ok=True)
    with tempfile.NamedTemporaryFile(suffix=".wav", dir=os.path.join(os.path.dirname(__file__), ".tmp"), delete=False) as tmp:
        wav_path = tmp.name

    try:
        # Run conversion and agent warmup in parallel
        success, agent_client = await asyncio.gather(
            loop.run_in_executor(None, convert_to_wav, audio_path, wav_path),
            loop.run_in_executor(None, _init_agent_client),
        )
        if not success: raise Exception("WAV conversion failed")

        # Transcribe & Get Duration
        yield {"status": "transcribing", "log": "Parallel transcription in progress..."}
        transcription, duration = await asyncio.gather(
            _transcribe_with_rest_api(wav_path),
            get_audio_duration(wav_path),
        )

        transcript = transcription["transcript"]
        if not transcript or not transcript.strip():
            raise Exception("Transcription produced no text. Please retry with clearer audio.")

        # Parallel GPT Analysis
        yield {"status": "analyzing", "log": "Running parallel AI audit chunks..."}

        segment_context = "\n".join([f"[{s['timestamp']}] {s['speaker']}: {s['text']}" for s in transcription["segments"]])
        
        # Split and Analyze
        gpt_chunk_size = compute_gpt_chunk_size(duration)

        parts = [
            transcript[i:i+gpt_chunk_size]
            for i in range(0, len(transcript), gpt_chunk_size)
        ]
        
        # parts = [transcript[i:i+GPT_CHUNK_MAX_CHARS] for i in range(0, len(transcript), GPT_CHUNK_MAX_CHARS)]
        analysis_tasks = [loop.run_in_executor(None, _run_agent_analysis, agent_client, p, segment_context) for p in parts]
        results = await asyncio.gather(*analysis_tasks)

        # 🚀 MERGE CHUNKS (Fixes "N/A" in frontend)
        final_analysis = _merge_analysis_results([r.get("analysis") for r in results])

        total_tokens = sum(
            int((r.get("usage", {}) or {}).get("total_tokens", 0) or 0)
            for r in results
        )

        total_time = time.time() - start_time
        yield {
            "status": "complete",
            "log": f"Call audit completed in {total_time:.1f}s",
            "result": {
                "duration": duration,
                "transcript": transcript,
                "segments": transcription["segments"],
                "analysis": final_analysis,
                "token_usage": {"total_tokens": total_tokens},
                "thread_id": results[0].get("thread_id") if results else None
            }
        }

    finally:
        if 'wav_path' in locals() and os.path.exists(wav_path):
            try: os.remove(wav_path)
            except: pass
