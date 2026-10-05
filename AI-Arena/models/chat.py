from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime


class ChatMessageSchema(BaseModel):
    """Schema for a single chat message."""
    role: str  # 'user', 'assistant', 'system'
    content: str
    images: Optional[List[str]] = None
    files: Optional[List[dict]] = None
    timestamp: Optional[str] = None


class CreateChatRequest(BaseModel):
    """Schema for creating a new chat session."""
    agent_id: Optional[str] = None  # None = normal chat, else agent id
    title: Optional[str] = "New Chat"


class UpdateChatRequest(BaseModel):
    """Schema for adding a message to a chat."""
    message: Optional[ChatMessageSchema] = None
    title: Optional[str] = None


class GenerateTitleRequest(BaseModel):
    """Schema for generating a chat title from messages."""
    messages: List[dict]


class ChatSessionResponse(BaseModel):
    """Schema for chat session returned to frontend."""
    id: str
    user_id: str
    title: str
    agent_id: Optional[str] = None
    messages: List[dict] = []
    created_at: str
    updated_at: str


class ChatListItem(BaseModel):
    """Schema for chat list item (without full messages)."""
    id: str
    title: str
    agent_id: Optional[str] = None
    created_at: str
    updated_at: str
    message_count: int = 0
