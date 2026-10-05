import logging
from bson import ObjectId
import json
from database import get_db, get_users_collection
from utils.blob import get_blob_service_client
from config import settings
from azure.core.exceptions import ResourceNotFoundError

logger = logging.getLogger(__name__)

async def calculate_user_storage(user_id: str) -> int:
    """
    Recalculates the total storage used by a user by summing:
    1. Size of all blobs in Azure (physical files)
    2. Estimated size of all chat documents in MongoDB (JSON data)
    Updates the User document and returns the total bytes.
    """
    db = get_db()
    users = get_users_collection()
    chats_col = db["chats"]
    
    user_oid = ObjectId(user_id) if isinstance(user_id, str) else user_id
    total_bytes = 0

    # 1. Sum all Blobs in Azure
    try:
        blob_service_client = get_blob_service_client()
        container_client = blob_service_client.get_container_client(settings.CONTAINER_NAME)
        # Blobs are prefixed with user_id/
        prefix = f"{str(user_oid)}/"
        blobs = container_client.list_blobs(name_starts_with=prefix)
        for blob in blobs:
            total_bytes += blob.size or 0
    except ResourceNotFoundError:
        logger.warning(f"Container {settings.CONTAINER_NAME} not found during storage sync for {user_id}")
    except Exception as e:
        logger.error(f"Error listing blobs for storage sync: {e}")

    # 2. Sum JSON size of all Chats in MongoDB
    try:
        cursor = chats_col.find({"user_id": str(user_oid)})
        async for chat in cursor:
            # We estimate BSON size by converting to JSON string length
            # A more accurate way in MongoDB is Object.bsonsize(doc), but via Motor:
            chat_str = json.dumps(chat, default=str)
            total_bytes += len(chat_str.encode('utf-8'))
    except Exception as e:
        logger.error(f"Error summing chat sizes for storage sync: {e}")

    # 3. Update User document
    await users.update_one(
        {"_id": user_oid},
        {"$set": {"storage_used_bytes": total_bytes}}
    )

    logger.info(f"Storage sync complete for {user_id}: {total_bytes} bytes total.")
    return total_bytes

async def increment_user_storage(user_id: str, bytes_to_add: int):
    """
    Atomically increments the user's storage usage.
    """
    users = get_users_collection()
    user_oid = ObjectId(user_id) if isinstance(user_id, str) else user_id
    
    await users.update_one(
        {"_id": user_oid},
        {"$inc": {"storage_used_bytes": bytes_to_add}}
    )
