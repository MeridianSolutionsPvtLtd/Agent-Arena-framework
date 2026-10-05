from pydantic import BaseModel, EmailStr, Field
from typing import Optional, Dict
from datetime import datetime


class UserCreate(BaseModel):
    """Schema for user registration."""
    name: str = Field(..., min_length=2, max_length=100)
    email: EmailStr
    password: str = Field(..., min_length=6)


class UserLogin(BaseModel):
    """Schema for user login."""
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    """Schema for JWT token response."""
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshTokenRequest(BaseModel):
    """Schema for token refresh."""
    refresh_token: str


class UserResponse(BaseModel):
    """Schema for user data returned to frontend."""
    id: str
    name: str
    email: str
    created_at: str
    hit_counts: Dict[str, int] = {}
    agent_hits: Dict[str, int] = {}
    storage_used_bytes: int = 0
    storage_limit_bytes: int = 500 * 1024 * 1024


class MessageResponse(BaseModel):
    """Generic message response."""
    message: str
    status: str = "success"
