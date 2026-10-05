"""
routers/search.py
Azure Cognitive Search endpoints.
"""
from typing import List, Any

from fastapi import APIRouter, HTTPException, Depends, File, UploadFile
from pydantic import BaseModel

from services.search_service import search_documents, upload_and_index_document, list_indexed_documents, delete_document
from services.keyvault_service import get_user_credentials
from middleware.hit_counter import increment_hit_count
from middleware.auth import get_current_user
from utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(
    prefix="/api/search",
    tags=["Search"]
)

SEARCH_CRED_KEYS = ["AZURE_SEARCH_ENDPOINT", "AZURE_SEARCH_API_KEY"]
SEARCH_ALLOWED_EXTENSIONS = {"pdf", "docx", "txt", "md", "csv", "json", "log"}
SEARCH_MAX_FILE_SIZE = 10 * 1024 * 1024


class CognitiveSearchRequest(BaseModel):
    query: str
    top: int = 10


class CognitiveSearchResponse(BaseModel):
    results: List[Any]
    status: str = "success"


@router.post("/query", response_model=CognitiveSearchResponse)
async def query_search(request: CognitiveSearchRequest, current_user: dict = Depends(get_current_user)):
    logger.info(f"Search query from user {current_user['_id']}: {request.query}")
    try:
        await increment_hit_count(current_user["_id"], "search")
        creds = await get_user_credentials(current_user["_id"], SEARCH_CRED_KEYS)
        results = await search_documents(
            query=request.query,
            top=request.top,
            credentials=creds,
            user_id=current_user["_id"]
        )
        logger.info(f"Search returned {len(results)} results.")
        return CognitiveSearchResponse(results=results)
    except Exception as e:
        logger.error(f"Search failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/upload")
async def upload_document(file: UploadFile = File(...), current_user: dict = Depends(get_current_user)):
    logger.info(f"Document upload from user {current_user['_id']}: {file.filename}")

    # Validate file extension
    ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    if ext not in SEARCH_ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type: .{ext}. Allowed: {', '.join(sorted(SEARCH_ALLOWED_EXTENSIONS))}",
        )

    file_data = await file.read()

    # Validate file size
    if len(file_data) > SEARCH_MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail="File too large. Maximum size is 10 MB.")

    if len(file_data) == 0:
        raise HTTPException(status_code=400, detail="File is empty.")

    try:
        await increment_hit_count(current_user["_id"], "search")
        creds = await get_user_credentials(current_user["_id"], SEARCH_CRED_KEYS)
        doc_meta = await upload_and_index_document(
            file_data=file_data,
            filename=file.filename,
            credentials=creds,
            user_id=current_user["_id"]
        )
        logger.info(f"Document indexed: {doc_meta['id']}")
        return {"document": doc_meta, "status": "success"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Upload failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/documents")
async def get_documents(current_user: dict = Depends(get_current_user)):
    try:
        creds = await get_user_credentials(current_user["_id"], SEARCH_CRED_KEYS)
        docs = await list_indexed_documents(
            credentials=creds,
            user_id=current_user["_id"]
        )
        return {"documents": docs, "status": "success"}
    except Exception as e:
        logger.error(f"List documents failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/documents/{doc_id}")
async def remove_document(doc_id: str, current_user: dict = Depends(get_current_user)):
    logger.info(f"Delete document {doc_id} by user {current_user['_id']}")
    try:
        creds = await get_user_credentials(current_user["_id"], SEARCH_CRED_KEYS)
        await delete_document(
            doc_id=doc_id,
            credentials=creds,
            user_id=current_user["_id"]
        )
        return {"status": "success", "message": f"Document {doc_id} deleted."}
    except Exception as e:
        logger.error(f"Delete failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
