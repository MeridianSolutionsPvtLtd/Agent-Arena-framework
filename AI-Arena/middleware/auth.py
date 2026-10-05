import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from bson import ObjectId
from config import settings
from database import get_users_collection

security = HTTPBearer()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> dict:
    """
    FastAPI dependency that decodes the JWT access token from the
    Authorization header and returns the authenticated user document.
    """
    token = credentials.credentials

    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Access token has expired",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid access token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if payload.get("type") != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token type",
        )

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload",
        )

    users = get_users_collection()
    user = await users.find_one({"_id": ObjectId(user_id)})

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )

    # Convert ObjectId to string for convenience
    user["_id"] = str(user["_id"])
    
    # Ensure context is set (redundant but safe)
    from utils.logger import user_id_ctx
    user_id_ctx.set(user["_id"])
    
    return user


async def get_capability_admin(
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Authorize Capability Catalog management through one migration boundary.

    The product currently has no finalized RBAC model, so authenticated mode
    intentionally delegates management to the existing JWT boundary.  The
    admin mode is retained for a configuration-only migration to RBAC later.
    """

    if settings.CAPABILITY_MANAGEMENT_ACCESS == "authenticated":
        return current_user

    roles = current_user.get("roles") or []
    if isinstance(roles, str):
        roles = [roles]
    normalized_roles = {
        str(role).strip().lower() for role in roles if str(role).strip()
    }
    if not current_user.get("is_admin") and not normalized_roles.intersection(
        {"capability_admin", "platform_admin"}
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Capability administrator role is required",
        )
    return current_user
