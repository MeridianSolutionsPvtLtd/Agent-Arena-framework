# Modules and Functionality

## `main.py`

Primary FastAPI application.

Responsibilities:

- Starts and stops MongoDB connection.
- Creates required local folders.
- Registers default dynamic-agent tools.
- Mounts static `/static` and `/outputs`.
- Mounts Arena feature router at `/arena`.
- Defines dynamic-agent APIs.
- Defines trace WebSocket.
- Wraps app with `ApiPrefixMiddleware` so `/api/...` works behind gateway.

## `core/persistence`

Database layer.

Main file:

```text
core/persistence/mongo_client.py
```

Responsibilities:

- MongoDB connection lifecycle.
- Existing dynamic-agent collections.
- New Arena `arena_*` collections.
- Best-effort index creation.
- Agent CRUD.
- User CRUD.
- Thread/message CRUD.
- Memory summary/vector CRUD.
- Token usage recording.
- Arena chat, credential, file, usage, service-run, agent-run, and data-table helpers.

## `core/security`

Authentication, input safety, output safety, and audit. This folder is the security source of truth for both the dynamic-agent APIs and the Arena APIs.

Files:

```text
auth.py
guardrails.py
middleware.py
output_safety.py
audit.py
```

Responsibilities:

- Password hashing.
- JWT access and refresh tokens.
- `get_current_user_id` dependency for dynamic-agent APIs.
- `get_current_user_doc` dependency for Arena APIs.
- Request logging and `/api` path normalization middleware.
- Prompt-injection detection.
- PII masking and tokenization.
- Output cleanup and safety checks.
- Audit event logging.
- Canonical guardrail, auth, and audit behavior for the whole backend.

## `core/orchestration`

Dynamic agent architecture and runtime.

Files:

```text
builder.py
executor.py
registry.py
state.py
trace.py
executor_nodes/
```

Responsibilities:

- Build agent blueprints from user intent.
- Store crew roles, tools, prompts, validator config, and executor policy.
- Build LangGraph executor.
- Emit trace events.
- Route execution through shield, planner, compiler, execute, validator, and safety nodes.

## `core/orchestration/executor_nodes`

Step-by-step execution nodes.

`shield.py`

- Sanitizes request context.
- Classifies intent.
- Handles plan approval recovery.
- Checks missing tools and email requirements.

`planner.py`

- Generates scoped execution plan.
- Assigns steps to tools and sub-agent roles.

`compiler.py`

- Converts readable plan to machine-executable JSON steps.

`execution.py`

- Runs tools.
- Manages step outputs.
- Updates blackboard.
- Tracks sub-agent histories.
- Synthesizes final answer.

`validator.py`

- Checks plan adherence.
- Checks validator checklist.
- Requests one retry if needed.

`safety.py`

- Cleans final output.
- Removes tool leakage.
- Detokenizes PII.
- Applies output safety checks.

## `core/tools`

Tool implementations for dynamic agents.

Important tools:

```text
extract_data_from_file
generate_report
send_email
execute_python
summarize_content
web_search
mailbox_tracker_graph
speech_to_text
data_collector_visualizer
```

Responsibilities:

- File extraction.
- Report generation.
- Email sending.
- Python calculation.
- Web search and source extraction.
- Audio transcription.
- Data collection and visualization.

## `core/memory`

Long-term semantic memory.

File:

```text
chroma_store.py
```

Responsibilities:

- Optional Chroma vector store.
- Semantic recall support.
- Graceful fallback to Mongo `memory_vectors`.

## `core/arena/playground`

Integrated Meridian AI Arena feature area.

This code was imported from the second backend and adapted to run inside the main project.

Important files:

```text
router_registry.py
database.py
middleware/hit_counter.py
services/keyvault_service.py
```

Responsibilities:

- Build safe Arena router mounted at `/arena`.
- Use main MongoDB connection.
- Use main JWT auth directly from `core/security/auth.py`.
- Store Arena credentials in `arena_credentials`.
- Store Arena chats in `arena_chats`.
- Store Arena usage in `arena_usage_events`.

Security note:

```text
core/security/
```

owns real auth, guardrails, output safety, and audit logic.

```text
core/arena/playground/middleware/hit_counter.py
```

is only Arena usage tracking. Authentication is not duplicated in Arena middleware.

## `core/arena/playground/routers`

Direct service APIs.

Mounted routes include:

```text
chats
credentials
openai
search
vision
document
language
speech
translator
content_safety
video
image
```

The copied `auth` router is not mounted.

## `core/arena/playground/services`

Service implementations used by Arena routers.

Responsibilities:

- Azure OpenAI.
- Azure Search.
- Azure Vision.
- Azure Document Intelligence.
- Azure Language.
- Azure Speech.
- Azure Translator.
- Azure Content Safety.
- Azure Blob support.
- Image generation.
- Video processing.
- Credential encryption/decryption.

## `core/arena/playground/agents`

Fixed business agents imported from the Arena backend.

Mounted agents:

```text
call_audit
recruitment
group_discussion
compliance
data_insights
invoice_finance
legal
```

Not mounted:

```text
sql_agent
```

Reason: old implementation uses DuckDB. The project direction is MongoDB-only.

## `docs`

Human-facing project documentation.

Files:

```text
PROJECT_OVERVIEW.md
FOLDER_STRUCTURE.md
API_REFERENCE.md
DATA_MODEL.md
WORKFLOWS.md
MODULES.md
FRONTEND_INTEGRATION.md
```
