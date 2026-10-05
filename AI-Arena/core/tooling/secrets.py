"""Secret resolver interfaces for low-cost and future managed deployments."""

from __future__ import annotations

import os
import re
from typing import Optional, Protocol


class SecretResolutionError(RuntimeError):
    pass


# Designed and implemented by Rajadurai R.
# Keeps runtime callers independent from the physical secret backend.
class SecretProvider(Protocol):
    async def get_secret(self, secret_ref: str, *, user_id: Optional[str] = None) -> str: ...


class EnvironmentSecretProvider:
    async def get_secret(self, secret_ref: str, *, user_id: Optional[str] = None) -> str:
        prefix = "env://"
        if not secret_ref.startswith(prefix):
            raise SecretResolutionError("Environment secret reference is invalid")
        key = secret_ref[len(prefix):]
        if not re.fullmatch(r"[A-Z][A-Z0-9_]{2,100}", key):
            raise SecretResolutionError("Environment secret name is invalid")
        value = os.getenv(key, "")
        if not value:
            raise SecretResolutionError("Required environment secret is unavailable")
        return value


# Designed and implemented by Rajadurai R.
# User-owned MCP credentials resolve only through the authenticated user boundary.
class EncryptedMongoSecretProvider:
    async def get_secret(self, secret_ref: str, *, user_id: Optional[str] = None) -> str:
        prefix = "mongodb-user://"
        if not secret_ref.startswith(prefix) or not user_id:
            raise SecretResolutionError("Encrypted MongoDB secret reference requires a user")
        key = secret_ref[len(prefix):]
        if not re.fullmatch(r"[A-Z][A-Z0-9_]{2,100}", key):
            raise SecretResolutionError("Encrypted MongoDB secret name is invalid")
        from services.keyvault_service import get_credential

        value = await get_credential(user_id, key)
        if not value:
            raise SecretResolutionError("Required encrypted credential is unavailable")
        return value
