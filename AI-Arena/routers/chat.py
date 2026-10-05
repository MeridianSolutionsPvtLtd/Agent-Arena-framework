"""
routers/chat.py
Chat history management endpoints.
"""
import asyncio
import json
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Depends, File, UploadFile
from fastapi.responses import StreamingResponse
from bson import ObjectId

from models.chat import CreateChatRequest, UpdateChatRequest, GenerateTitleRequest
from services.storage_service import calculate_user_storage, increment_user_storage
from services.blob_service import upload_user_file, delete_user_files
from services.keyvault_service import get_user_credentials
from services.openai_service import generate_chat_completion
from database import get_db
from middleware.auth import get_current_user
from utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/chats", tags=["Chat History"])


def _chat_history_collection():
    return get_db()["chats"]


# ── Static paths registered BEFORE dynamic /{chat_id} routes ──────────

@router.post("/generate-title")
async def generate_title(body: GenerateTitleRequest, current_user: dict = Depends(get_current_user)):
    """Generate a short chat title from the first few messages using OpenAI."""
    try:
        creds = await get_user_credentials(current_user["_id"], [
            "AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_API_KEY", "AZURE_OPENAI_DEPLOYMENT_NAME"
        ])

        # Build a concise prompt for title generation
        conversation = ""
        for msg in body.messages[:4]:
            role = msg.get("role", "user")
            content = msg.get("content", "")[:200]
            conversation += f"{role}: {content}\n"

        title_messages = [
            {"role": "system", "content": "Generate a concise, descriptive title (max 6 words) for this conversation. Ignore generic greetings like 'hi' or 'hello'. Focus on the core request, topic, or uploaded file mentioned in the user's messages. Return ONLY the title text, nothing else. No quotes."},
            {"role": "user", "content": conversation},
        ]

        title_text, _ = await generate_chat_completion(
            messages=title_messages,
            model=None,
            credentials=creds,
        )

        title = title_text.strip().strip('"').strip("'")[:60]
        return {"title": title}

    except Exception as e:
        logger.error(f"Title generation failed: {e}", exc_info=True)
        return {"title": "New Chat"}


@router.post("/generate-title-stream")
async def generate_title_stream(body: GenerateTitleRequest, current_user: dict = Depends(get_current_user)):
    """Generate a chat title and stream it character by character."""
    try:
        creds = await get_user_credentials(current_user["_id"], [
            "AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_API_KEY", "AZURE_OPENAI_DEPLOYMENT_NAME"
        ])

        conversation = ""
        for msg in body.messages[:4]:
            role = msg.get("role", "user")
            content = msg.get("content", "")[:200]
            conversation += f"{role}: {content}\n"

        title_messages = [
            {"role": "system", "content": "Generate a concise, descriptive title (max 6 words) for this conversation. Ignore generic greetings like 'hi' or 'hello'. Focus on the core request, topic, or uploaded file mentioned in the user's messages. Return ONLY the title text, nothing else. No quotes."},
            {"role": "user", "content": conversation},
        ]

        title_text, _ = await generate_chat_completion(
            messages=title_messages,
            model=None,
            credentials=creds,
        )

        title = title_text.strip().strip('"').strip("'")[:60]

        async def stream_chars():
            for char in title:
                yield f"data: {json.dumps({'char': char})}\n\n"
                await asyncio.sleep(0.04)
            yield f"data: {json.dumps({'done': True, 'title': title})}\n\n"

        return StreamingResponse(stream_chars(), media_type="text/event-stream")

    except Exception as e:
        logger.error(f"Streaming title generation failed: {e}", exc_info=True)

        async def error_stream():
            yield f"data: {json.dumps({'done': True, 'title': 'New Chat'})}\n\n"

        return StreamingResponse(error_stream(), media_type="text/event-stream")


# ── Collection CRUD routes ─────────────────────────────────────────────

@router.post("", status_code=201)
async def create_chat(body: CreateChatRequest, current_user: dict = Depends(get_current_user)):
    """Create a new chat session."""
    now = datetime.now(timezone.utc).isoformat()
    doc = {
        "user_id": current_user["_id"],
        "title": body.title or "New Chat",
        "agent_id": body.agent_id,
        "messages": [],
        "created_at": now,
        "updated_at": now,
    }
    result = await _chat_history_collection().insert_one(doc)
    doc["_id"] = result.inserted_id

    # Track storage for the new empty chat document
    try:
        doc_size = len(json.dumps(doc, default=str).encode('utf-8'))
        await increment_user_storage(current_user["_id"], doc_size)
    except Exception as e:
        logger.warning(f"Failed to track initial chat storage: {e}")

    return {
        "id": str(doc["_id"]),
        "title": doc["title"],
        "agent_id": doc["agent_id"],
        "created_at": doc["created_at"],
        "updated_at": doc["updated_at"],
        "messages": [],
    }


