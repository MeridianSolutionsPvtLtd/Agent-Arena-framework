# Custom agent lifecycle: startup, creation, and execution

This guide follows one custom agent from application startup to a completed run. It is intended as a hands-on map for Postman testing and code navigation. Line numbers can move as the code evolves; the function names and file paths are the stable references.

## 1. High-level flow

```text
Process starts
  -> main.lifespan()
     -> validate settings
     -> connect MongoDB
     -> create/repair indexes
     -> optional bootstrap user
     -> warm Ollama + embedding model
     -> register routers

POST /api/auth/login
  -> access token

POST /api/agents/preview
  -> LLM creates a draft blueprint
  -> capability catalog validates selected tools

POST /api/agents/blueprint
  -> validate ownership/tool_refs/policy
  -> persist custom agent
  -> return agent_id

POST /api/agents/{agent_id}/run
  -> service loads agent and thread
  -> LangGraph: shield -> planner -> compiler -> safety -> execution -> validator
  -> native/external MCP tool broker
  -> plan/tool approval when required
  -> final response + thread/audit state
```

## 2. Startup: what runs and why

| Location | Function | Why it exists |
|---|---|---|
| `main.py:76` | `lifespan(app)` | FastAPI startup/shutdown boundary. It fails startup if required infrastructure cannot be initialized. |
| `config.py` | `validate_security_settings()` | Rejects unsafe/missing production settings before serving traffic. |
| `database.py:11` | `connect_to_mongo()` | Creates the application Mongo client/database handle. |
| `services/agent_service.py` | `initialize_agent_storage()` | Creates/repairs indexes for agents, threads, runs, capabilities, tool executions, and related state. Empty Mongo collections may not appear in Compass until a document is written. |
| `main.py:37` | `seed_default_user()` | Optional bootstrap user only when `SEED_DEFAULT_USER` is enabled. |
| `core/orchestration/azure_settings.py` | `warmup_ollama_models()` | Loads the configured local chat model and HF embedding model before the first request, avoiding first-request model-load latency. |
| `agents/call_audit/service.py` | `warmup_azure_stt()` | Background warm-up for the separate speech-to-text path; it is not used by normal custom-agent planning. |
| `database.py:25` | `close_mongo_connection()` | Graceful shutdown cleanup. |
| `main.py:99-163` | `app = FastAPI(...)`, `include_router(...)` | Builds the API and registers auth, files, agents, capabilities, MCP, tool-execution, and registry routes. |
| `core/startup/indexes.py:82` | `ensure_index(collection, keys, **options)` | Idempotently ensures one Mongo index; repeated startup/recovery calls are safe. |

Health checks: `GET /health` and `GET /api/health` are implemented in `main.py:167-180`.

## 3. Authenticate first

`routers/auth.py:50` implements `POST /api/auth/login`. Send JSON credentials and save the returned bearer token. All custom-agent, file, capability, MCP, and approval routes depend on `get_current_user` from `middleware/auth.py`.

```http
POST http://127.0.0.1:5000/api/auth/login
Content-Type: application/json

{
  "email": "<user email>",
  "password": "<password>"
}
```

Use the token on every later request:

```http
Authorization: Bearer <access token>
```

## 4. Choose tools and create a custom agent

### 4.1 Discover builder tools

`routers/capabilities.py:162` implements `GET /api/capabilities/builder/tools`. It reads the owner-scoped authoritative catalog. The UI should use the returned `capability_id`, `version`, lifecycle state, and approval metadata rather than inventing them.

Native tool seed definitions are in `core/tooling/capability_seed.py`. External MCP registration/discovery is handled by `routers/capabilities.py:179-385` and `core/tooling/external_mcp.py`.

### 4.2 Preview a blueprint (does not save)

`routers/agents.py:50` -> `services/agent_service.py:322` (`preview_custom_agent()`). The preview validates the proposed agent and returns a blueprint. This is the point where a frontend can show the user the plan, roles, and selected tools for review.

```http
POST http://127.0.0.1:5000/api/agents/preview
Authorization: Bearer <token>
Content-Type: application/json

{
  "name": "Web research agent",
  "query": "Search the internet, summarize the findings, and create a report.",
  "conversation_history": ""
}
```

### 4.3 Save the reviewed blueprint

`routers/agents.py:63` -> `services/agent_service.py:389` (`create_custom_agent_from_blueprint()`). The service validates the blueprint, owner/tenant fields, tool references, and governance policy before inserting the custom agent document.

