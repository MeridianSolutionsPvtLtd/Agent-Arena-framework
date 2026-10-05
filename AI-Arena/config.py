import os
from dotenv import load_dotenv

load_dotenv()


class Settings:
    """Central configuration accessed via environment variables."""

    # MongoDB
    MONGODB_URI: str = os.getenv("MONGODB_URI", "")
    MONGODB_NAME: str = os.getenv("MONGODB_NAME", "meridianarena")
    MONGODB_COLLECTION_NAME: str = os.getenv("MONGODB_COLLECTION_NAME", "users")

    # JWT
    JWT_SECRET: str = os.getenv("JWT_SECRET", "change-me")
    JWT_REFRESH_SECRET: str = os.getenv("JWT_REFRESH_SECRET", "change-me-refresh")
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30"))
    REFRESH_TOKEN_EXPIRE_DAYS: int = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "7"))

    # Credential Encryption
    CREDENTIAL_ENCRYPTION_KEY: str = os.getenv("CREDENTIAL_ENCRYPTION_KEY", "")

    AGENT_REGISTRY_TEST_TIMEOUT_SECONDS: int = max(
        5, min(int(os.getenv("AGENT_REGISTRY_TEST_TIMEOUT_SECONDS", "30")), 120)
    )
    AGENT_REGISTRY_RUN_TIMEOUT_SECONDS: int = max(
        5, min(int(os.getenv("AGENT_REGISTRY_RUN_TIMEOUT_SECONDS", "120")), 600)
    )
    AGENT_REGISTRY_ALLOWED_HOST_SUFFIXES: tuple[str, ...] = tuple(
        value.strip().lower().lstrip(".")
        for value in os.getenv("AGENT_REGISTRY_ALLOWED_HOST_SUFFIXES", "").split(",")
        if value.strip()
    )

    # Optional bootstrap account. Disabled by default in every environment.
    SEED_DEFAULT_USER: bool = os.getenv("SEED_DEFAULT_USER", "false").lower() == "true"
    DEFAULT_USER_NAME: str = os.getenv("DEFAULT_USER_NAME", "")
    DEFAULT_USER_EMAIL: str = os.getenv("DEFAULT_USER_EMAIL", "")
    DEFAULT_USER_PASSWORD: str = os.getenv("DEFAULT_USER_PASSWORD", "")

    # High-risk tools remain disabled unless the deployment explicitly enables them.
    ENABLE_UNSAFE_PYTHON_TOOL: bool = (
        os.getenv("ENABLE_UNSAFE_PYTHON_TOOL", "false").lower() == "true"
    )
    ENABLE_ADVANCED_WEB_TOOL: bool = (
        os.getenv("ENABLE_ADVANCED_WEB_TOOL", "false").lower() == "true"
    )

    # Reusable native MCP tools execute in-process behind the existing app JWT.
    ENABLE_NATIVE_MCP_SERVER: bool = (
        os.getenv("ENABLE_NATIVE_MCP_SERVER", "false").lower() == "true"
    )
    ENABLE_GOVERNED_TOOL_RUNTIME: bool = (
        os.getenv("ENABLE_GOVERNED_TOOL_RUNTIME", "false").lower() == "true"
    )
    APP_ENV: str = os.getenv("APP_ENV", "development").strip().lower()
    # Temporary bridge until the product's RBAC model is finalized.  Keep the
    # authorization decision centralized so endpoints do not need to change
    # when capability administration moves to dedicated roles.
    CAPABILITY_MANAGEMENT_ACCESS: str = os.getenv(
        "CAPABILITY_MANAGEMENT_ACCESS", "authenticated"
    ).strip().lower()
    MCP_MAX_REQUEST_BYTES: int = int(os.getenv("MCP_MAX_REQUEST_BYTES", "1048576"))
    MCP_MAX_RESPONSE_BYTES: int = int(os.getenv("MCP_MAX_RESPONSE_BYTES", "5242880"))
    MCP_ALLOWED_ENDPOINT_HOSTS: list[str] = [
        item.strip()
        for item in os.getenv("MCP_ALLOWED_ENDPOINT_HOSTS", "").split(",")
        if item.strip()
    ]
    # Designed and implemented by Rajadurai R.
    MCP_VALIDATION_MAX_AGE_SECONDS: int = int(
        os.getenv("MCP_VALIDATION_MAX_AGE_SECONDS", "900")
    )
    MCP_SERVER_VALIDATION_TIMEOUT_SECONDS: int = int(
        os.getenv("MCP_SERVER_VALIDATION_TIMEOUT_SECONDS", "30")
    )
    MCP_MAX_DISCOVERED_TOOLS: int = int(os.getenv("MCP_MAX_DISCOVERED_TOOLS", "500"))
    MCP_MAX_CONNECTIONS_PER_USER: int = int(os.getenv("MCP_MAX_CONNECTIONS_PER_USER", "10"))
    MCP_MAX_ACTIVE_TOOLS_PER_AGENT: int = int(os.getenv("MCP_MAX_ACTIVE_TOOLS_PER_AGENT", "30"))

    # CORS
    CORS_ORIGINS: list = os.getenv("CORS_ORIGINS", "*").split(",")

    # Azure Service Defaults (fallback when user hasn't set their own)
    AZURE_OPENAI_ENDPOINT: str = os.getenv("AZURE_OPENAI_ENDPOINT", "")
    AZURE_OPENAI_API_KEY: str = os.getenv("AZURE_OPENAI_API_KEY", "")
    AZURE_OPENAI_DEPLOYMENT_NAME: str = os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME", "")

    AZURE_OPENAI_IMAGE_ENDPOINT: str = os.getenv("AZURE_OPENAI_IMAGE_ENDPOINT", "")
    AZURE_OPENAI_IMAGE_API_KEY: str = os.getenv("AZURE_OPENAI_IMAGE_API_KEY", "")
    AZURE_OPENAI_IMAGE_DEPLOYMENT_NAME: str = os.getenv("AZURE_OPENAI_IMAGE_DEPLOYMENT_NAME", "")

    AZURE_SEARCH_ENDPOINT: str = os.getenv("AZURE_SEARCH_ENDPOINT", "")
    AZURE_SEARCH_API_KEY: str = os.getenv("AZURE_SEARCH_API_KEY", "")

    AZURE_VISION_ENDPOINT: str = os.getenv("AZURE_VISION_ENDPOINT", "")

    AZURE_VISION_API_KEY: str = os.getenv("AZURE_VISION_API_KEY", "")

    AZURE_DOCUMENT_ENDPOINT: str = os.getenv("AZURE_DOCUMENT_ENDPOINT", "")
    AZURE_DOCUMENT_API_KEY: str = os.getenv("AZURE_DOCUMENT_API_KEY", "")

    AZURE_LANGUAGE_ENDPOINT: str = os.getenv("AZURE_LANGUAGE_ENDPOINT", "")
    AZURE_LANGUAGE_API_KEY: str = os.getenv("AZURE_LANGUAGE_API_KEY", "")

    AZURE_SPEECH_KEY: str = os.getenv("AZURE_SPEECH_KEY", "")
    AZURE_SPEECH_REGION: str = os.getenv("AZURE_SPEECH_REGION", "")

    AZURE_TRANSLATOR_KEY: str = os.getenv("AZURE_TRANSLATOR_KEY", "")
    AZURE_TRANSLATOR_REGION: str = os.getenv("AZURE_TRANSLATOR_REGION", "")
    AZURE_TRANSLATOR_ENDPOINT: str = os.getenv("AZURE_TRANSLATOR_ENDPOINT", "")

    AZURE_CONTENT_SAFETY_ENDPOINT: str = os.getenv("AZURE_CONTENT_SAFETY_ENDPOINT", "")
    AZURE_CONTENT_SAFETY_API_KEY: str = os.getenv("AZURE_CONTENT_SAFETY_API_KEY", "")

    # Azure Computer Vision Configuration
    AZURE_VIDEO_VISION_ENDPOINT: str = os.getenv("AZURE_VIDEO_VISION_ENDPOINT", "")
    AZURE_VIDEO_VISION_API_KEY: str = os.getenv("AZURE_VIDEO_VISION_API_KEY", "")
    
    # Azure Speech Service Configuration
    AZURE_VIDEO_SPEECH_KEY: str = os.getenv("AZURE_VIDEO_SPEECH_KEY", "")
    AZURE_VIDEO_SPEECH_REGION: str = os.getenv("AZURE_VIDEO_SPEECH_REGION", "")
    UPLOAD_DIR: str = os.getenv("UPLOAD_DIR", "./uploads")
    MAX_VIDEO_SIZE_MB: int = int(os.getenv("MAX_VIDEO_SIZE_MB", 50))
    FRAME_INTERVAL_SECONDS: int = int(os.getenv("FRAME_INTERVAL_SECONDS",3))
    MAX_VIDEO_DURATION_MINUTES: int = int(os.getenv("MAX_VIDEO_DURATION_MINUTES", 15))

    # Azure AI Foundry Configuration (Agents)
    AZURE_AI_ENDPOINT: str = os.getenv("AZURE_AI_ENDPOINT", "")
    COMPLIANCE_AGENT_ID: str = os.getenv("COMPLIANCE_AGENT_ID", "")
    ATS_AGENT_ID: str = os.getenv("ATS_AGENT_ID", "")
    CALL_AUDIT_AGENT_ID: str = os.getenv("CALL_AUDIT_AGENT_ID", "")
    DATA_INSIGHTS_AGENT_ID: str = os.getenv("DATA_INSIGHTS_AGENT_ID", "")
    LEGAL_AGENT_ID: str = os.getenv("LEGAL_AGENT_ID", "")

    # Azure Blob Storage
    BLOB_CONNECTION_STRING: str = os.getenv("BLOB_CONNECTION_STRING", "")
    CONTAINER_NAME: str = os.getenv("CONTAINER_NAME", "user-uploads")
    STORAGE_LIMIT_MB: int = int(os.getenv("STORAGE_LIMIT_MB", 500))


