"""
routers/openai.py
OpenAI chat completion endpoint.
"""
from typing import Optional, List

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

from services.openai_service import generate_chat_completion
from services.keyvault_service import get_user_credentials
from middleware.hit_counter import increment_hit_count
from middleware.auth import get_current_user
from utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(
    prefix="/api/openai",
    tags=["OpenAI"]
)


class OpenAIMessage(BaseModel):
    role: str
    content: str
    images: Optional[List[str]] = None


class OpenAIChatRequest(BaseModel):
    messages: List[OpenAIMessage]
    model: Optional[str] = None


class OpenAIChatResponse(BaseModel):
    response: str
    status: str = "success"


@router.post("/chat", response_model=OpenAIChatResponse)
async def chat_completion(request: OpenAIChatRequest, current_user: dict = Depends(get_current_user)):
    logger.info("Chat completion requested", extra={"user_id": current_user["_id"]})
    try:
        # Get per-user credentials (falls back to .env defaults)
        creds = await get_user_credentials(current_user["_id"], [
            "AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_API_KEY", "AZURE_OPENAI_DEPLOYMENT_NAME"
        ])

        # Convert Pydantic models to dicts for the OpenAI client
        messages_data = []
        for msg in request.messages:
            m_dict = {"role": msg.role, "content": msg.content}
            if msg.images:
                m_dict["images"] = msg.images
            messages_data.append(m_dict)

        # Call generate_chat_completion service directly
        response_content, usage = await generate_chat_completion(
            messages=messages_data,
            model=request.model,
            credentials=creds
        )

        # Track usage with tokens
        token_count = usage.total_tokens if usage else 0
        await increment_hit_count(current_user["_id"], "openai", tokens=token_count)

        return OpenAIChatResponse(response=response_content)
    except Exception as e:
        logger.error(f"Chat completion failed: {str(e)}", exc_info=True, extra={"status_code": 500})
        raise HTTPException(status_code=500, detail=str(e))
