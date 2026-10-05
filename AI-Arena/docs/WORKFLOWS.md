# Workflows

## Startup Workflow

```text
FastAPI lifespan starts
  -> AgentRegistryDB.connect()
  -> AgentRegistryDB.ensure_indexes()
  -> register_default_tools()
  -> static/output folders created
```

Arena routes are mounted during import:

```text
main.py
  -> build_arena_router()
  -> app.include_router(...)
```

## Dynamic Agent Creation

```text
Frontend calls POST /agents/preview
  -> AgentBuilder.build()
  -> LLM creates AgentBlueprint
  -> response returned, not saved

Frontend reviews blueprint
  -> POST /agents/create
  -> AgentRegistryDB.save_agent()
  -> document saved in agents
```

Agent blueprint contains:

```text
name
domain
tools
crew_roles
system_prompt
validator_config
executor_policy
user_intent
```

## Dynamic Agent Run

```text
POST /agents/{agent_id}/run
  -> verify user owns agent
  -> sanitize input
  -> tokenize PII
  -> persist user message
  -> load recent messages
  -> load summary
  -> search semantic memory
  -> build enriched history
  -> AgentExecutor.run()
```

Executor graph:

```text
shield
  -> planner
  -> compiler
  -> execute
  -> validator
  -> safety
```

After execution:

```text
persist assistant message
persist blackboard
persist sub-agent histories
persist collaboration payload
persist memory vectors
maybe write summary
record token usage
return response
```

## Human-In-The-Loop Plan Approval

Some runs return:

```json
{
  "hitl_pending": true,
  "flight_plan_steps": []
}
```

Frontend should show the plan and ask for approval.

When user says "yes" or "approved":

```text
POST /agents/{agent_id}/run
  -> shield recovers previous plan
  -> executor runs approved plan
```

## Trace WebSocket

Frontend connects:

```text
WS /api/ws/trace/{trace_id}
```

Backend emits node/status events:

```text
executor started
shield analyzing
planner generating
compiler compiling
execute running tool
validator checking
safety finalizing
```

## Arena API Workflow

Frontend calls:

```text
/api/arena/<feature>
```

Middleware strips `/api`, so backend sees:

```text
/arena/<feature>
```

Arena router calls:

```text
core/security/auth.py get_current_user_doc()
  -> AgentRegistryDB.get_user()
  -> normalized user dict
```

Service credentials:

```text
get_user_credentials()
  -> arena_credentials lookup
  -> decrypt
  -> fallback to env setting
```

Usage:

```text
increment_hit_count()
  -> arena_usage_events insert
```

## Arena Chat Workflow

```text
POST /api/arena/chats
  -> create arena_chats document

PUT /api/arena/chats/{chat_id}
  -> append message or update title

GET /api/arena/chats
  -> list user's Arena chats
```

## Arena Credentials Workflow

```text
POST /api/arena/credentials
  -> encrypt credential
  -> upsert arena_credentials by user_id + key_name

GET /api/arena/credentials
  -> list credential names, not values

DELETE /api/arena/credentials/{key_name}
  -> delete one credential
```

## Arena Service Workflow

Example document analysis:

```text
POST /api/arena/document/analyze
  -> core/security/auth.py get_current_user_doc()
  -> get Azure Document credentials
  -> read uploaded file bytes
  -> call Azure Document Intelligence
  -> return result
  -> record usage event
```

## What Is Not Mounted

Copied Arena auth:

```text
core/arena/playground/routers/auth.py
```

Reason: main auth is canonical.

Copied SQL/DuckDB:

```text
core/arena/playground/agents/sql_agent/router.py
```

Reason: project is MongoDB-only. Use `arena_data_tables` and `arena_data_rows` for future implementation.