# Credential schema: maps service name -> list of required env var names




# Credential schema: maps service name -> list of required env var names
# These exact names are what users must provide in the frontend
SERVICE_CREDENTIAL_KEYS = {
    "openai": ["AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_API_KEY", "AZURE_OPENAI_DEPLOYMENT_NAME"],
    "search": ["AZURE_SEARCH_ENDPOINT", "AZURE_SEARCH_API_KEY"],
    "vision": ["AZURE_VISION_ENDPOINT", "AZURE_VISION_API_KEY"],

    "document": ["AZURE_DOCUMENT_ENDPOINT", "AZURE_DOCUMENT_API_KEY"],
    "language": ["AZURE_LANGUAGE_ENDPOINT", "AZURE_LANGUAGE_API_KEY"],
    "speech": ["AZURE_SPEECH_KEY", "AZURE_SPEECH_REGION"],
    "translator": ["AZURE_TRANSLATOR_KEY", "AZURE_TRANSLATOR_REGION", "AZURE_TRANSLATOR_ENDPOINT"],
    "content_safety": ["AZURE_CONTENT_SAFETY_ENDPOINT", "AZURE_CONTENT_SAFETY_API_KEY"],
    "video_vision": ["AZURE_VIDEO_VISION_ENDPOINT", "AZURE_VIDEO_VISION_API_KEY"],
    "video_speech": ["AZURE_VIDEO_SPEECH_KEY", "AZURE_VIDEO_SPEECH_REGION"],
    "image_generation": ["AZURE_OPENAI_IMAGE_ENDPOINT", "AZURE_OPENAI_IMAGE_API_KEY", "AZURE_OPENAI_IMAGE_DEPLOYMENT_NAME"],
}


