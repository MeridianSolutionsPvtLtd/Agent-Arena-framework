from azure.ai.vision.imageanalysis import ImageAnalysisClient
from azure.ai.vision.imageanalysis.models import VisualFeatures
from azure.core.credentials import AzureKeyCredential
from config import settings
from utils.logger import get_logger

logger = get_logger(__name__)


def analyze_image(image_data: bytes, credentials: dict = None):
    creds = credentials or {}
    endpoint = creds.get("AZURE_VISION_ENDPOINT") or settings.AZURE_VISION_ENDPOINT
    key = creds.get("AZURE_VISION_API_KEY") or settings.AZURE_VISION_API_KEY

    if not endpoint or not key:
        logger.error("Azure Vision credentials missing")
        raise ValueError("Azure Vision credentials are not configured. Please add them in your profile.")

    client = ImageAnalysisClient(endpoint=endpoint, credential=AzureKeyCredential(key))

    try:
        result = client.analyze(
            image_data=image_data,
            visual_features=[
                VisualFeatures.CAPTION,
                VisualFeatures.READ,
                VisualFeatures.TAGS,
                VisualFeatures.OBJECTS
            ]
        )
        return result
    except Exception as e:
        logger.error(f"Error in Vision service: {e}", exc_info=True)
        raise e
