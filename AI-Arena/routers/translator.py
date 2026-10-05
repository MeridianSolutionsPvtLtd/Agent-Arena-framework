"""
routers/translator.py
Translation endpoint.
"""
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

from services.translator_service import translate_text
from services.keyvault_service import get_user_credentials
from middleware.hit_counter import increment_hit_count
from middleware.auth import get_current_user
from utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(
    prefix="/api/translator",
    tags=["Translator"]
)


class TranslatorTranslateRequest(BaseModel):
    text: str
    to_lang: str = "fr"


@router.post("/translate")
async def translate_endpoint(request: TranslatorTranslateRequest, current_user: dict = Depends(get_current_user)):
    logger.info(f"Translation requested by user {current_user['_id']} to language {request.to_lang}")
    try:
        await increment_hit_count(current_user["_id"], "translator")
        creds = await get_user_credentials(current_user["_id"], [
            "AZURE_TRANSLATOR_KEY", "AZURE_TRANSLATOR_REGION", "AZURE_TRANSLATOR_ENDPOINT"
        ])

        print("Creds: ", creds)
        result = translate_text(request.text, request.to_lang, credentials=creds)
        print("Result: ", result)
        return {"result": result, "status": "success"}
    except Exception as e:
        logger.error(f"Translation failed: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
