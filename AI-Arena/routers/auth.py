"""
routers/auth.py
Authentication endpoints.
"""
from fastapi import APIRouter, HTTPException, status, Depends
from pydantic import BaseModel
from bson import ObjectId

from models.user import UserCreate, UserLogin, TokenResponse, RefreshTokenRequest, UserResponse, MessageResponse
from services.auth_service import authenticate_user, refresh_access_token, register_user, hash_password, verify_password
from services.storage_service import calculate_user_storage
from database import get_users_collection
from middleware.auth import get_current_user
from utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/auth", tags=["Authentication"])


class AuthChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


@router.get("/usage")
async def get_usage(current_user: dict = Depends(get_current_user)):
    """Return the user's storage usage."""
    usage_bytes = current_user.get("storage_used_bytes", 0)
    limit_bytes = current_user.get("storage_limit_bytes", 500 * 1024 * 1024)
    return {
        "usage_bytes": usage_bytes,
        "limit_bytes": limit_bytes,
        "limit_mb": limit_bytes // (1024 * 1024)
    }


@router.post("/sync-storage")
async def sync_storage(current_user: dict = Depends(get_current_user)):
    """Force recalculate user's storage usage (Blobs + JSON)."""
    try:
        total_bytes = await calculate_user_storage(current_user["_id"])
        return {"status": "success", "total_bytes": total_bytes}
    except Exception as e:
        logger.error(f"Storage sync failed for {current_user['_id']}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/login", response_model=TokenResponse)
async def login(data: UserLogin):
    """Authenticate user and return access + refresh tokens."""
    logger.info(f"Login attempt for email: {data.email}")
    try:
        result = await authenticate_user(email=data.email, password=data.password)
        logger.info(f"Login successful for email: {data.email}")
        return TokenResponse(
            access_token=result["access_token"],
            refresh_token=result["refresh_token"],
        )
    except ValueError as e:
        logger.warning(f"Login failed (Value Error): {str(e)}")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(e))
    except Exception as e:
        logger.error(f"Login failed for {data.email}: {str(e)}", exc_info=True, extra={"status_code": 500})
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Login failed: {str(e)}",
        )


@router.post("/refresh")
async def refresh(data: RefreshTokenRequest):
    """Get a new access token using a valid refresh token."""
    try:
        result = await refresh_access_token(data.refresh_token)
        logger.info("Token refresh successful")
        return result
    except ValueError as e:
        logger.warning(f"Token refresh failed: {str(e)}")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(e))
    except Exception as e:
        logger.error(f"Token refresh error: {str(e)}", exc_info=True, extra={"status_code": 500})
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Token refresh failed: {str(e)}",
        )


@router.get("/me", response_model=UserResponse)
async def get_me(current_user: dict = Depends(get_current_user)):
    """Return the authenticated user's profile."""
    return UserResponse(
        id=current_user["_id"],
        name=current_user["name"],
        email=current_user["email"],
        created_at=current_user.get("created_at", ""),
        hit_counts=current_user.get("hit_counts", {}),
        agent_hits=current_user.get("agent_hits", {}),
        storage_used_bytes=current_user.get("storage_used_bytes", 0),
        storage_limit_bytes=current_user.get("storage_limit_bytes", 500 * 1024 * 1024),
    )


@router.post("/register")
async def register(data: UserCreate):
    """Register a new user."""
    logger.info(f"Registration attempt for email: {data.email}")
    try:
        user = await register_user(name=data.name, email=data.email, password=data.password)
        logger.info(f"Registration successful for email: {data.email}")
        return MessageResponse(message="Registration successful")
    except ValueError as e:
        logger.warning(f"Registration failed: {str(e)}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error(f"Registration error: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Registration failed: {str(e)}",
        )


@router.post("/change-password")
async def change_password(data: AuthChangePasswordRequest, current_user: dict = Depends(get_current_user)):
    """Change the current user's password."""
    if not verify_password(data.current_password, current_user["password"]):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect",
        )
    users = get_users_collection()
    new_hash = hash_password(data.new_password)
    await users.update_one(
        {"_id": ObjectId(current_user["_id"])},
        {"$set": {"password": new_hash}},
    )
    return MessageResponse(message="Password changed successfully")
