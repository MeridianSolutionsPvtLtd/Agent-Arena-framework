# Project Overview

This backend has two integrated systems.

## 1. Dynamic Agent System

The original `Meridian-Agentic-Ai-Backend` system. It lets users create custom AI agents from natural language, stores an agent blueprint, and runs the agent through a multi-step orchestration workflow.

Main capabilities:

- User signup/login.
- Agent preview and creation.
- Agent blueprint storage.
- Agent config editing.
- File upload.
- Agent execution.
- Human-in-the-loop plan approval.
- Real-time trace WebSocket.
- Conversation history.
- Blackboard and sub-agent histories.
- Long-context memory summaries.
- Mongo/Chroma semantic memory.
- Token usage tracking.
- Agent export as blueprint, ZIP, or desktop client.

Main code:

```text
main.py
core/orchestration/
core/tools/
core/persistence/
core/security/
core/memory/
```

## 2. Arena Feature System

The imported `meridianaiarena-backend` feature set. It provides fixed Azure AI service APIs and fixed business-agent APIs.

Mounted in the main app through:

```text
core/arena/playground/router_registry.py
```

Public frontend path:

```text
/api/arena/*
```

Main capabilities:

- OpenAI chat.
- Search upload/query.
- Vision image analysis.
- Document analysis.
- Language analysis.
- Speech to text.
- Text to speech.
- Translator.
- Content safety.
- Image generation.
- Video analysis.
- Fixed agents such as recruitment, legal, compliance, data insights, invoice finance, group discussion, and call audit.

Important exclusions:

- Copied Arena auth routes are not mounted. Main auth remains canonical.
- Copied SQL/DuckDB route is not mounted. MongoDB-only table storage is planned through `arena_data_tables` and `arena_data_rows`.

## Integration Boundary

Shared:

```text
users
main FastAPI app
main JWT auth
main Mongo connection
```

Separated:

```text
dynamic-agent runtime collections
arena feature collections
```

This prevents old dynamic-agent work from being broken by the new Arena feature.

## Security Integration

The main project security package remains canonical:

```text
core/security/
```

It owns:

```text
auth.py
guardrails.py
audit.py
output_safety.py
middleware.py
```

Auth dependencies are provided directly from `core/security/auth.py`:

```text
get_current_user_id()
get_current_user_doc()
```

Dynamic-agent APIs use `get_current_user_id()` when they need the username string. Arena APIs use `get_current_user_doc()` when they need a normalized user document with `_id`, profile fields, and storage counters.

Arena keeps only usage tracking under `core/arena/playground/middleware/hit_counter.py`; JWT auth and user lookup are not duplicated there.

Request flow:

```text
/api/arena/*
  -> router_registry.py
  -> Arena router
  -> core/security/auth.py get_current_user_doc()
  -> users
```
