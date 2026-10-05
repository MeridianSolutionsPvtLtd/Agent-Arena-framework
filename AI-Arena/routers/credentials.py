"""
routers/credentials.py
User credential management endpoints.
"""
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field, SecretStr

from config import SERVICE_CREDENTIAL_KEYS
from services.keyvault_service import get_user_credentials, set_credential, list_user_credentials, delete_credential
from middleware.auth import get_current_user
from utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/credentials", tags=["Credentials"])


class CredentialCreateRequest(BaseModel):
    key_name: str = Field(pattern=r"^[A-Z][A-Z0-9_]{2,100}$")
    value: SecretStr


@router.get("/schema")
async def get_credential_schema():
    """Return the credential key names required per service (from .env names)."""
    return {"schema": SERVICE_CREDENTIAL_KEYS, "status": "success"}


@router.post("")
async def add_credential(data: CredentialCreateRequest, current_user: dict = Depends(get_current_user)):
    """Add or update a credential for the current user (encrypted in DB)."""
    logger.info(f"Adding credential {data.key_name} for user {current_user['_id']}")
    try:
        result = await set_credential(
            user_id=current_user["_id"],
            key_name=data.key_name,
            value=data.value.get_secret_value(),
        )
        logger.info(f"Credential {data.key_name} saved successfully")
        return {"result": result, "status": "success"}
    except ValueError as e:
        logger.warning(f"Failed to add credential {data.key_name}: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to save credential {data.key_name}: {str(e)}", exc_info=True, extra={"status_code": 500})
        raise HTTPException(status_code=503, detail="Credential service is unavailable")


@router.get("")
async def list_credentials(current_user: dict = Depends(get_current_user)):
    """List all credential names for the current user (values are not returned)."""
    try:
        secrets = await list_user_credentials(user_id=current_user["_id"])
        return {"credentials": secrets, "status": "success"}
    except ValueError as e:
        logger.warning(f"Failed to list credentials: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to list credentials: {str(e)}", exc_info=True, extra={"status_code": 500})
        raise HTTPException(status_code=503, detail="Credential service is unavailable")


@router.delete("/{key_name}")
async def remove_credential(key_name: str, current_user: dict = Depends(get_current_user)):
    """Delete a credential for the current user."""
    logger.info(f"Deleting credential {key_name} for user {current_user['_id']}")
    try:
        result = await delete_credential(user_id=current_user["_id"], key_name=key_name)
        logger.info(f"Credential {key_name} deleted successfully")
        return {"result": result, "status": "success"}
    except ValueError as e:
        logger.warning(f"Failed to delete credential {key_name}: {str(e)}")
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to delete credential {key_name}: {str(e)}", exc_info=True, extra={"status_code": 500})
        raise HTTPException(status_code=503, detail="Credential service is unavailable")
