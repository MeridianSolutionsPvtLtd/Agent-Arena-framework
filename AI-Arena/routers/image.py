"""
routers/image.py
Image generation endpoint.
"""
from fastapi import APIRouter, HTTPException, Depends, Body

from services.image_service import generate_image
from services.keyvault_service import get_user_credentials
from middleware.hit_counter import increment_hit_count
from middleware.auth import get_current_user
from utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(
    prefix="/api/image",
    tags=["Image Generation"]
)


@router.post("/generate")
async def generate_image_endpoint(prompt: str = Body(..., embed=True), current_user: dict = Depends(get_current_user)):
    logger.info(f"Image generation requested by user {current_user['_id']}")
    try:
        # Increment hit count for OpenAI/Image
        await increment_hit_count(current_user["_id"], "openai")

        creds = await get_user_credentials(current_user["_id"], [
            "AZURE_OPENAI_IMAGE_ENDPOINT", "AZURE_OPENAI_IMAGE_API_KEY", "AZURE_OPENAI_IMAGE_DEPLOYMENT_NAME"
        ])

        image_url = await generate_image(prompt, credentials=creds)
        return {"image_url": image_url, "status": "success"}
    except Exception as e:
        logger.error(f"Image generation failed: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
