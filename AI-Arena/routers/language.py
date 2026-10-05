"""
routers/language.py
Language service endpoints.
"""
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

from services.language_service import (
    analyze_sentiment,
    extract_key_phrases,
    recognize_entities,
    recognize_pii_entities,
    detect_language,
    summarize_text
)
import services.language_service
from services.keyvault_service import get_user_credentials
from middleware.hit_counter import increment_hit_count
from middleware.auth import get_current_user
from utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(
    prefix="/api/language",
    tags=["Language Service"]
)


class LanguageAnalysisRequest(BaseModel):
    text: str


@router.post("/analyze")
async def language_analysis(request: LanguageAnalysisRequest, current_user: dict = Depends(get_current_user)):
    logger.info(f"Language analysis requested by user {current_user['_id']}")
    try:
        await increment_hit_count(current_user["_id"], "language")

        creds = await get_user_credentials(current_user["_id"], [
            "AZURE_LANGUAGE_ENDPOINT", "AZURE_LANGUAGE_API_KEY"
        ])

        results = analyze_sentiment([request.text], credentials=creds)
        if results and "error" in results[0]:
            logger.warning(f"Language analysis warning: {results[0]['message']}")
            raise HTTPException(status_code=400, detail=results[0]["message"])
        return {"result": results[0], "status": "success"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Language analysis failed: {str(e)}", exc_info=True, extra={"status_code": 500})
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/key_phrases")
async def extract_key_phrases_api(request: LanguageAnalysisRequest, current_user: dict = Depends(get_current_user)):
    try:
        await increment_hit_count(current_user["_id"], "language")
        creds = await get_user_credentials(current_user["_id"], ["AZURE_LANGUAGE_ENDPOINT", "AZURE_LANGUAGE_API_KEY"])
        results = services.language_service.extract_key_phrases([request.text], credentials=creds)
        return {"result": results[0], "status": "success"}
    except Exception as e:
        logger.error(f"Key phrase extraction failed: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/entities")
async def recognize_entities_api(request: LanguageAnalysisRequest, current_user: dict = Depends(get_current_user)):
    try:
        await increment_hit_count(current_user["_id"], "language")
        creds = await get_user_credentials(current_user["_id"], ["AZURE_LANGUAGE_ENDPOINT", "AZURE_LANGUAGE_API_KEY"])
        results = recognize_entities([request.text], credentials=creds)
        return {"result": results[0], "status": "success"}
    except Exception as e:
        logger.error(f"Entity recognition failed: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/pii")
async def recognize_pii_entities_api(request: LanguageAnalysisRequest, current_user: dict = Depends(get_current_user)):
    try:
        await increment_hit_count(current_user["_id"], "language")
        creds = await get_user_credentials(current_user["_id"], ["AZURE_LANGUAGE_ENDPOINT", "AZURE_LANGUAGE_API_KEY"])
        results = recognize_pii_entities([request.text], credentials=creds)
        return {"result": results[0], "status": "success"}
    except Exception as e:
        logger.error(f"PII recognition failed: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/detect_language")
async def detect_language_api(request: LanguageAnalysisRequest, current_user: dict = Depends(get_current_user)):
    try:
        await increment_hit_count(current_user["_id"], "language")
        creds = await get_user_credentials(current_user["_id"], ["AZURE_LANGUAGE_ENDPOINT", "AZURE_LANGUAGE_API_KEY"])
        results = detect_language([request.text], credentials=creds)
        return {"result": results[0], "status": "success"}
    except Exception as e:
        logger.error(f"Language detection failed: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/summarize")
async def summarize_text_api(request: LanguageAnalysisRequest, current_user: dict = Depends(get_current_user)):
    try:
        await increment_hit_count(current_user["_id"], "language")
        creds = await get_user_credentials(current_user["_id"], ["AZURE_LANGUAGE_ENDPOINT", "AZURE_LANGUAGE_API_KEY"])
        results = summarize_text([request.text], credentials=creds)
        return {"result": results[0], "status": "success"}
    except Exception as e:
        logger.error(f"Text summarization failed: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