@router.get("")
async def list_chats(agent_id: Optional[str] = None, current_user: dict = Depends(get_current_user)):
    """List chat sessions for the current user, most recent first."""
    query = {"user_id": current_user["_id"]}
    if agent_id is not None:
        query["agent_id"] = agent_id if agent_id != "null" else None

    cursor = _chat_history_collection().find(
        query,
        {"messages": {"$slice": -1}, "user_id": 1, "title": 1, "agent_id": 1,
         "created_at": 1, "updated_at": 1},
    ).sort("updated_at", -1)

    chats = []
    async for doc in cursor:
        chats.append({
            "id": str(doc["_id"]),
            "title": doc.get("title", "New Chat"),
            "agent_id": doc.get("agent_id"),
            "created_at": doc.get("created_at", ""),
            "updated_at": doc.get("updated_at", ""),
            "message_count": len(doc.get("messages", [])),
        })
    return chats


@router.get("/{chat_id}")
async def get_chat(chat_id: str, current_user: dict = Depends(get_current_user)):
    """Retrieve a single chat session with all messages."""
    doc = await _chat_history_collection().find_one({
        "_id": ObjectId(chat_id),
        "user_id": current_user["_id"],
    })
    if not doc:
        raise HTTPException(status_code=404, detail="Chat not found")
    return {
        "id": str(doc["_id"]),
        "user_id": doc["user_id"],
        "title": doc.get("title", "New Chat"),
        "agent_id": doc.get("agent_id"),
        "messages": doc.get("messages", []),
        "created_at": doc.get("created_at", ""),
        "updated_at": doc.get("updated_at", ""),
    }


@router.put("/{chat_id}")
async def update_chat(chat_id: str, body: UpdateChatRequest, current_user: dict = Depends(get_current_user)):
    """Add a message to a chat or update its title."""
    now = datetime.now(timezone.utc).isoformat()
    update = {"$set": {"updated_at": now}}

    if body.message:
        msg_dict = body.message.model_dump()
        msg_dict["timestamp"] = now
        update["$push"] = {"messages": msg_dict}

    if body.title:
        update["$set"]["title"] = body.title

    result = await _chat_history_collection().update_one(
        {"_id": ObjectId(chat_id), "user_id": current_user["_id"]},
        update,
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Chat not found")

    # Track storage for the new message
    if body.message:
        try:
            msg_size = len(json.dumps(msg_dict, default=str).encode('utf-8'))
            await increment_user_storage(current_user["_id"], msg_size)
        except Exception as e:
            logger.warning(f"Failed to increment chat storage: {e}")

    return {"status": "updated"}


@router.post("/{chat_id}/upload")
async def upload_chat_file(chat_id: str, file: UploadFile = File(...), current_user: dict = Depends(get_current_user)):
    """Upload a file to a specific chat, storage-checked."""
    # 1. Upload to blob and update storage
    file_info = await upload_user_file(current_user["_id"], file)

    # 2. Extract info for MongoDB
    file_doc = {
        "filename": file_info["filename"],
        "url": file_info["url"],
        "size": file_info["size"],
        "content_type": file_info["content_type"],
        "blob_name": file_info["blob_name"],
        "uploaded_at": datetime.now(timezone.utc).isoformat()
    }

    return file_doc


@router.delete("/{chat_id}")
async def delete_chat(chat_id: str, current_user: dict = Depends(get_current_user)):
    """Delete a chat session and its associated blobs."""
    # 1. Find the chat to get all message files
    chat = await _chat_history_collection().find_one({
        "_id": ObjectId(chat_id),
        "user_id": current_user["_id"],
    })

    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")

    # 2. Extract all files from all messages
    all_files = []
    for msg in chat.get("messages", []):
        if msg.get("files"):
            all_files.extend(msg["files"])

    # 3. Use blob_service to delete them and update user's storage
    if all_files:
        await delete_user_files(current_user["_id"], all_files)

    # 4. Delete the chat document
    result = await _chat_history_collection().delete_one({
        "_id": ObjectId(chat_id),
        "user_id": current_user["_id"],
    })

    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Chat not found")

    # 5. Full sync after deletion to account for JSON removal
    try:
        await calculate_user_storage(current_user["_id"])
    except Exception as e:
        logger.warning(f"Post-deletion storage sync failed: {e}")

    return {"status": "deleted", "files_cleared": len(all_files)}
