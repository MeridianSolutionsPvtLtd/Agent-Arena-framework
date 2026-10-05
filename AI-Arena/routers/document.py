"""
routers/document.py
Document Intelligence endpoint.
"""
from fastapi import APIRouter, HTTPException, Depends, File, UploadFile

from services.document_service import analyze_document
from services.keyvault_service import get_user_credentials
from services.blob_service import upload_user_file
from middleware.hit_counter import increment_hit_count
from middleware.auth import get_current_user
from utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(
    prefix="/api/document",
    tags=["Document Intelligence"]
)


@router.post("/analyze")
async def analyze_document_endpoint(file: UploadFile = File(...), current_user: dict = Depends(get_current_user)):
    logger.info(f"Document analysis requested by user {current_user['_id']}")
    try:
        await increment_hit_count(current_user["_id"], "document")

        creds = await get_user_credentials(current_user["_id"], [
            "AZURE_DOCUMENT_ENDPOINT", "AZURE_DOCUMENT_API_KEY"
        ])

        # 1. Upload to Blob Storage and update storage tracking
        blob_info = await upload_user_file(current_user["_id"], file)
        file_data = blob_info["content"]
        result = await analyze_document(file_data, credentials=creds)
        return {"result": result, "status": "success"}
    except HTTPException as he:
        raise he
    except Exception as e:
        logger.error(f"Document analysis failed: {str(e)}", exc_info=True, extra={"status_code": 500})
        raise HTTPException(status_code=500, detail=str(e))
