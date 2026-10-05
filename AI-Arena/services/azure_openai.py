"""
Azure OpenAI GPT-4 Service
Generates video summaries, key highlights, topic extraction, sentiment, and timeline 
by feeding combined vision + transcript data to GPT-4.
"""

import re
import json
import logging
from typing import List, Dict, Any, Optional

import httpx

from config import settings

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = """You are a professional video analyst. You receive two types of data about a video:

1. **Frame Analysis** — descriptions, tags, objects, and text detected in sampled video frames (with timestamps).
2. **Audio Transcript** — transcribed speech segments with timestamps.

Using this data, generate a comprehensive video analysis in **valid JSON** with exactly this structure:

{
  "concise_summary": "A detailed 3-5 sentence summary of the entire video content.",
  "key_highlights": [
    {"text": "highlight 1", "confidence": 0.95, "timestamp": 0.0},
    {"text": "highlight 2", "confidence": 0.90, "timestamp": 12.5}
  ],
  "topics": ["topic 1", "topic 2", ...],
  "sentiment": {
    "overall": "positive | negative | neutral | mixed",
    "score": 0.0,
    "breakdown": {"positive": 0.0, "negative": 0.0, "neutral": 0.0}
  },
  "timeline": [
    {
      "timestamp_seconds": 0.0,
      "event_type": "scene_change | speech | highlight | topic_shift",
      "description": "Exhaustive description of what happens",
      "ocr_text": "Text visible in frame if any"
    }
  ]
}

Be exhaustive and professional. Incorporate visual tags, detected objects, and OCR text from frames into your descriptions. Ensure the summary is comprehensive. Return ONLY the JSON object, no markdown fences or extra text. Confidence scores for highlights should be estimated based on the clarity of data provided. Output exactly 10 highlights if possible.
**CRITICAL**: The output must be valid RFC 8259 JSON. Ensure all property names are enclosed in double quotes and there are NO trailing commas at the end of arrays or objects.
"""


class AzureOpenAIService:
    """Uses Azure OpenAI GPT-4 to generate video summaries and insights."""

    def __init__(self):
        self.endpoint = settings.AZURE_OPENAI_ENDPOINT.rstrip("/")
        self.api_key = settings.AZURE_OPENAI_API_KEY
        self.deployment = settings.AZURE_OPENAI_DEPLOYMENT_NAME

    def _is_configured(self) -> bool:
        return (
            bool(self.endpoint)
            and bool(self.api_key)
            and "your-" not in self.api_key
        )

    async def generate_summary(
        self,
        frame_analyses: List[Dict[str, Any]],
        transcript_segments: List[Dict[str, Any]],
        video_metadata: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Send combined vision + transcript data to GPT-4 for summarization.

        Returns dict with concise_summary, key_highlights, topics, sentiment, timeline.
        """
        if not self._is_configured():
            return self._mock_summary(frame_analyses, transcript_segments, video_metadata)

        user_content = self._build_prompt(frame_analyses, transcript_segments, video_metadata)

        url = self.endpoint
        
        headers = {
            "api-key": self.api_key,
            "Content-Type": "application/json",
        }
        payload = {
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            "temperature": 0.5,
            "max_tokens": 4000,
        }

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(url, headers=headers, json=payload)
                response.raise_for_status()
                result = response.json()

            content = result["choices"][0]["message"]["content"]
            
            # Extract JSON if GPT included conversational text
            json_match = re.search(r"(\{.*\})", content, re.DOTALL)
            if json_match:
                json_str = json_match.group(1)
            else:
                json_str = content

            try:
                parsed = json.loads(json_str)
            except json.JSONDecodeError:
                # Fallback: try stripping common malformed characters
                logger.warning("Standard JSON parse failed, attempting cleanup...")
                json_str = json_str.strip().strip("`").strip()
                if json_str.startswith("json"): # common with markdown fences
                    json_str = json_str[4:].strip()
                parsed = json.loads(json_str)

            logger.info("GPT-4 summary generated and parsed successfully")
            return parsed

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse GPT-4 response as JSON: {e}")
            return self._mock_summary(frame_analyses, transcript_segments, video_metadata, error=str(e))
        except httpx.HTTPStatusError as e:
            logger.error(f"OpenAI API error: {e.response.status_code} – {e.response.text}")
            return self._mock_summary(frame_analyses, transcript_segments, video_metadata, error=str(e))
        except Exception as e:
            logger.error(f"OpenAI API call failed: {e}")
            return self._mock_summary(frame_analyses, transcript_segments, video_metadata, error=str(e))

    def _build_prompt(
        self,
        frame_analyses: List[Dict[str, Any]],
        transcript_segments: List[Dict[str, Any]],
        video_metadata: Dict[str, Any],
    ) -> str:
        """Build the user prompt from analysis data."""
        parts = [
            f"## Video Metadata",
            f"- Duration: {video_metadata.get('duration_seconds', 0):.1f} seconds",
            f"- Resolution: {video_metadata.get('resolution', 'unknown')}",
            f"- Frames analysed: {len(frame_analyses)}",
            "",
            "## Frame-by-Frame Analysis",
        ]
        for fa in frame_analyses:
            parts.append(
                f"**[{fa['timestamp']:.1f}s]** {fa['description']}  "
                f"Tags: {', '.join(fa.get('tags', [])[:10])}  "
                f"Objects: {', '.join(o['name'] for o in fa.get('objects', [])[:5])}  "
                f"Text: {'; '.join(fa.get('text_in_frame', [])[:3])}"
            )

        parts.append("")
        parts.append("## Audio Transcript")
        for seg in transcript_segments:
            parts.append(
                f"[{seg['start_seconds']:.1f}s–{seg['end_seconds']:.1f}s] {seg['text']}"
            )

        return "\n".join(parts)

    def _mock_summary(
        self,
        frame_analyses: List[Dict[str, Any]],
        transcript_segments: List[Dict[str, Any]],
        video_metadata: Dict[str, Any],
        error: str = None,
    ) -> Dict[str, Any]:
        """Return a mock summary when OpenAI is not configured."""
        note = (
            "Azure OpenAI credentials not configured"
            if not error
            else f"API error: {error}"
        )
        duration = video_metadata.get("duration_seconds", 0)

        return {
            "concise_summary": (
                f"[Demo] This is a {duration:.0f}-second video. "
                f"{len(frame_analyses)} frames and {len(transcript_segments)} speech segments were analyzed. "
                f"Note: {note}. Configure your Azure OpenAI credentials for real summarization."
            ),
            "key_highlights": [
                f"Video duration: {duration:.1f} seconds",
                f"Frames extracted: {len(frame_analyses)}",
                f"Speech segments: {len(transcript_segments)}",
                "Demo mode – no GPT analysis performed",
            ],
            "topics": ["video-analysis", "demo", "azure-ai"],
            "sentiment": {
                "overall": "neutral",
                "score": 0.0,
                "breakdown": {"positive": 0.33, "negative": 0.0, "neutral": 0.67},
            },
            "timeline": [
                {
                    "timestamp_seconds": 0.0,
                    "event_type": "scene_change",
                    "description": "Video begins",
                },
                {
                    "timestamp_seconds": duration / 2,
                    "event_type": "highlight",
                    "description": "Mid-point of video",
                },
                {
                    "timestamp_seconds": duration,
                    "event_type": "scene_change",
                    "description": "Video ends",
                },
            ],
        }
