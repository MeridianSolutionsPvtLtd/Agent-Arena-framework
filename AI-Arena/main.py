"""
Meridian AI Arena — Unified FastAPI Backend
Merges AI MeridianAI Arena services + Agent MeridianAI Arena agents.
"""

import sys

# chromadb (pulled in by crewai) rejects sqlite3 < 3.35 at import time, and the
# App Service image ships an older build. pysqlite3 bundles its own SQLite, so
# alias it before anything can import the stdlib module.
try:
    __import__("pysqlite3")
    sys.modules["sqlite3"] = sys.modules.pop("pysqlite3")
except ModuleNotFoundError:
    pass

import os
import asyncio
from contextlib import AsyncExitStack, asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Adjust path to the project root directory
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from config import settings, validate_security_settings
from database import connect_to_mongo, close_mongo_connection, get_db
from middleware.logging_middleware import LoggingMiddleware
from middleware.path_fixer import PathFixerMiddleware
from middleware.error_handlers import register_safe_error_handlers
from utils.logger import get_logger
from services.agent_service import initialize_agent_storage
from agents.call_audit.service import warmup_azure_stt

logger = get_logger(__name__)

async def seed_default_user():
    """Optionally create an explicitly configured bootstrap user."""
    if not settings.SEED_DEFAULT_USER:
        return
    try:
        db = get_db()
        existing = await db.users.find_one({"email": settings.DEFAULT_USER_EMAIL})
        if not existing:
            from services.auth_service import hash_password
            from datetime import datetime, timezone

            await db.users.insert_one({
                "name": settings.DEFAULT_USER_NAME,
                "email": settings.DEFAULT_USER_EMAIL,
                "password": hash_password(settings.DEFAULT_USER_PASSWORD),
                "created_at": datetime.now(timezone.utc).isoformat(),
                "hit_counts": {
                    "openai": 0, "vision": 0, "document": 0, "search": 0,
                    "language": 0, "speech": 0, "translator": 0,
                    "content_safety": 0, "video_analysis": 0,
                },
                "agent_hits": {
                    "call_audit": 0, "contract_analysis": 0,
                    "recruitment": 0, "data_insights": 0,
                    "compliance_policy": 0, "invoice_finance": 0,
                    "legal_agent": 0, "gd": 0,
                },
                "total_tokens": 0,
                "storage_used_bytes": 0,
                "storage_limit_bytes": 500 * 1024 * 1024,
            })
            logger.info("Seeded configured bootstrap user")
        else:
            logger.info("Configured bootstrap user already exists")
    except Exception as e:
        logger.error(f"Failed to seed default user: {e}", exc_info=True)
        raise

@asynccontextmanager
async def lifespan(app: FastAPI):
    stack = AsyncExitStack()
    try:
        validate_security_settings()
        await connect_to_mongo()
        await initialize_agent_storage()   # indexes first — collections are empty here
        await seed_default_user()          # insert user only after indexes exist
        # Load chat and semantic-embedding models before the first request.
        from core.orchestration.azure_settings import warmup_ollama_models
        await asyncio.to_thread(warmup_ollama_models)
        # Run warmup task in the background safely during lifespan startup
        asyncio.create_task(warmup_azure_stt())
    except Exception as e:
        await stack.aclose()
        logger.critical(f"Startup failed: {e}", exc_info=True)
        raise
    yield
    await stack.aclose()
    await close_mongo_connection()

app = FastAPI(
    title="Meridian AI Arena API",
    version="2.0.0",
    lifespan=lifespan,
)

register_safe_error_handlers(app)

app.add_middleware(PathFixerMiddleware)
app.add_middleware(LoggingMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials="*" not in settings.CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── AI Service Routers ──────────────────────────────────────────────
from routers import openai, search, vision, document, language, speech, translator, content_safety, video, image
from routers import auth, credentials
from routers import chat as chat_router_module
from routers import agents as agents_router_module
from routers import capabilities as capabilities_router_module
from routers import mcp_connections as mcp_connections_router_module
from routers import tool_executions as tool_executions_router_module
from routers import agent_files as agent_files_router_module
from routers import agent_registry as agent_registry_router_module

app.include_router(auth.router)
app.include_router(credentials.router)
app.include_router(chat_router_module.router)
app.include_router(agent_files_router_module.router)
app.include_router(agents_router_module.router)
app.include_router(capabilities_router_module.router)
# Designed and implemented by Rajadurai R.
# Register the owner-scoped MCP onboarding and OAuth surface with the application.
app.include_router(mcp_connections_router_module.router)
app.include_router(tool_executions_router_module.router)
app.include_router(agent_registry_router_module.router)
app.include_router(openai.router)
app.include_router(search.router)
app.include_router(vision.router)
app.include_router(document.router)
app.include_router(language.router)
app.include_router(speech.router)
app.include_router(translator.router)
app.include_router(content_safety.router)
app.include_router(video.router)
app.include_router(image.router)

# ── Agent Routers ────────────────────────────────────────────────────
from agents.call_audit.router import router as call_audit_router
from agents.recruitment.router import router as recruitment_router
from agents.group_discussion.router import router as gd_router
from agents.compliance.router import router as compliance_router
from agents.data_insights.router import router as data_insights_router
from agents.invoice_finance.router import router as invoice_finance_router
from agents.legal.router import router as legal_router
from agents.sql_agent.router import router as sql_agent_router

app.include_router(call_audit_router)
app.include_router(recruitment_router)
app.include_router(gd_router)
app.include_router(compliance_router)
app.include_router(data_insights_router)
app.include_router(invoice_finance_router)
app.include_router(legal_router)
app.include_router(sql_agent_router)

@app.get("/")
def read_root():
    return {"message": "Welcome to Meridian AI Arena API"}

@app.get("/health")
def health_check():
    return _health_payload()

@app.get("/api/health")
def api_health_check():
    return _health_payload()


def _health_payload() -> dict:
    return {
        "status": "healthy",
        "service": "Meridian AI Arena",
        "tool_runtime": {
            "enabled": settings.ENABLE_GOVERNED_TOOL_RUNTIME,
            "registry_provider": "mongodb",
            "external_transport": "direct_https",
            "native_mcp_enabled": settings.ENABLE_NATIVE_MCP_SERVER,
        },
    }

