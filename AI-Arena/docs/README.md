# Meridian Agentic AI Backend Docs

This documentation explains the unified backend after integrating the Arena feature into the main `Meridian-Agentic-Ai-Backend` project.

The backend now has two major parts:

```text
1. Dynamic Agent System
2. Arena Feature System
```

The main app remains:

```text
main.py
```

All APIs are served from this single FastAPI backend.

## Architecture

```text
Frontend
   |
   | /api/*
   v
FastAPI main.py
   |
   +-- Dynamic Agent APIs
   |     |
   |     +-- Agent Builder
   |     +-- Agent Executor
   |     +-- Tools
   |     +-- Memory
   |     +-- Trace WebSocket
   |
   +-- Arena APIs
   |     |
   |     +-- Azure AI Services
   |     +-- Fixed Business Agents
   |     +-- Arena Chats
   |     +-- Arena Credentials
   |
   v
MongoDB
```

## Route Design

Dynamic agent routes stay as existing main project routes:

```text
/api/agents/*
/api/upload
/api/ws/trace/{trace_id}
```

Arena feature routes are namespaced to avoid conflicts:

```text
/api/arena/*
```

Internally, Arena routes are mounted at `/arena/*`. The main middleware strips the external `/api` prefix.

## Folder Structure

```text
Meridian-Agentic-Ai-Backend/
  main.py
  requirements.txt
  README.md
  docs/
    README.md
    PROJECT_OVERVIEW.md
    FOLDER_STRUCTURE.md
    API_REFERENCE.md
    DATA_MODEL.md
    WORKFLOWS.md
    MODULES.md
    FRONTEND_INTEGRATION.md
  core/
    persistence/
      mongo_client.py
    security/
      auth.py
      guardrails.py
      middleware.py
      output_safety.py
      audit.py
    orchestration/
      builder.py
      executor.py
      executor_nodes/
    tools/
    memory/
    arena/
      playground/
        router_registry.py
        routers/
        services/
        agents/
        models/
        middleware/
        utils/
```

## Main Modules

`main.py`

Single FastAPI entry point. Starts MongoDB, registers tools, mounts static files, exposes dynamic-agent routes, and mounts Arena routes.

`core/persistence`

MongoDB data access layer. Owns existing agent collections and new `arena_*` collections.

`core/security`

Authentication, JWT, guardrails, PII handling, audit logging, and output safety. This is the source of truth for security across the whole backend.

`core/orchestration`

Dynamic agent creation and execution workflow. Includes the agent blueprint builder and LangGraph executor.

`core/tools`

Tools available to dynamic agents, such as file extraction, web search, email, report generation, Python execution, summarization, and speech-to-text.

`core/memory`

Semantic memory support using Chroma when available and MongoDB fallback vectors.

`core/arena/playground`

Imported Arena feature module. Contains Azure AI service routes, fixed business agents, Arena chat APIs, credential APIs, and database/usage integration helpers.

## Security Boundary

Security logic lives in one place:

```text
core/security/
```

Auth dependencies are split by return shape:

```text
get_current_user_id()   -> username/user id string for dynamic-agent APIs
get_current_user_doc()  -> normalized user document for Arena APIs
```

Arena routers import directly from `core/security/auth.py`:

```text
/api/arena/*
  -> Arena router
  -> core/security/auth.py
  -> shared users collection
```

Guardrails, output safety, request middleware, audit, JWT handling, and user lookup remain owned by `core/security`. Arena keeps `middleware/hit_counter.py` only for Arena usage tracking, not authentication.

## Database Separation

Existing dynamic-agent collections:

```text
users
agents
threads
messages
memory_summaries
memory_vectors
token_usage
```

New Arena feature collections:

```text
arena_chats
arena_credentials
arena_files
arena_usage_events
arena_service_runs
arena_agent_runs
arena_agent_definitions
arena_db_mappings
arena_data_tables
arena_data_rows
```

Important rule:

```text
Arena features must write only to arena_* collections.
Dynamic agent runtime keeps using agents, threads, messages, memory, and token_usage.
```

## What Is Mounted

Mounted:

```text
/api/arena/chats
/api/arena/credentials
/api/arena/openai
/api/arena/search
/api/arena/vision
/api/arena/document
/api/arena/language
/api/arena/speech
/api/arena/translator
/api/arena/content_safety
/api/arena/video/upload
/api/arena/image
/api/arena/recruitment
/api/arena/legal
/api/arena/compliance
/api/arena/data-insights
/api/arena/invoice-finance
/api/arena/gd
/api/arena/call-audit
```

Not mounted:

```text
Copied Arena auth routes
Copied SQL/DuckDB route
```

Reason:

- Auth is handled by the main backend.
- SQL/DuckDB is excluded because the project is moving MongoDB-only.

## Documentation Links

- [Project Overview](PROJECT_OVERVIEW.md)
- [Folder Structure](FOLDER_STRUCTURE.md)
- [API Reference](API_REFERENCE.md)
- [Data Model](DATA_MODEL.md)
- [Workflows](WORKFLOWS.md)
- [Modules](MODULES.md)
- [Frontend Integration Notes](FRONTEND_INTEGRATION.md)
- [Call Audit Audio Pipeline](CALL_AUDIT_AUDIO_PIPELINE.md)

## Recommended Reading Order

For frontend engineers:

```text
1. FRONTEND_INTEGRATION.md
2. API_REFERENCE.md
3. WORKFLOWS.md
4. DATA_MODEL.md
```

For backend engineers:

```text
1. PROJECT_OVERVIEW.md
2. FOLDER_STRUCTURE.md
3. MODULES.md
4. DATA_MODEL.md
5. WORKFLOWS.md
```
