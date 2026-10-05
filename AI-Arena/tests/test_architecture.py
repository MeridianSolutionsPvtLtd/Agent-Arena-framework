"""Regression tests for the single-database and single-auth architecture."""

import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_duplicate_auth_and_old_store_files_are_absent():
    assert not (ROOT / "auth.py").exists()
    assert not (ROOT / "core" / "security" / "auth.py").exists()
    assert not (ROOT / "core" / "security" / "middleware.py").exists()
    assert not (ROOT / "core" / "persistence" / "mongo_client.py").exists()


def test_runtime_store_does_not_create_a_motor_client():
    source = (ROOT / "core" / "persistence" / "runtime_store.py").read_text(encoding="utf-8")

    assert "AsyncIOMotorClient" not in source
    assert "from database import get_db" in source
    assert "class AgentRuntimeStore" in source
    assert "db if db is not None else get_db()" in source
    assert 'cls.db["arena_' not in source
    assert "arena_chats_collection" not in source
    assert "create_arena_chat" not in source
    assert "upsert_arena_credential" not in source
    assert "create_arena_agent_run" not in source
    assert "upsert_arena_db_mapping" not in source
    assert "query_arena_data_rows" not in source


def test_python_sources_do_not_import_removed_compatibility_modules():
    forbidden = (
        "from auth import",
        "core.persistence.mongo_client",
        "core.security.auth",
        "core.security.middleware",
    )
    ignored_directories = {
        ".git", ".venv", "venv", "env", "ENV", "antenv", "__pycache__",
        ".pytest_cache", "build", "dist", "node_modules", "Lib", "Include",
        "share",
    }
    for current, directories, files in os.walk(ROOT):
        directories[:] = [name for name in directories if name not in ignored_directories]
        for filename in files:
            if not filename.endswith(".py"):
                continue
            path = Path(current, filename)
            if path == Path(__file__).resolve():
                continue
            source = path.read_text(encoding="utf-8-sig")
            assert not any(term in source for term in forbidden), (
                f"Removed compatibility import in {path}"
            )


def test_agent_router_uses_canonical_arena_authentication():
    source = (ROOT / "routers" / "agents.py").read_text(encoding="utf-8")

    assert "from middleware.auth import get_current_user" in source


def test_public_agent_contract_uses_one_stable_agent_identifier():
    source = (ROOT / "models" / "agent.py").read_text(encoding="utf-8")

    assert "agent_id: str" in source
    assert "agent_key: str" not in source


def test_custom_agent_creation_is_blueprint_only():
    from main import app

    paths = app.openapi()["paths"]
    assert "post" not in paths["/api/agents"]
    assert "post" in paths["/api/agents/preview"]
    assert "post" in paths["/api/agents/blueprint"]
