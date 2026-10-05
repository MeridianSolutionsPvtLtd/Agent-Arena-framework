"""
Credential service — stores encrypted credentials in MongoDB (replaces Key Vault).

Each user document has a `credentials` field:
    { "credentials": { "AZURE_OPENAI_API_KEY": "<encrypted>", ... } }

Values are encrypted with Fernet symmetric encryption before storage
and decrypted when retrieved.
"""

import base64

from cryptography.fernet import Fernet, InvalidToken
from config import settings
from database import get_users_collection
from utils.logger import get_logger
import bson
import re
import json
from datetime import datetime, timezone, timedelta

logger = get_logger(__name__)

_fernet = None
_CREDENTIAL_KEY_RE = re.compile(r"^[A-Z][A-Z0-9_]{2,100}$")


# Designed and implemented by Rajadurai R.
# Reject MongoDB path-control characters before constructing credential field paths.
def _validate_key_name(key_name: str) -> str:
    normalized = (key_name or "").strip().upper()
    if not _CREDENTIAL_KEY_RE.fullmatch(normalized):
        raise ValueError("Credential name must contain only uppercase letters, digits, and underscores")
    return normalized


def _get_fernet() -> Fernet:
    """Get or create the Fernet encryptor (singleton)."""
    global _fernet
    if _fernet is None:
        key = settings.CREDENTIAL_ENCRYPTION_KEY
        if not key:
            logger.critical("CREDENTIAL_ENCRYPTION_KEY is not configured in .env")
            raise ValueError("CREDENTIAL_ENCRYPTION_KEY is not configured")
        # Accept standard Fernet keys and equivalent URL-safe Base64 values
        # whose trailing padding was stripped by a secret manager.
        padded_key = key + ("=" * (-len(key) % 4))
        _fernet = Fernet(padded_key.encode())
    return _fernet


def _encrypt(value: str) -> str:
    """Encrypt a plaintext value and return base64-encoded ciphertext."""
    return _get_fernet().encrypt(value.encode()).decode()


def _decrypt(token: str) -> str:
    """Decrypt a Fernet token and return plaintext."""
    try:
        return _get_fernet().decrypt(token.encode()).decode()
    except InvalidToken:
        logger.error("Failed to decrypt credential — invalid token")
        raise ValueError("Failed to decrypt credential")


async def set_credential(user_id: str, key_name: str, value: str) -> dict:
    """Encrypt and store a credential in the user's MongoDB document."""
    # Plain API keys, bearer tokens, and OAuth bundles never reach the catalog.
    try:
        key_name = _validate_key_name(key_name)
        if not value or len(value) > 100_000:
            raise ValueError("Credential value is required and must not exceed 100000 characters")
        encrypted = _encrypt(value)
        users = get_users_collection()
        await users.update_one(
            {"_id": bson.ObjectId(user_id)},
            {"$set": {f"credentials.{key_name}": encrypted}},
        )
        logger.info(f"Credential {key_name} saved for user {user_id}")
        return {"key_name": key_name, "status": "saved"}
    except Exception as e:
        logger.error(f"Failed to save credential {key_name}: {e}", exc_info=True)
        raise ValueError(f"Failed to save credential: {str(e)}")


async def get_credential(user_id: str, key_name: str) -> str | None:
    """Retrieve and decrypt a single credential from MongoDB. Returns None if not found."""
    try:
        key_name = _validate_key_name(key_name)
        users = get_users_collection()
        user = await users.find_one(
            {"_id": bson.ObjectId(user_id)},
            {"credentials": 1}
        )
        if not user or "credentials" not in user:
            return None
        encrypted = user["credentials"].get(key_name)
        if not encrypted:
            return None
        return _decrypt(encrypted)
    except ValueError:
        return None
    except Exception as e:
        logger.error(f"Failed to get credential {key_name}: {e}", exc_info=True)
        return None


