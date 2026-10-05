# Agent System: Complete Workflow

## 1. System boundaries

`meridianaiarena-backend` is the only FastAPI application and owns:

- application startup and shutdown;
- JWT authentication and user lookup;
- the Motor client and MongoDB database;
- public API contracts;
- encrypted user credentials;
- Arena chats, storage quotas, and usage counters;
- existing prebuilt-agent services.

The migrated `core/` package is a runtime library. It owns:

- blueprint generation;
- LangGraph orchestration;
- specialist-role execution;
- tool registration and invocation;
- guardrails, PII handling, and output safety;
- thread memory, summaries, vectors, token accounting, and traces.

`core.persistence.AgentRuntimeStore` does not open another connection. During
Arena startup it binds its collection methods to `database.get_db()`.

## 2. Startup workflow

```text
FastAPI lifespan
  -> validate JWT and optional bootstrap settings
  -> connect Arena Motor client
  -> optionally seed explicitly configured bootstrap user
  -> bind AgentRuntimeStore to the same database
  -> register enabled tools
  -> create agent/runtime indexes
  -> idempotently upsert prebuilt definitions into agents
  -> accept requests
```

Startup fails instead of serving a partially initialized API when security,
MongoDB, tool dependencies, indexes, or seeding cannot initialize correctly.

## 3. Unified agent document

Both kinds live in `agents`:

```text
agent_kind=prebuilt
  -> user_id=null
  -> visibility=public
  -> config.handler selects an existing Arena service

agent_kind=custom
  -> user_id=<JWT user id>
  -> visibility=private
  -> system_prompt + tools + crew_roles + policies define runtime behavior
```

The client may send a MongoDB ObjectId or stable `agent_id` when reading/running an
agent. The service loads the document first and derives `agent_kind` from the
database; client input never selects the executor.

## 4. NLP agent creation workflow

```text
POST /api/agents/preview
  -> AgentBuilder reads registered tool metadata
  -> LLM converts user intent into system prompt, crew roles, tool assignments,
     validator checklist, and execution policy
  -> server validates the LLM-produced object as untrusted input
  -> return preview without persistence

POST /api/agents/blueprint
  -> validate reviewed blueprint again
  -> discard supplied owner/id fields
  -> assign server-owned identity and authenticated owner
  -> insert into agents
```

Every role's `assigned_tools` must be a subset of the agent-level `tools`.

## 5. Text execution workflow

```text
POST /api/agents/{id}/run
  -> authenticate JWT
  -> load accessible active agent
  -> create running agent_runs audit record using input SHA-256 (not raw input)
  -> dispatch by stored agent_kind
```

### Prebuilt branch

```text
config.handler
  -> existing compliance/data-insights/GD/recruitment/legal service
  -> normalize service response and token usage
```

File-specialized prebuilt agents retain their existing direct endpoints.

### Custom branch

```text
AgentRuntimeService.run_agent
  -> verify agent ownership again in AgentRuntimeStore
  -> sanitize query and conversation history
  -> tokenize protected PII
  -> analyze prompt-injection signals
  -> create/reuse thread and append user message
  -> load recent turns, latest summary, and semantic memories
  -> validate referenced files against uploads/<user-id> boundary
  -> recover approved plan/blackboard when continuing a HITL run
  -> invoke AgentExecutor in a worker thread
```

## 6. Orchestration graph

```text
shield
  -> unsafe: stop
  -> side effect requiring approval: return HITL plan
  -> approved existing plan: compiler
  -> normal request: planner

planner
  -> create structured, role-aware steps from available tools
  -> compiler

compiler
  -> compile specialist tasks and execution context
  -> execute

execute
  -> invoke only registered and role-authorized tools
  -> update blackboard, step outputs, and sub-agent histories
  -> validator

validator
  -> score output against blueprint checklist
  -> one controlled retry when required
  -> safety

safety
  -> enforce output safety, factual/tool evidence, URL/email rules
  -> one bounded retry when allowed
  -> final response
```

Loop guards prevent unbounded validator/safety retries.

## 7. Human approval workflow

For sensitive side effects such as email:

```text
initial request
  -> shield/planner produce structured plan
  -> response contains hitl_pending=true and flight_plan_steps
  -> plan and blackboard persist with assistant message

follow-up "approved" / "continue"
  -> runtime loads the same thread
  -> recovers the exact persisted plan and approved file paths
  -> shield recognizes approval
  -> compiler executes the pre-approved plan
```

Approval does not grant new tools or paths; the original blueprint and file
allowlists still apply.

## 8. Tool workflow and security

Enabled migrated tools:

- `extract_data_from_file`
- `generate_report`
- `send_email`
- `summarize_content`
- `web_search`
- `mailbox_tracker_graph`
- `speech_to_text`

