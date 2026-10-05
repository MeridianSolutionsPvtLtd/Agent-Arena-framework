import logging
from io import BytesIO
from typing import Optional, Dict
from bson import ObjectId
from fastapi import HTTPException, UploadFile
from database import get_db, get_users_collection
from utils.blob import upload_blob_from_file, delete_blob
from config import settings

logger = logging.getLogger(__name__)

async def upload_user_file(user_id: str, file: UploadFile) -> Dict:
    """
    Uploads a file to blob storage, checks limits, and updates user storage tracking in MongoDB.
    Returns metadata about the uploaded file.
    """
    db = get_db()
    users = get_users_collection()
    
    if db is None:
        logger.error("MongoDB Database connection is not initialized!")
        raise HTTPException(status_code=500, detail="Database connection error")

    # 1. Get user and check storage limit
    try:
        query_id = ObjectId(user_id) if isinstance(user_id, str) else user_id
        user = await users.find_one({"_id": query_id})
    except ValueError as ve:
        logger.error(f"Invalid user_id format: {user_id} - {ve}")
        raise HTTPException(status_code=400, detail=f"Invalid user ID format: {ve}")
    except HTTPException as he:
        # Re-raise HTTPExceptions to preserve status codes (404, 413, etc)
        raise he
    except Exception as e:
        logger.error(f"Error finding user {user_id}: {e}")
        raise HTTPException(status_code=500, detail=f"User lookup failed: {e}")

    if not user:
        logger.warning(f"User {user_id} not found in database.")
        raise HTTPException(status_code=404, detail="User not found")
        
    current_usage = user.get("storage_used_bytes", 0)
    limit = user.get("storage_limit_bytes", 500 * 1024 * 1024)
    
    print(f"--- STORAGE UPLOAD START ---")
    print(f"User: {user_id} | Name: {user.get('name')} | Usage: {current_usage/(1024*1024):.2f}MB")
    
    file_content = await file.read()
    file_size = len(file_content)
    print(f"File: {file.filename} | Size: {file_size/(1024*1024):.2f}MB")
    
    if current_usage + file_size > limit:
        print(f"!!! QUOTA EXCEEDED !!! Limit: {limit/(1024*1024):.0f}MB")
        raise HTTPException(
            status_code=413, 
            detail=f"Storage limit exceeded. Current: {current_usage/(1024*1024):.1f}MB, New: {file_size/(1024*1024):.1f}MB, Limit: {limit/(1024*1024):.0f}MB"
        )
        
    # 2. Upload to Blob Storage
    blob_name = f"{user_id}/{file.filename}"
    try:
        print(f"Attempting blob upload: {blob_name}")
        file_url = upload_blob_from_file(blob_name, BytesIO(file_content))
        print(f"Blob upload SUCCESS: {file_url}")
    except HTTPException as he:
        print(f"Blob upload FAILED (HTTP): {he.detail}")
        raise he
    except Exception as e:
        print(f"Blob upload FAILED (Unexpected): {e}")
        logger.error(f"Blob upload failed for {blob_name}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to upload file to storage: {e}")
        
    # 3. Update User Storage Usage
    try:
        from services.storage_service import increment_user_storage
        print(f"Updating database for user {user_id}... inc={file_size}")
        await increment_user_storage(user["_id"], file_size)
    except Exception as e:
        print(f"Database update FAILED: {e}")
        logger.error(f"Failed to update storage for {user_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to update storage usage in database")
    
    print(f"--- STORAGE UPLOAD COMPLETE ---")
    return {
        "filename": file.filename,
        "url": file_url,
        "size": file_size,
        "content_type": file.content_type,
        "blob_name": blob_name,
        "content": file_content
    }

async def delete_user_files(user_id: str, files: list):
    """
    Deletes files from blob storage and updates user storage tracking.
    'files' should be a list of dicts with 'size' and 'blob_name'.
    """
    if not files:
        return
        
    users = get_users_collection()
    total_freed = 0
    
    for f in files:
        blob_name = f.get("blob_name")
        size = f.get("size", 0)
        if blob_name:
            try:
                delete_blob(settings.CONTAINER_NAME, blob_name, is_prefix=False)
                total_freed += size
            except Exception as e:
                logger.error(f"Failed to delete blob {blob_name}: {e}")
                
    if total_freed > 0:
        from services.storage_service import increment_user_storage
        await increment_user_storage(user_id, -total_freed)
