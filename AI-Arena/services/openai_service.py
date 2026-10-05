from openai import AsyncAzureOpenAI
from config import settings
from utils.logger import get_logger

logger = get_logger(__name__)


async def generate_chat_completion(messages: list, model: str = None, credentials: dict = None):
    """Generate chat completion using per-user or default credentials."""
    creds = credentials or {}
    endpoint = creds.get("AZURE_OPENAI_ENDPOINT") or settings.AZURE_OPENAI_ENDPOINT
    api_key = creds.get("AZURE_OPENAI_API_KEY") or settings.AZURE_OPENAI_API_KEY
    deployment_name = model or creds.get("AZURE_OPENAI_DEPLOYMENT_NAME") or settings.AZURE_OPENAI_DEPLOYMENT_NAME

    if not endpoint or not api_key:
        logger.error("Azure OpenAI credentials missing")
        raise ValueError("Azure OpenAI credentials are not configured. Please add them in your profile.")

    client = AsyncAzureOpenAI(
        azure_endpoint=endpoint,
        api_key=api_key,
        api_version="2025-01-01-preview"
    )

    # Format messages for multimodal support
    formatted_messages = []
    for msg in messages:
        if msg.get("images"):
            content = [{"type": "text", "text": msg["content"]}]
            for img_b64 in msg["images"]:
                url = img_b64 if img_b64.startswith("data:") else f"data:image/jpeg;base64,{img_b64}"
                content.append({
                    "type": "image_url",
                    "image_url": {"url": url}
                })
            formatted_messages.append({"role": msg["role"], "content": content})
        else:
            formatted_messages.append({"role": msg["role"], "content": msg["content"]})

    try:
        response = await client.chat.completions.create(
            model=deployment_name,
            messages=formatted_messages,
            temperature=0.7,
            max_tokens=4096,
            top_p=0.95,
            frequency_penalty=0,
            presence_penalty=0,
            stop=None,
            stream=False
        )
        usage = response.usage
        return response.choices[0].message.content, usage
    except Exception as e:
        logger.error(f"Error in OpenAI service: {e}", exc_info=True)
        raise e
