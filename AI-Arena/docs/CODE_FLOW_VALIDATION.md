# Code Flow Validation

## Canonical infrastructure ownership

The cleanup enforces these boundaries:

| Concern | Canonical implementation | Runtime consumer |
|---|---|---|
| Mongo client lifecycle | `database.py` | `AgentRuntimeStore.connect(get_db())` |
| JWT authentication | `middleware/auth.py` | All Arena and agent routers |
| Unified agent coordination | `services/agent_service.py` | `routers/agents.py` |
| Runtime persistence methods | `core/persistence/runtime_store.py` | Agent runtime and agent service |
| Agent guardrails | `core/security/` | Agent runtime and graph nodes |

Removed compatibility files:

```text
auth.py
core/security/auth.py
core/security/middleware.py
core/persistence/mongo_client.py
```

Architecture regression tests fail if these files or their imports return.

## Request validation flow

```text
HTTP request
  -> FastAPI/Pydantic validates shape and size
  -> middleware.auth validates access JWT
  -> users collection confirms the subject still exists
  -> router passes current_user["_id"] to AgentService
  -> AgentService applies ownership, visibility, status, and capability rules
```

The request cannot provide an owner ID or select `agent_kind` for execution.

## Database validation flow

```text
main.lifespan
  -> database.connect_to_mongo()
  -> database.get_db()
  -> initialize_agent_storage()
  -> AgentRuntimeStore.connect(existing_db)
```

`AgentRuntimeStore` contains collection operations but imports no Motor client
and owns no connection lifecycle. `database.close_mongo_connection()` remains
the only shutdown owner.

## Custom execution validation flow

```text
POST /api/agents/{id}/run
  -> accessible active agent lookup
  -> owner check for custom agent
  -> input-hash audit record
  -> AgentRuntimeService performs a second owner lookup
  -> sanitization, PII and injection checks
  -> authorized file-path validation
  -> LangGraph execution
  -> output safety and bounded retries
  -> message/memory/token persistence
  -> Arena chat and usage persistence
  -> normalized response
```

The repeated ownership lookup is intentional defense in depth at the API and
runtime boundaries.

## Prebuilt execution validation flow

```text
POST /api/agents/{id}/run
  -> load public active prebuilt document
  -> read server-seeded config.handler
  -> dispatch to existing Arena service
  -> normalize response, tokens, audit, and chat data
```

The client cannot provide or override the handler.

## File validation flow

```text
multipart upload
  -> agent tool capability policy
  -> extension and streamed byte limit
  -> user storage quota
  -> randomized Blob name
  -> user-scoped local execution path
  -> exact allowlist match inside graph tool execution
```

Planner-generated paths are never accepted merely because a server file exists.

## Automated validation

Run:

```powershell
python -m pytest
```

The suite validates:

- canonical auth imports;
- absence of the old Mongo client and duplicate auth modules;
- runtime store connection ownership;
- ownership-scoped CRUD;
- blueprint/tool validation;
- safe-default feature gates;
- file-boundary rejection;
- audit privacy;
- export privacy.

Additional release checks validate all Python ASTs, complete FastAPI OpenAPI
generation, safe tool registration, SSRF blocking, and portable ZIP contents.
