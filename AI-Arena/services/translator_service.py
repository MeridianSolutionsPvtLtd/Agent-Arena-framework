import requests, uuid
from config import settings
from utils.logger import get_logger

logger = get_logger(__name__)


def translate_text(text: str, to_lang: str = "fr", credentials: dict = None):
    creds = credentials or {}
    key = creds.get("AZURE_TRANSLATOR_KEY") or settings.AZURE_TRANSLATOR_KEY
    endpoint = creds.get("AZURE_TRANSLATOR_ENDPOINT") or settings.AZURE_TRANSLATOR_ENDPOINT
    region = creds.get("AZURE_TRANSLATOR_REGION") or settings.AZURE_TRANSLATOR_REGION

    print("Key: ", key)
    print("Endpoint: ", endpoint)
    print("Region: ", region)

    if not key or not endpoint or not region:
        logger.error("Azure Translator credentials missing")
        raise ValueError(
            "Azure Translator credentials are not configured correctly. "
            "Please add key, endpoint, and region in your profile."
        )
    path = '/translate'
    constructed_url = endpoint.rstrip('/') + path

    print("Constructed URL: ", constructed_url)

    params = {
        'api-version': '3.0',
        'to': [to_lang]
    }

    headers = {
        'Ocp-Apim-Subscription-Key': key,
        'Ocp-Apim-Subscription-Region': region,
        'Content-type': 'application/json',
        'X-ClientTraceId': str(uuid.uuid4())
    }

    body = [{'text': text}]

    response = requests.post(constructed_url, params=params, headers=headers, json=body)
    
    if response.status_code != 200:
        logger.error(f"Translator API failed: {response.text}", extra={"status_code": response.status_code})
        response.raise_for_status()

    return response.json()
