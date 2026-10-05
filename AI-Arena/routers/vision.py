"""
routers/vision.py
Computer Vision endpoint.
"""
from fastapi import APIRouter, HTTPException, Depends, File, UploadFile

from services.vision_service import analyze_image
from services.keyvault_service import get_user_credentials
from middleware.hit_counter import increment_hit_count
from middleware.auth import get_current_user
from utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(
    prefix="/api/vision",
    tags=["Computer Vision"]
)


@router.post("/analyze")
async def analyze_image_endpoint(file: UploadFile = File(...), current_user: dict = Depends(get_current_user)):
    logger.info(f"Vision analysis requested by user {current_user['_id']}")
    try:
        await increment_hit_count(current_user["_id"], "vision")

        creds = await get_user_credentials(current_user["_id"], [
            "AZURE_VISION_ENDPOINT", "AZURE_VISION_API_KEY"
        ])

        image_data = await file.read()
        result = analyze_image(image_data, credentials=creds)

        response = {
            "caption": result.caption.text if result.caption else None,
            "tags": [tag.name for tag in result.tags.list] if result.tags else [],
            "confidence": result.caption.confidence if result.caption else None,
        }
        return {"result": response, "status": "success"}
    except Exception as e:
        logger.error(f"Vision analysis failed: {str(e)}", exc_info=True, extra={"status_code": 500})
        raise HTTPException(status_code=500, detail=str(e))