```http
POST http://127.0.0.1:5000/api/agents/blueprint
Authorization: Bearer <token>
Content-Type: application/json

{
  "blueprint": <paste the reviewed blueprint returned by /preview>
}
```

Important frontend contract: `core/orchestration/builder.py:79-146` (`_apply_tool_allowlist()`) resolves selected tools into exact `tool_refs`. The backend validator `services/agent_service.py:272` (`_validate_active_tool_refs()`) expects one active version reference for every governed tool. If the UI changes “Active Toolkit” but sends only tool names and omits/stales `tool_refs`, `/api/agents/blueprint` returns HTTP 400.

The builder implementation is `core/orchestration/builder.py:32` (`AgentBuilder`) and `:191` (`build()`). The catalog implementation is `core/tooling/capability_catalog.py`; it scopes records by owner/tenant and is the source of truth for approval metadata.

## 5. Run the custom agent

### 5.1 Text run

`routers/agents.py:115` -> `services/agent_service.py:1061` (`run_agent()`) -> `core/agent_runtime/service.py:194` (`run_agent()`).

```http
POST http://127.0.0.1:5000/api/agents/{agent_id}/run
Authorization: Bearer <token>
Content-Type: application/json

{
  "message": "Search the latest electric-vehicle developments in India, summarize the evidence, and create a professional report.",
  "thread_id": null,
  "chat_id": null,
  "file_ids": [],
  "payload": {}
}
```

The response may be:

- `status: success`: final answer is in `response`.
- `status: pending_approval`, `approval_type: plan`: approve the proposed flight plan, then resume the run according to the client flow.
- `status: pending_approval`, `approval_type: tool`: a governed tool is waiting for approval; use the tool-execution endpoint below.
- HTTP 4xx/5xx: inspect `detail.code`, `detail.message`, `trace_id`, and server logs.

### 5.2 Upload a file, then run

The upload route is **`POST /api/agents/files`**, not `/api/agent-files/upload`. It is implemented by `routers/agent_files.py:33` (`upload_agent_files`). The multipart field must be named `files` and must contain a real file part, not a Windows path string.

```http
POST http://127.0.0.1:5000/api/agents/files
Authorization: Bearer <token>
Content-Type: multipart/form-data

files = <select a local PDF in Postman>
```

The response returns `file_id` values. Pass them to the normal run:

```json
{
  "message": "Analyze the uploaded document and summarize it.",
  "thread_id": null,
  "file_ids": ["<file_id returned by /api/agents/files>"],
  "payload": {}
}
```

For one-request multipart execution, use `POST /api/agents/{agent_id}/run-file`, implemented at `routers/agents.py:153` and `services/agent_service.py:823`. Its multipart fields are `file`, `message`, `thread_id`, `chat_id`, and JSON string `payload`.

## 6. Runtime graph: where the work happens

`core/orchestration/executor.py:19` (`AgentExecutor.build_executor()`) constructs the LangGraph-style runtime. The important nodes are:

| Node | Location | Responsibility |
|---|---|---|
| Shield / intent | `core/orchestration/executor_nodes/shield.py:143` (`shield_node`) | Classifies conversation vs agentic work, reads blueprint context, and determines whether plan/tool approval is needed. A simple “hello” can finish as a direct conversation. |
| Planner | `core/orchestration/executor_nodes/planner.py:39` (`planner_node`) | Converts an agentic request plus blueprint roles/tools into an ordered flight plan. It has a validated blueprint fallback when the local model does not produce valid JSON. |
| Compiler | `core/orchestration/executor_nodes/compiler.py` | Converts the plan into executable step contracts and governed tool references. |
| Safety | `core/orchestration/executor_nodes/safety.py:15` (`safety_node`) | Applies safety/policy checks before execution. |
| Execution | `core/orchestration/executor_nodes/execution.py:1928` (`execution_node`) | Runs steps sequentially, maintains state/blackboard, calls the broker, records outputs, and preserves verified web URLs for later report generation. |
| Validator | `core/orchestration/executor_nodes/validator.py` | Validates the final model output and applies the safe fallback when local-model JSON is malformed. |
| Runtime service | `core/agent_runtime/service.py:194` (`run_agent`) | Persists thread/run state, handles resumes, maps typed failures, and returns the stable API response. |

