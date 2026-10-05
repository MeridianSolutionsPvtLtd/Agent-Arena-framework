"""
routers/content_safety.py
Content safety analysis endpoint.
"""
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

from services.content_safety_service import analyze_text_safety
from services.keyvault_service import get_user_credentials
from middleware.hit_counter import increment_hit_count
from middleware.auth import get_current_user
from utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(
    prefix="/api/content_safety",
    tags=["Content Safety"]
)


class ContentSafetyRequest(BaseModel):
    text: str


@router.post("/analyze")
async def safety_analysis(request: ContentSafetyRequest, current_user: dict = Depends(get_current_user)):
    logger.info(f"Content safety analysis requested by user {current_user['_id']}")
    try:
        await increment_hit_count(current_user["_id"], "content_safety")

        creds = await get_user_credentials(current_user["_id"], [
            "AZURE_CONTENT_SAFETY_ENDPOINT", "AZURE_CONTENT_SAFETY_API_KEY"
        ])

        result = analyze_text_safety(request.text, credentials=creds)
        return {"result": result, "status": "success"}
    except Exception as e:
        logger.error(f"Content safety analysis failed: {str(e)}", exc_info=True, extra={"status_code": 500})
        raise HTTPException(status_code=500, detail=str(e))
