"""Encryption for short-lived resumable tool payloads stored in MongoDB."""

from __future__ import annotations

import json
import base64
import hashlib
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

from config import settings


def _fernet() -> Fernet:
    # Derive a valid independent Fernet key from the configured encryption
    # secret; this does not reuse or change the credential-service ciphertext.
    digest = hashlib.sha256(
        ("tool-execution-payload:" + settings.CREDENTIAL_ENCRYPTION_KEY).encode("utf-8")
    ).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_payload(payload: dict[str, Any]) -> str:
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return _fernet().encrypt(
        serialized.encode("utf-8")
    ).decode("ascii")


def decrypt_payload(ciphertext: str) -> dict[str, Any]:
    try:
        raw = _fernet().decrypt(
            ciphertext.encode("ascii")
        )
        value = json.loads(raw.decode("utf-8"))
    except (InvalidToken, ValueError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError("Stored execution payload cannot be decrypted") from exc
    if not isinstance(value, dict):
        raise ValueError("Stored execution payload is invalid")
    return value
