"""
routers/speech.py
Speech service endpoints (TTS and STT).
"""
import asyncio

from fastapi import APIRouter, HTTPException, Depends, File, UploadFile, Form
from fastapi.responses import Response
from pydantic import BaseModel

from services.speech_service import text_to_speech, speech_to_text
from services.language_service import analyze_sentiment, extract_key_phrases, recognize_entities, detect_language
from services.keyvault_service import get_user_credentials
from services.blob_service import upload_user_file
from middleware.hit_counter import increment_hit_count
from middleware.auth import get_current_user
from utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(
    prefix="/api/speech",
    tags=["Speech Service"]
)


class SpeechTTSRequest(BaseModel):
    text: str


@router.post("/tts")
async def text_to_speech_endpoint(request: SpeechTTSRequest, current_user: dict = Depends(get_current_user)):
    logger.info(f"TTS requested by user {current_user['_id']}")
    try:
        await increment_hit_count(current_user["_id"], "speech")

        creds = await get_user_credentials(current_user["_id"], [
            "AZURE_SPEECH_KEY", "AZURE_SPEECH_REGION"
        ])

        audio_data = text_to_speech(request.text, credentials=creds)
        return Response(content=audio_data, media_type="audio/wav")
    except HTTPException as he:
        raise he
    except Exception as e:
        logger.error(f"TTS failed: {str(e)}", exc_info=True, extra={"status_code": 500})
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/stt")
async def speech_to_text_endpoint(
    file: UploadFile = File(...),
    auto_detect_language: bool = Form(False),
    enable_analytics: bool = Form(False),
    current_user: dict = Depends(get_current_user)
):
    logger.info(f"STT requested by user {current_user['_id']}")
    try:
        await increment_hit_count(current_user["_id"], "speech")

        creds = await get_user_credentials(current_user["_id"], [
            "AZURE_SPEECH_KEY", "AZURE_SPEECH_REGION",
            "AZURE_LANGUAGE_ENDPOINT", "AZURE_LANGUAGE_API_KEY"
        ])

        # 0. Upload to Blob Storage and update storage tracking
        blob_info = await upload_user_file(current_user["_id"], file)
        audio_data = blob_info["content"]

        # 1. Perform Speech-to-Text (now async with parallel chunks)
        stt_result = await speech_to_text(
            audio_data,
            credentials=creds,
            auto_detect_language=auto_detect_language
        )

        print("STT Result:", stt_result)

        full_text = stt_result.get("text", "")
        response_data = {
            "text": full_text,
            "stt_details": stt_result,
            "status": "success"
        }

        # 2. Perform Analytics if requested and text exists — ALL IN PARALLEL
        if enable_analytics and full_text.strip():
            logger.info("Performing post-transcription analytics in parallel...")
            analytics_results = {}
            documents = [full_text]

            try:
                loop = asyncio.get_event_loop()
                # Run all 4 analytics calls concurrently in thread pool
                sentiment_task = loop.run_in_executor(
                    None, analyze_sentiment, documents, creds
                )
                keyphrases_task = loop.run_in_executor(
                    None, extract_key_phrases, documents, creds
                )
                entities_task = loop.run_in_executor(
                    None, recognize_entities, documents, creds
                )
                language_task = loop.run_in_executor(
                    None, detect_language, documents, creds
                )

                # Wait for all to complete simultaneously
                (
                    analytics_results["sentiment"],
                    analytics_results["key_phrases"],
                    analytics_results["entities"],
                    analytics_results["detected_language"],
                ) = await asyncio.gather(
                    sentiment_task, keyphrases_task, entities_task, language_task
                )

                logger.info("⚡ All analytics completed in parallel")

            except Exception as analytics_err:
                logger.error(f"Analytics failed: {analytics_err}")
                analytics_results["error"] = str(analytics_err)

            response_data["analytics"] = analytics_results

        print("Response Data: ", response_data)
        return response_data

    except HTTPException as he:
        raise he
    except Exception as e:
        logger.error(f"STT failed: {str(e)}", exc_info=True, extra={"status_code": 500})
        raise HTTPException(status_code=500, detail=str(e))