async def list_user_credentials(user_id: str) -> list:
    """List all credential key names for a user (no values returned)."""
    try:
        users = get_users_collection()
        user = await users.find_one(
            {"_id": bson.ObjectId(user_id)},
            {"credentials": 1}
        )
        if not user or "credentials" not in user:
            return []
        return [{"key_name": k} for k in user["credentials"].keys()]
    except Exception as e:
        logger.error(f"Failed to list credentials: {e}", exc_info=True)
        raise ValueError(f"Failed to list credentials: {str(e)}")


async def delete_credential(user_id: str, key_name: str) -> dict:
    """Remove a credential from the user's MongoDB document."""
    try:
        key_name = _validate_key_name(key_name)
        users = get_users_collection()
        result = await users.update_one(
            {"_id": bson.ObjectId(user_id)},
            {"$unset": {f"credentials.{key_name}": ""}},
        )
        if result.modified_count == 0:
            raise ValueError(f"Credential '{key_name}' not found")
        logger.info(f"Credential {key_name} deleted for user {user_id}")
        return {"key_name": key_name, "status": "deleted"}
    except ValueError:
        raise
    except Exception as e:
        logger.error(f"Failed to delete credential {key_name}: {e}", exc_info=True)
        raise ValueError(f"Failed to delete credential: {str(e)}")


async def get_user_credentials(user_id: str, required_keys: list) -> dict:
    """
    Get a dict of credentials for a user.
    For each key in required_keys, try to fetch from user's DB record.
    If not found, fall back to the env/settings default.
    """
    credentials = {}
    for key_name in required_keys:
        value = await get_credential(user_id, key_name)
        if value:
            credentials[key_name] = value
        else:
            # Fallback to the settings default
            credentials[key_name] = getattr(settings, key_name, "")
    return credentials


# Designed and implemented by Rajadurai R.
async def get_oauth_access_token(user_id: str, key_name: str) -> str:
    """Resolve and refresh an encrypted OAuth token bundle when necessary."""

    raw = await get_credential(user_id, key_name)
    if not raw:
        raise ValueError("OAuth connection must be reconnected")
    try:
        bundle = json.loads(raw)
        access_token = str(bundle["access_token"])
        expires_at = datetime.fromisoformat(str(bundle["expires_at"]))
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("Stored OAuth credential is invalid") from exc
    if expires_at > datetime.now(timezone.utc) + timedelta(seconds=60):
        return access_token
    refresh_token = bundle.get("refresh_token")
    token_endpoint = bundle.get("token_endpoint")
    if not refresh_token or not token_endpoint:
        raise ValueError("OAuth connection must be reconnected")
    import httpx
    from core.tooling.external_mcp import validate_resolved_endpoint

    await validate_resolved_endpoint(str(token_endpoint))

    client_id = str(bundle.get("client_id") or "")
    if not client_id:
        raise ValueError("Stored OAuth client registration is invalid")
    payload = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": client_id,
    }
    headers = {}
    client_secret = bundle.get("client_secret")
    auth_method = bundle.get("token_endpoint_auth_method", "none")
    if client_secret and auth_method == "client_secret_basic":
        encoded = base64.b64encode(
            f"{client_id}:{client_secret}".encode("utf-8")
        ).decode("ascii")
        headers["Authorization"] = f"Basic {encoded}"
    elif client_secret:
        payload["client_secret"] = client_secret
    async with httpx.AsyncClient(timeout=20.0, follow_redirects=False) as client:
        response = await client.post(token_endpoint, data=payload, headers=headers)
        if response.status_code >= 400:
            raise ValueError("OAuth connection must be reconnected")
        refreshed = response.json()
    if not refreshed.get("access_token"):
        raise ValueError("OAuth provider returned an invalid refresh response")
    bundle["access_token"] = refreshed["access_token"]
    bundle["refresh_token"] = refreshed.get("refresh_token", refresh_token)
    bundle["expires_at"] = (
        datetime.now(timezone.utc) + timedelta(seconds=int(refreshed.get("expires_in", 3600)))
    ).isoformat()
    await set_credential(user_id, key_name, json.dumps(bundle, separators=(",", ":")))
    return str(bundle["access_token"])
