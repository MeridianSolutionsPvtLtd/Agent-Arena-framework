import jwt
from datetime import datetime, timedelta, timezone
from passlib.context import CryptContext
from config import settings
from database import get_users_collection
from utils.logger import get_logger

logger = get_logger(__name__)

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    """Hash a password using bcrypt, truncating to 72 bytes to avoid algorithm limits."""
    # Bcrypt has a 72-byte limit for the input password.
    truncated_password = password[:72]
    return pwd_context.hash(truncated_password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plain password against a hashed one, truncating to 72 bytes."""
    try:
        truncated_password = plain_password[:72]
        return pwd_context.verify(truncated_password, hashed_password)
    except Exception as e:
        logger.error(f"Password verification failed: {e}")
        return False


def create_access_token(data: dict) -> str:
    """Create a short-lived JWT access token."""
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire, "type": "access"})
    return jwt.encode(to_encode, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def create_refresh_token(data: dict) -> str:
    """Create a long-lived JWT refresh token."""
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    to_encode.update({"exp": expire, "type": "refresh"})
    return jwt.encode(to_encode, settings.JWT_REFRESH_SECRET, algorithm=settings.JWT_ALGORITHM)


async def register_user(name: str, email: str, password: str) -> dict:
    """Register a new user in MongoDB."""
    users = get_users_collection()

    # Check if user already exists
    existing = await users.find_one({"email": email.lower()})
    if existing:
        raise ValueError("A user with this email already exists")

    user_doc = {
        "name": name,
        "email": email.lower(),
        "password": hash_password(password),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "hit_counts": {
            "openai": 0,
            "vision": 0,
            "document": 0,
            "search": 0,
            "language": 0,
            "speech": 0,
            "translator": 0,
            "content_safety": 0,
            "video_analysis": 0,
        },
        "agent_hits": {
            "call_audit": 0,
            "recruitment": 0,
            "group_discussion": 0,
            "compliance_policy": 0,
            "data_insights": 0,
            "invoice_finance": 0,
            "legal_agent": 0,
        },
        "storage_used_bytes": 0,
        "storage_limit_bytes": 500 * 1024 * 1024,
    }

    result = await users.insert_one(user_doc)
    user_doc["_id"] = result.inserted_id
    return user_doc


async def authenticate_user(email: str, password: str) -> dict:
    """Authenticate user and return tokens."""
    users = get_users_collection()
    user = await users.find_one({"email": email.lower()})

    if not user:
        raise ValueError("Invalid email or password")

    if not verify_password(password, user["password"]):
        raise ValueError("Invalid email or password")

    token_data = {"sub": str(user["_id"]), "email": user["email"], "name": user["name"]}
    access_token = create_access_token(token_data)
    refresh_token = create_refresh_token(token_data)

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "user": {
            "id": str(user["_id"]),
            "name": user["name"],
            "email": user["email"],
            "created_at": user.get("created_at", ""),
            "hit_counts": user.get("hit_counts", {}),
            "agent_hits": user.get("agent_hits", {}),
            "storage_used_bytes": user.get("storage_used_bytes", 0),
            "storage_limit_bytes": user.get("storage_limit_bytes", 500 * 1024 * 1024),
        },
    }


async def refresh_access_token(refresh_token: str) -> dict:
    """Validate refresh token and return a new access token."""
    try:
        payload = jwt.decode(
            refresh_token, settings.JWT_REFRESH_SECRET, algorithms=[settings.JWT_ALGORITHM]
        )
        if payload.get("type") != "refresh":
            raise ValueError("Invalid token type")

        token_data = {"sub": payload["sub"], "email": payload["email"], "name": payload["name"]}
        new_access_token = create_access_token(token_data)

        return {"access_token": new_access_token, "token_type": "bearer"}
    except jwt.ExpiredSignatureError:
        raise ValueError("Refresh token has expired. Please login again.")
    except jwt.InvalidTokenError:
        raise ValueError("Invalid refresh token")