settings = Settings()
def validate_security_settings() -> None:
    """Validate authentication secrets before application startup."""
    if len(settings.JWT_SECRET) < 32:
        raise RuntimeError("JWT_SECRET must contain at least 32 characters")

    if len(settings.JWT_REFRESH_SECRET) < 32:
        raise RuntimeError(
            "JWT_REFRESH_SECRET must contain at least 32 characters"
        )

    if settings.JWT_SECRET == settings.JWT_REFRESH_SECRET:
        raise RuntimeError(
            "JWT access and refresh secrets must be different"
        )

    if len(settings.CREDENTIAL_ENCRYPTION_KEY) < 32:
        raise RuntimeError(
            "CREDENTIAL_ENCRYPTION_KEY must contain at least 32 characters"
        )
    try:
        from cryptography.fernet import Fernet
        padded_key = settings.CREDENTIAL_ENCRYPTION_KEY + (
            "=" * (-len(settings.CREDENTIAL_ENCRYPTION_KEY) % 4)
        )
        Fernet(padded_key.encode())
    except Exception as exc:
        raise RuntimeError(
            "CREDENTIAL_ENCRYPTION_KEY must be a valid Fernet key"
        ) from exc
    if settings.CAPABILITY_MANAGEMENT_ACCESS not in {"authenticated", "admin"}:
        raise RuntimeError(
            "CAPABILITY_MANAGEMENT_ACCESS must be one of: admin, authenticated"
        )
    if not 1024 <= settings.MCP_MAX_REQUEST_BYTES <= 100 * 1024 * 1024:
        raise RuntimeError("MCP_MAX_REQUEST_BYTES must be between 1 KiB and 100 MiB")
    if not 1024 <= settings.MCP_MAX_RESPONSE_BYTES <= 100 * 1024 * 1024:
        raise RuntimeError("MCP_MAX_RESPONSE_BYTES must be between 1 KiB and 100 MiB")
    if not 60 <= settings.MCP_VALIDATION_MAX_AGE_SECONDS <= 86_400:
        raise RuntimeError("MCP_VALIDATION_MAX_AGE_SECONDS must be between 60 and 86400")
    if not 1 <= settings.MCP_SERVER_VALIDATION_TIMEOUT_SECONDS <= 300:
        raise RuntimeError("MCP_SERVER_VALIDATION_TIMEOUT_SECONDS must be between 1 and 300")
    if not 1 <= settings.MCP_MAX_DISCOVERED_TOOLS <= 10_000:
        raise RuntimeError("MCP_MAX_DISCOVERED_TOOLS must be between 1 and 10000")
    if not 1 <= settings.MCP_MAX_CONNECTIONS_PER_USER <= 1000:
        raise RuntimeError("MCP_MAX_CONNECTIONS_PER_USER must be between 1 and 1000")
    if not 1 <= settings.MCP_MAX_ACTIVE_TOOLS_PER_AGENT <= 200:
        raise RuntimeError("MCP_MAX_ACTIVE_TOOLS_PER_AGENT must be between 1 and 200")