For web research, execution calls the selected `web_search` tool, passes its structured evidence to `summarize_content`, then passes the summary and verified URLs to `generate_report`. Each tool remains independently governed; the report tool does not decide whether search results are relevant.

## 7. MCP and approval flow

### Native/local governed tools

The catalog seed is `core/tooling/capability_seed.py`. Dispatch is centralized in `core/tooling/execution_broker.py`, which checks assignment, lifecycle, scopes, idempotency, and approval policy before calling a tool. Native/external transport errors are normalized by `core/tooling/mcp_tool_client.py`.

### External MCP servers

The onboarding API is in `routers/mcp_connections.py`:

| Method | Endpoint | Function |
|---|---|---|
| GET | `/api/mcp/templates` | `list_mcp_templates()` (`:100`) |
| POST | `/api/mcp/connections` | `connect_mcp()` (`:139`) |
| POST | `/api/mcp/inspect` | `inspect_mcp_authentication()` (`:166`) |
| POST | `/api/mcp/connections/{id}/{version}/tools` | `select_mcp_tools()` (`:251`) |
| POST | `/api/mcp/connections/{id}/{version}/validate` | `validate_mcp_connection()` (`:275`) |
| POST | `/api/mcp/connections/{id}/{version}/reconnect` | `reconnect_mcp_connection()` (`:298`) |
| DELETE | `/api/mcp/connections/{id}/{version}` | `disconnect_mcp_connection()` (`:317`) |

OAuth helpers are `/api/mcp/oauth/client-metadata`, `/api/mcp/oauth/start`, and `/api/mcp/oauth/callback` (`routers/mcp_connections.py:177-221`).

### Tool approval from Postman

When a run returns `approval_type: tool`, use the returned `tool_execution_id`:

```http
GET http://127.0.0.1:5000/api/tool-executions/{tool_execution_id}
Authorization: Bearer <token>
```

Approve/reject with the enum values shown by the API (`not_required`, `pending`, `approved`, `rejected`, `expired`):

```http
POST http://127.0.0.1:5000/api/tool-executions/{tool_execution_id}/approval
Authorization: Bearer <token>
Content-Type: application/json

{
  "decision": "approved",
  "reason": "Approved by user"
}
```

Then resume:

```http
POST http://127.0.0.1:5000/api/tool-executions/{tool_execution_id}/resume
Authorization: Bearer <token>
```

These endpoints are implemented in `routers/tool_executions.py:49-100`; persistence and optimistic revision checks are in `core/tooling/tool_execution_store.py`.

## 8. Debugging checklist

1. **401 Unauthorized**: token missing/expired; verify login and the `Authorization` header.
2. **400 on `/blueprint`**: inspect the request’s `tools` and `tool_refs`; every governed tool needs one active catalog version. Check `services/agent_service.py:_validate_active_tool_refs()`.
3. **422 on file upload**: use multipart key `files` (or `file` for `/run-file`) and select a real Postman file. Do not send a path as JSON/text.
4. **Plan JSON parse failure**: inspect planner logs and the blueprint fallback in `planner.py`; this is a model-output problem, not a Mongo failure.
5. **MCP unavailable / 503**: inspect `execution_broker.py`, `mcp_tool_client.py`, and the tool execution record by `tool_execution_id`.
6. **Summarization timeout**: inspect the local Ollama endpoint/model, `core/tools/summarize_content.py`, and the catalog timeout. The structured failure should remain a tool failure, not be treated as summary text.
7. **No report sources**: inspect the `[Execution] web_search verified URLs` log and the report-source merge in `execution.py`; the report only receives URLs that survived the web-search result normalization.
8. **Slow first request**: confirm the startup warm-up completed. `warmup_ollama_models()` loads the chat and embedding models during lifespan.

## 9. Minimal hands-on test order

1. `GET /api/health`.
2. `POST /api/auth/login` and save the token.
3. `GET /api/capabilities/builder/tools`.
4. `POST /api/agents/preview`.
5. `POST /api/agents/blueprint` using the reviewed blueprint.
6. `POST /api/agents/{agent_id}/run` with a simple conversation (`hello`) to verify the no-tool path.
7. Run an agentic request that requires one safe read-only tool; approve the plan if returned.
8. If a tool approval is returned, `GET` the execution, `POST /approval`, then `POST /resume`.
9. Test `/api/agents/files` and then a run with the returned `file_id`.

This order isolates authentication, creation, conversation classification, agentic planning, governed execution, approvals, and file ingestion instead of debugging all layers at once.
