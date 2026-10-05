import asyncio
import base64
import json
import uuid
import httpx

from config import settings
from utils.logger import get_logger

logger = get_logger(__name__)


async def generate_image(prompt: str, credentials: dict = None):
    """
    Generate an image using Azure OpenAI.

    Supports:
    - synchronous 200 responses
    - asynchronous 202 responses with operation-location polling
    - image URL responses
    - base64 image responses
    """
    creds = credentials or {}

    endpoint = creds.get("AZURE_OPENAI_IMAGE_ENDPOINT") or settings.AZURE_OPENAI_IMAGE_ENDPOINT
    api_key = creds.get("AZURE_OPENAI_IMAGE_API_KEY") or settings.AZURE_OPENAI_IMAGE_API_KEY
    deployment_name = creds.get("AZURE_OPENAI_IMAGE_DEPLOYMENT_NAME") or settings.AZURE_OPENAI_IMAGE_DEPLOYMENT_NAME

    if not endpoint or not api_key:
        logger.error(
            "Azure OpenAI Image credentials missing",
            extra={
                "has_endpoint": bool(endpoint),
                "has_api_key": bool(api_key),
                "has_deployment_name": bool(deployment_name),
            },
        )
        raise ValueError(
            "Azure OpenAI Image credentials are not configured. Please add them in your profile."
        )

    endpoint = endpoint.rstrip("/")

    # If user stored only the Azure OpenAI resource base URL:
    # Example: https://your-resource.openai.azure.com
    if "/openai/" not in endpoint:
        if not deployment_name:
            raise ValueError(
                "AZURE_OPENAI_IMAGE_DEPLOYMENT_NAME is required when only a base endpoint is provided."
            )

        # Azure docs show async image generation route with :submit and 202 Accepted
        # POST {endpoint}/openai/images/generations:submit?api-version=2023-10-01-preview
        url = f"{endpoint}/openai/images/generations:submit?api-version=2023-10-01-preview"

        # Some setups still require deployment-based route.
        # If your Azure resource specifically expects deployment route, switch to:
        # url = f"{endpoint}/openai/deployments/{deployment_name}/images/generations?api-version=2024-02-01"
    else:
        # Full URL provided directly in config
        url = endpoint

    headers = {
        "api-key": api_key,
        "Content-Type": "application/json",
        "Operation-Id": str(uuid.uuid4()),
    }

    payload = {
        "prompt": prompt,
        "n": 1,
        "size": "1024x1024",
    }

    logger.info(
        "Generating image with Azure OpenAI",
        extra={
            "url": url,
            "deployment_name": deployment_name,
            "payload": payload,
        },
    )

    timeout = httpx.Timeout(connect=30.0, read=180.0, write=30.0, pool=30.0)

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(url, headers=headers, json=payload)

            logger.info(
                "Initial image generation response received",
                extra={
                    "status_code": response.status_code,
                    "headers": dict(response.headers),
                },
            )

            # Case 1: synchronous success
            if response.status_code == 200:
                data = response.json()
                logger.info(f"Azure OpenAI Image Response: {json.dumps(data)}")
                return _extract_image_result(data)

            # Case 2: async accepted -> poll operation-location
            if response.status_code == 202:
                operation_location = response.headers.get("operation-location")

                if not operation_location:
                    logger.error(
                        "202 Accepted received but operation-location header missing",
                        extra={"headers": dict(response.headers)},
                    )
                    raise Exception(
                        "Image generation started, but operation-location header was missing."
                    )

                logger.info(
                    "Polling Azure image operation",
                    extra={"operation_location": operation_location},
                )

                for attempt in range(60):  # ~5 minutes max with 5 sec sleep
                    poll_response = await client.get(
                        operation_location,
                        headers={"api-key": api_key}
                    )

                    logger.info(
                        "Polled image operation",
                        extra={
                            "attempt": attempt + 1,
                            "status_code": poll_response.status_code,
                            "headers": dict(poll_response.headers),
                        },
                    )

                    if poll_response.status_code != 200:
                        error_text = poll_response.text
                        logger.error(
                            "Polling failed",
                            extra={
                                "status_code": poll_response.status_code,
                                "response_text": error_text,
                            },
                        )
                        raise Exception(f"Polling failed: {error_text}")

                    poll_data = poll_response.json()
                    logger.info(f"Azure image poll response: {json.dumps(poll_data)}")

                    status = str(poll_data.get("status", "")).lower()

                    if status in ("succeeded", "completed"):
                        # Azure may return final result in different shapes
                        result_data = poll_data.get("result", poll_data)
                        return _extract_image_result(result_data)

                    if status in ("failed", "canceled", "cancelled"):
                        raise Exception(
                            f"Image generation failed: {json.dumps(poll_data)}"
                        )

                    await asyncio.sleep(5)

                raise Exception("Image generation timed out while waiting for completion.")

            # Case 3: non-success response
            error_detail = response.text
            try:
                error_json = response.json()
                error_detail = error_json.get("error", {}).get("message", error_detail)
            except Exception:
                pass

            logger.error(
                "Image generation failed",
                extra={
                    "status_code": response.status_code,
                    "response_text": response.text,
                    "url": url,
                },
            )
            raise Exception(f"Image generation failed: {error_detail}")

    except httpx.ReadTimeout as e:
        logger.error("Azure image generation timed out", exc_info=True)
        raise Exception(
            "Image generation timed out. Azure took too long to respond."
        ) from e

    except Exception as e:
        logger.error(f"Error in image service: {e}", exc_info=True)
        raise


def _extract_image_result(data: dict):
    """
    Extract image result from Azure/OpenAI response.
    Returns either:
    - URL string
    - data:image/png;base64,... string
    """
    if not isinstance(data, dict):
        raise Exception("Unexpected image response format.")

    items = data.get("data", [])
    if not items or not isinstance(items, list):
        raise Exception("No image data found in response.")

    first = items[0]

    image_url = first.get("url")
    if image_url:
        return image_url

    b64_json = first.get("b64_json")
    if b64_json:
        return f"data:image/png;base64,{b64_json}"

    # Some providers may use a direct base64 field
    b64_data = first.get("base64")
    if b64_data:
        return f"data:image/png;base64,{b64_data}"

    raise Exception("No image URL or base64 image data found in response.")




