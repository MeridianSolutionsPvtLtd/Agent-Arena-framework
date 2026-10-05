"""
Azure Computer Vision Service
Analyzes extracted video frames using Azure Computer Vision 4.0 API.
"""

import base64
import logging
from typing import List, Dict, Any, Tuple

import httpx

from config import settings

logger = logging.getLogger(__name__)

# Azure Computer Vision 4.0 Analyze endpoint
ANALYZE_URL_TEMPLATE = "{endpoint}computervision/imageanalysis:analyze?api-version=2024-02-01&features=caption,tags,objects,smartCrops,read"


class AzureVisionService:
    """Calls Azure Computer Vision to analyze video frames."""

    def __init__(self):
        self.endpoint = settings.AZURE_VIDEO_VISION_ENDPOINT.rstrip("/")
        self.api_key = settings.AZURE_VIDEO_VISION_API_KEY

    def _is_configured(self) -> bool:
        return bool(self.endpoint) and bool(self.api_key) and "your-" not in self.api_key

    async def analyze_frame(
        self, frame_path: str, timestamp: float
    ) -> Dict[str, Any]:
        """
        Analyze a single frame image using Azure Computer Vision.

        Returns a dict with description, tags, objects, brands, dominant_colors.
        """
        print("A")
        if not self._is_configured():
            return self._mock_analysis(frame_path, timestamp)
        print("B")
        url = ANALYZE_URL_TEMPLATE.format(endpoint=self.endpoint + "/")
        headers = {
            "Ocp-Apim-Subscription-Key": self.api_key,
            "Content-Type": "application/octet-stream",
        }
        print("C")
        with open(frame_path, "rb") as f:
            image_data = f.read()

        try:
            print("D")
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(url, headers=headers, content=image_data)
                print("E")
                response.raise_for_status()
                result = response.json()
            print("F")
            return self._parse_response(result, timestamp)

        except httpx.HTTPStatusError as e:
            # Handle "Feature 'Caption' is not supported in this region" error (400)
            if e.response.status_code == 400 and "Caption" in e.response.text:
                print("G")
                logger.warning("Vision API 'caption' feature not supported in this region. Retrying without it.")
                try:
                    # Fallback URL without caption feature
                    fallback_url = self.endpoint + "/computervision/imageanalysis:analyze?api-version=2024-02-01&features=tags,objects,smartCrops,read"
                    async with httpx.AsyncClient(timeout=30.0) as client:
                        print("H")
                        response = await client.post(fallback_url, headers=headers, content=image_data)
                        print("I")
                        response.raise_for_status()
                        result = response.json()
                    return self._parse_response(result, timestamp)
                except Exception as retry_err:
                    print("J")  
                    logger.error(f"Vision API fallback failed: {retry_err}")
                    return self._mock_analysis(frame_path, timestamp, error=str(retry_err))

            logger.error(f"Vision API error ({e.response.status_code}): {e.response.text}")
            return self._mock_analysis(frame_path, timestamp, error=str(e))
        except Exception as e:
            print("K")
            logger.error(f"Vision API call failed: {e}")
            return self._mock_analysis(frame_path, timestamp, error=str(e))

    def _parse_response(self, result: dict, timestamp: float) -> Dict[str, Any]:
        """Parse the Azure Vision API JSON response."""
        caption = result.get("captionResult", {}).get("text", "No description available")
        tags = [
            t["name"]
            for t in result.get("tagsResult", {}).get("values", [])
            if t.get("confidence", 0) > 0.5
        ]
        objects = []
        for obj in result.get("objectsResult", {}).get("values", []):
            objects.append({
                "name": obj.get("tags", [{}])[0].get("name", "unknown") if obj.get("tags") else "unknown",
                "confidence": obj.get("tags", [{}])[0].get("confidence", 0) if obj.get("tags") else 0,
                "bounding_box": obj.get("boundingBox", {}),
            })

        # Extract brands from tags (tags containing brand-like names)
        brands = [
            t["name"]
            for t in result.get("tagsResult", {}).get("values", [])
            if t.get("confidence", 0) > 0.7 and any(
                keyword in t["name"].lower()
                for keyword in ["logo", "brand", "sign", "text"]
            )
        ]

        # Read results (OCR text found in frame)
        read_text = []
        for block in result.get("readResult", {}).get("blocks", []):
            for line in block.get("lines", []):
                read_text.append(line.get("text", ""))

        return {
            "timestamp": timestamp,
            "description": caption,
            "tags": tags,
            "objects": objects,
            "brands": brands,
            "text_in_frame": read_text,
        }

    def _mock_analysis(
        self, frame_path: str, timestamp: float, error: str = None
    ) -> Dict[str, Any]:
        """Return a mock analysis when API is not configured."""
        note = "Azure Vision credentials not configured" if not error else f"API error: {error}"
        return {
            "timestamp": timestamp,
            "description": f"[Demo] Scene at {timestamp:.1f}s – {note}",
            "tags": ["demo", "scene", "video-frame"],
            "objects": [
                {"name": "object", "confidence": 0.85, "bounding_box": {"x": 50, "y": 50, "w": 200, "h": 200}}
            ],
            "brands": [],
            "text_in_frame": [],
        }

    async def analyze_frames(
        self, frames: List[Tuple[str, float]]
    ) -> List[Dict[str, Any]]:
        """Analyze multiple frames in parallel. Limits to 15 frames max to stay within API quotas."""
        import asyncio

        # Sample evenly if we have too many frames
        if len(frames) > 15:
            step = len(frames) // 15
            frames = frames[::step][:15]

        # Use a semaphore to limit concurrent API calls (avoid throttling)
        semaphore = asyncio.Semaphore(5)

        async def _analyze_with_limit(frame_path: str, timestamp: float):
            async with semaphore:
                return await self.analyze_frame(frame_path, timestamp)

        # Run all frame analyses concurrently
        results = await asyncio.gather(
            *[_analyze_with_limit(fp, ts) for fp, ts in frames]
        )

        logger.info(f"Analyzed {len(results)} frames with Azure Vision (parallel)")
        return list(results)
