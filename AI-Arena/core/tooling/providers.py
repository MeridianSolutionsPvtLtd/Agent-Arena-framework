"""Single construction point for replaceable tool-infrastructure providers."""

from __future__ import annotations

# Designed and implemented by Rajadurai R.
def get_secret_provider(secret_ref: str):
    from core.tooling.secrets import EncryptedMongoSecretProvider, EnvironmentSecretProvider

    if secret_ref.startswith("env://"):
        return EnvironmentSecretProvider()
    if secret_ref.startswith("mongodb-user://"):
        return EncryptedMongoSecretProvider()
    raise ValueError("Unsupported MCP secret reference provider")
