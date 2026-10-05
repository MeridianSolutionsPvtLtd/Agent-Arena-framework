from azure.ai.contentsafety import ContentSafetyClient
from azure.core.credentials import AzureKeyCredential
from azure.core.exceptions import HttpResponseError
from azure.ai.contentsafety.models import AnalyzeTextOptions
from config import settings
from utils.logger import get_logger

logger = get_logger(__name__)


def analyze_text_safety(text: str, credentials: dict = None):
    creds = credentials or {}
    endpoint = creds.get("AZURE_CONTENT_SAFETY_ENDPOINT") or settings.AZURE_CONTENT_SAFETY_ENDPOINT
    key = creds.get("AZURE_CONTENT_SAFETY_API_KEY") or settings.AZURE_CONTENT_SAFETY_API_KEY

    if not endpoint or not key:
        logger.error("Azure Content Safety credentials missing")
        raise ValueError("Azure Content Safety credentials are not configured. Please add them in your profile.")

    client = ContentSafetyClient(endpoint, AzureKeyCredential(key))
    request = AnalyzeTextOptions(text=text)

    try:
        response = client.analyze_text(request)
        result = {}

        for item in response.categories_analysis:
            result[item.category.lower()] = {
                "severity": item.severity
            }
        return result

    except HttpResponseError as e:
        logger.error(f"Analyze text failed (HTTP Error): {e}", exc_info=True)
        raise e
    except Exception as e:
        logger.error(f"Analyze text failed: {e}", exc_info=True)
        raise e