`execute_python` code is present for parity but disabled by default because a
subprocess timeout is not an operating-system security boundary. Enable it only
inside a dedicated sandbox using `ENABLE_UNSAFE_PYTHON_TOOL=true`.

`data_collector_visualizer` is also present for parity but disabled by default
because it performs broad automated outbound collection. Enable it only behind
restricted egress and isolated credentials using `ENABLE_ADVANCED_WEB_TOOL=true`.
The standard `web_search` scraper rejects local, private, link-local, reserved,
and non-HTTP(S) targets.

File tools receive paths exclusively from the authenticated request's validated
`file_paths` state. A planner-created path is accepted only when its resolved
path exactly matches that allowlist. The extractor no longer searches global
temporary/upload directories for filename matches.

## 9. Custom file workflow

```text
POST /api/agents/{id}/run-file
  -> verify custom-agent ownership and active status
  -> derive allowed extensions/size from configured tools
  -> stream-read with a hard size limit
  -> upload a randomized safe blob name and update user quota
  -> save a randomized local execution copy under uploads/<user-id>/
  -> pass the authorized absolute path to the graph runtime
  -> delete local copy after completion
```

If a HITL plan is pending, the local copy is retained for its approved
continuation. Blob quota-accounting failure triggers blob rollback.

## 10. Completion and persistence

After a custom run:

```text
executor response
  -> detokenize protected PII for the authorized response
  -> append assistant message with collaboration metadata
  -> update semantic vector memory
  -> periodically create thread summary
  -> record per-query and cumulative token usage
  -> optionally append user/assistant messages to Arena chat_id
  -> mark agent_runs success/error
  -> increment Arena agent hit/token counters
  -> return unified AgentRunResponse
```

Raw request text is not duplicated in `agent_runs`. Full conversation content
exists only in the conversation stores required for product functionality.

## 11. Management endpoints

```text
GET    /api/agents
POST   /api/agents/preview
POST   /api/agents/blueprint
GET    /api/agents/{id}
PATCH  /api/agents/{id}
DELETE /api/agents/{id}
POST   /api/agents/{id}/run
POST   /api/agents/{id}/run-file
GET    /api/agents/{id}/config
PATCH  /api/agents/{id}/config
DELETE /api/agents/{id}/history
GET    /api/agents/{id}/context
GET    /api/agents/{id}/blackboard
GET    /api/agents/{id}/sub-agent-histories
GET    /api/agents/{id}/export?format=blueprint|zip
```

All custom management and runtime-state endpoints enforce owner equality using
the authenticated user ID.

Exports are owner-authenticated and use `Cache-Control: no-store`. Blueprint
exports remove database ownership and internal timestamp fields. Portable ZIPs
contain the reviewed blueprint, CLI runner, runtime, dependency list, and empty
environment template. Temporary ZIPs are deleted after the response completes.

The legacy request-time Tauri/Windows executable compiler is intentionally not
exposed. Application servers do not run npm/Rust/linker supply-chain builds.

## 12. Failure behavior

- Validation and unsupported capability: `400`
- Authentication failure: `401`
- Missing or inaccessible agent/chat: `404`
- File too large: `413`
- Optional service unavailable: `503`
- Upstream Azure/tool failure: safe `5xx` response with detailed server log

Unexpected exception strings are not returned to clients by the unified agent
runtime.
## 12. Secure conversation threads

Custom agents and every prebuilt agent executed through the unified API use an application-owned
`thread_id`. The client must never send or store an Azure/provider thread ID.

- Omit `thread_id` (or send `null`) to create a new conversation.
- Send a previously returned application `thread_id` to continue it.
- List switchable conversations with `GET /api/agents/{agent_id}/threads`.
- Load one conversation with
  `GET /api/agents/{agent_id}/threads/{thread_id}/messages`.

Every lookup is scoped by the authenticated `user_id`, canonical `agent_id`,
and application `thread_id`. Prebuilt thread records privately store the
provider identifier in `provider_thread_id`. A thread owned by another user or
agent returns `404`.

Example new-chat request:

```json
{
  "message": "Review this policy",
  "thread_id": null
}
```

Example continuation:

```json
{
  "message": "Explain the second risk",
  "thread_id": "thread_6ec79de378b34b96b19f8ad307ec7337"
}
```

Every unified prebuilt run persists its user and assistant messages in the
shared `messages` collection, so one-shot/file/job agents can still be listed,
selected, and displayed as application history. Compliance and Legal also
bind a private `provider_thread_id`, allowing the external Azure agent to
continue its native conversational context. For one-shot agents, selecting an
existing thread groups new results into the same application history; it does
not imply provider-native conversational memory.
