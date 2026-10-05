# Unified Agent Migration

## Purpose

`meridianaiarena-backend` is the main backend. Agentic AI capabilities are
migrated into this repository while preserving the Arena API style, MongoDB
connection, authentication, credential encryption, chat storage, metrics, and
existing prebuilt-agent endpoints.

This is an additive migration. Existing endpoints continue to work while the
frontend moves to the unified API.

## Architecture

```text
authenticated request
    -> routers/agents.py
    -> services/agent_service.py
    -> MongoDB agents collection
    -> prebuilt service or custom Agentic AI graph runtime
    -> chats + agent_runs + user usage counters
    -> unified response
```

Arena remains the application shell. The migrated `core/` package is an
isolated runtime library containing the original orchestration, tool, memory,
guardrail, and persistence behavior. Its persistence facade binds to Arena's
existing Motor database; it does not create a second MongoDB client or expose
a second authentication system.

## Collections

### `agents`

Stores both agent kinds. `agent_kind` is the discriminator.

| Field | Purpose |
|---|---|
| `agent_id` | Stable, unique API and runtime identity |
| `agent_kind` | `prebuilt` or `custom` |
| `user_id` | Owner for custom agents; `null` for prebuilt agents |
| `visibility` | `public` for prebuilt, `private` for custom |
| `status` | `active`, `inactive`, or `draft` |
| `config` | Small runtime-specific configuration |

Prebuilt definitions are seeded idempotently at application startup. Code owns
their names, handlers, and capabilities; the database owns their operational
status.

### `agent_runs`

Stores execution status, ownership, agent identity, token usage, timestamps,
and a SHA-256 input hash. Raw prompts and responses are not duplicated into
this audit collection. Conversation content remains in the existing `chats`
collection when a `chat_id` is supplied.

## API

All endpoints require an Arena access token.

### List accessible agents

```http
GET /api/agents
GET /api/agents?agent_kind=custom
```

Returns active public prebuilt agents and custom agents owned by the current
user.

### Create a custom agent

Custom agents are created only through an NLP-generated, user-reviewed
blueprint:

```http
POST /api/agents/preview
POST /api/agents/blueprint
```

The preview is not persisted. The reviewed blueprint is validated again before
the backend assigns ownership, kind, visibility, stable identity, and
timestamps and inserts it into `agents`.

### Read, update, and delete

```http
GET    /api/agents/{agent_id}
PATCH  /api/agents/{agent_id}
DELETE /api/agents/{agent_id}
```

Only the owner can update or delete a custom agent. Prebuilt agents cannot be
modified through these user endpoints.

### Execute

```http
POST /api/agents/{agent_id}/run
Content-Type: application/json

{
  "message": "Review the quarterly results",
  "thread_id": null,
  "chat_id": null,
  "payload": {}
}
```

The server loads the agent and determines its kind. The client never controls
the execution type.

File-capable custom agents use:

```http
POST /api/agents/{agent_id}/run-file
Content-Type: multipart/form-data
```

Advanced runtime endpoints expose owned-agent configuration, context,
blackboard, specialist histories, and history cleanup. See `AGENT_WORKFLOW.md`.

Owner-authenticated blueprint and portable ZIP exports are available at:

```http
GET /api/agents/{agent_id}/export?format=blueprint
GET /api/agents/{agent_id}/export?format=zip
```

Group discussion requires:

```json
{"message": "Transcript...", "payload": {"topic": "Remote work"}}
```

## Security decisions

- Ownership always comes from the verified JWT user document.
- Custom agents are private and cannot be queried by another user.
- Unauthorized and missing agents both return `404` to reduce enumeration.
- Custom prompts and model configuration are returned only to their owner.
- Agent runs do not duplicate raw prompt or response content.
- Unexpected execution errors are logged server-side and returned as a generic
  error to clients.
- Only registered tool names are accepted. Role-level tool assignments must be
  subsets of the blueprint tool allowlist.
- Uploaded paths are restricted to the authenticated user's managed upload
  directory. LLM-produced paths can never override this allowlist.
- The arbitrary Python executor is migrated but disabled by default. It can be
  enabled only with `ENABLE_UNSAFE_PYTHON_TOOL=true` in a dedicated OS/container
  sandbox that has no host secrets or filesystem access.
- Broad AgentQL/data-collector browsing is migrated but disabled by default;
  enabling it requires restricted egress and isolated credentials.
- Side-effect plans use the migrated human-approval workflow.
- Existing encrypted Arena credentials and deployment-level Agentic runtime
  configuration remain available through their established mechanisms.

## Prebuilt compatibility

Text execution is available through the unified endpoint for compliance, data
insights, group discussion, recruitment, legal, and custom agents. Custom-agent
files use the unified `run-file` endpoint. Specialized prebuilt file, audio,
SQL, invoice, and recruitment endpoints remain unchanged so their established
request and response contracts stay backward compatible.

## Deployment

1. Back up the existing MongoDB database.
2. Copy `.env.example` to the deployment secret store and provide independent
   JWT secrets of at least 32 characters. There are no fallback JWT secrets.
3. Deploy this version using the same `MONGODB_URI` and `MONGODB_NAME`.
4. Start one instance first; startup creates indexes and seeds prebuilt agent
   metadata idempotently.
5. Verify `/api/health` and `GET /api/agents` with an authenticated user.
6. Run one existing direct prebuilt endpoint and one unified endpoint.
7. Roll out remaining instances.

No destructive database migration is performed. Existing collections and
endpoints remain available.

The former hard-coded bootstrap account is removed. Optional bootstrap seeding
is disabled by default and requires explicit `DEFAULT_USER_*` values.

## Verification

```powershell
python -m pytest tests/test_agent_service.py
```

Production smoke checks:

1. Existing authentication and chat endpoints respond normally.
2. Prebuilt agents appear once in `GET /api/agents`.
3. A user can create, update, run, and delete only their own custom agent.
4. A second user cannot read or mutate that custom agent.
5. Successful executions create `agent_runs` records and increment usage.
6. A supplied chat ID must belong to the authenticated user.
