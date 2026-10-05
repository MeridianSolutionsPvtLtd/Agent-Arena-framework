"""
agents/data_insights/router.py
Data Insights agent endpoints.
"""
from typing import Optional

from fastapi import APIRouter, HTTPException, Depends, File, UploadFile, Form
from pydantic import BaseModel

from agents.data_insights.service import DataInsightsService
from services.blob_service import upload_user_file
from middleware.hit_counter import increment_hit_count
from middleware.auth import get_current_user
from utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/data-insights", tags=["Data Insights"])

data_insights_service_instance = DataInsightsService()


class DataInsightsTextAnalysisRequest(BaseModel):
    data: str
    context: Optional[str] = None


@router.post("/analyze/text")
async def data_insights_analyze_text(request: DataInsightsTextAnalysisRequest, user=Depends(get_current_user)):
    """Analyze raw text data."""
    try:
        result = await data_insights_service_instance.analyze_text(request.data, request.context)

        # Update hits
        token_count = result.get("token_usage", {}).get("total_tokens", 0)
        await increment_hit_count(user["_id"], "data_insights", target_field="agent_hits", tokens=token_count)

        return result
    except Exception as e:
        logger.error(f"Text analysis failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/analyze/file")
async def data_insights_analyze_file(
    file: UploadFile = File(...),
    context: Optional[str] = Form(None),
    user=Depends(get_current_user)
):
    """Analyze an uploaded CSV, Excel, or JSON file."""
    try:
        # 1. Upload to Blob Storage and update storage tracking
        blob_info = await upload_user_file(user["_id"], file)

        # 2. Analyze using the content from blob_info
        result = await data_insights_service_instance.analyze_file(blob_info["content"], file.filename, context)

        # Update hits
        token_count = result.get("token_usage", {}).get("total_tokens", 0)
        await increment_hit_count(user["_id"], "data_insights", target_field="agent_hits", tokens=token_count)

        return result
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except HTTPException as he:
        raise he
    except Exception as e:
        logger.error(f"File analysis failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
