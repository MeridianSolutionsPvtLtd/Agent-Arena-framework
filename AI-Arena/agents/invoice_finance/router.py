"""
agents/invoice_finance/router.py
Invoice & Finance analysis endpoint.
"""
from fastapi import APIRouter, HTTPException, Depends, File, UploadFile

from agents.invoice_finance.service import InvoiceFinanceService
from services.blob_service import upload_user_file
from middleware.hit_counter import increment_hit_count
from middleware.auth import get_current_user
from utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/invoice-finance", tags=["Invoice & Finance"])

invoice_finance_service_instance = InvoiceFinanceService()


@router.post("/analyze")
async def invoice_finance_analyze_document(
    file: UploadFile = File(...),
    user=Depends(get_current_user)
):
    logger.info(f"Invoice/Finance analysis requested for file: {file.filename}")
    try:
        # 1. Upload to Blob Storage and update storage tracking
        blob_info = await upload_user_file(user["_id"], file)

        # 2. Analyze using the content from blob_info
        result = await invoice_finance_service_instance.analyze_document(blob_info["content"])

        # Update hits and symbolic tokens
        await increment_hit_count(user["_id"], "invoice_finance", target_field="agent_hits", tokens=50)

        return {"result": result, "status": "success"}
    except HTTPException as he:
        raise he
    except Exception as e:
        logger.error(f"Invoice/Finance analysis failed: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
