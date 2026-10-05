"""
Service logic for Group Discussion Agent.
"""
import os
import re
import json
import asyncio
import logging
from typing import Dict, Any, Optional
from agents.common.azure_agent_client import AzureAgentClient

from agents.group_discussion.prompts import get_gd_analysis_prompt
from agents.common.utils import extract_json_from_response

logger = logging.getLogger(__name__)

# Initialize Azure OpenAI Client
AZURE_OPENAI_API_KEY = os.getenv("AZURE_OPENAI_API_KEY", "")
AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT", "")
AZURE_OPENAI_DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME", "gpt-4o-aiteam")




async def analyze_gd(content: str, topic: str) -> Dict[str, Any]:
    """Analyze GD transcript/notes using Azure Agent."""
    # Using the same agent as ATS
    agent_id = os.getenv("ATS_AGENT_ID", "asst_cjcAshIAPbjB45xIfVIrYqVf")
    try:
        azure_agent = AzureAgentClient(agent_id)
    except Exception as e:
        logger.error(f"Failed to initialize Azure Agent for GD: {e}")
        return {"error": f"Agent init failed: {e}"}

    prompt = get_gd_analysis_prompt(content, topic)
    logger.info(f"GD Analysis: topic='{topic}', content_length={len(content)}")

    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: azure_agent.run_analysis(prompt)
        )

        result_str = result.get("response", "")
        logger.info(f"GD raw response length: {len(result_str) if result_str else 0}")

        if not result_str or not result_str.strip():
            logger.error("GD Analysis returned empty response from Agent")
            return {
                "structuredNotes": "The AI returned an empty response. Please try again.",
                "expectedResponses": [],
                "brainstormedStructure": "No structure available.",
                "sentiment": "Unknown",
                "key_takeaways": [],
                "error": "Empty response from AI"
            }

        GD_FALLBACK = {
            "structuredNotes": "Unable to process the notes.",
            "expectedResponses": [],
            "brainstormedStructure": "No structure available.",
            "sentiment": "Unknown",
            "key_takeaways": []
        }
        analysis = extract_json_from_response(result_str, fallback=GD_FALLBACK)
        analysis["thread_id"] = result.get("thread_id")
        analysis["token_usage"] = result.get("usage", {})
        return analysis

    except Exception as e:
        logger.error(f"GD Analysis Agent call failed: {e}", exc_info=True)
        return {
            "structuredNotes": f"Analysis failed: {str(e)}",
            "expectedResponses": [],
            "brainstormedStructure": "No structure available.",
            "sentiment": "Unknown",
            "key_takeaways": [],
            "error": str(e)
        }


async def process_gd_audio(audio_path: str, topic: str) -> Dict[str, Any]:
    """Full audio-to-analysis pipeline for GD."""
    from agents.call_audit.utils import convert_to_wav
    from agents.call_audit.service import _transcribe_with_diarization

    loop = asyncio.get_event_loop()

    # 1. Convert to WAV
    wav_path = audio_path.rsplit(".", 1)[0] + "_gd_conv.wav"
    success = await loop.run_in_executor(None, convert_to_wav, audio_path, wav_path)
    if not success:
        if audio_path.lower().endswith(".wav"):
            wav_path = audio_path
        else:
            raise Exception("Audio conversion failed")

    # 2. Transcribe
    transcription = await loop.run_in_executor(None, _transcribe_with_diarization, wav_path)

    # Cleanup WAV
    if wav_path != audio_path and os.path.exists(wav_path):
        os.remove(wav_path)

    # 3. Analyze
    return await analyze_gd(transcription["transcript"], topic)
