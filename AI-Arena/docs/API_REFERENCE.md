# API Reference

This document lists route groups for frontend integration.

## Base URL

Local default:

```text
http://localhost:8000
```

When using the gateway, frontend generally calls:

```text
/api/...
```

The backend strips a leading `/api` through `ApiPrefixMiddleware`.

## Auth

### `POST /signup`

Create a main backend user.

Request:

```json
{
  "username": "user1",
  "password": "secret"
}
```

### `POST /login`

OAuth2 password login. Send as form data:

```text
username=user1
password=secret
```

Response:

```json
{
  "access_token": "...",
  "refresh_token": "...",
  "token_type": "bearer"
}
```

### `POST /auth/refresh`

Request:

```json
{
  "refresh_token": "..."
}
```

## Dynamic Agent APIs

### `POST /agents/preview`

Generates an agent blueprint but does not save it.

Auth required.

Request:

```json
{
  "query": "Create an agent that compares vendor quotations",
  "name": "Quotation Agent"
}
```

### `POST /agents/create`

Creates/saves an agent.

Auth required.

Request can include `query`, `name`, or a reviewed `blueprint`.

### `GET /agents/me`

Lists current user's agents.

### `PATCH /agents/{agent_id}/name`

Rename an agent.

Request:

```json
{
  "name": "New Name"
}
```

### `GET /agents/{agent_id}/config`

Returns editable agent config fields:

- `crew_roles`
- `executor_policy`
- `validator_config`
- `system_prompt`

### `PATCH /agents/{agent_id}/config`

Updates agent config fields.

### `POST /agents/{agent_id}/run`

Runs the agent.

Request:

```json
{
  "query": "Analyze this file and summarize findings",
  "conversation_history": "",
  "trace_id": "optional",
  "thread_id": "optional"
}
```

Response includes:

- `response`
- `trace_id`
- `thread_id`
- `collaboration`
- `token_usage`
- optional `hitl_pending`
- optional `flight_plan_steps`

### `GET /agents/{agent_id}/context`

Returns latest UI-ready messages and token total.

### `GET /agents/{agent_id}/blackboard`

Returns latest persisted blackboard.

### `GET /agents/{agent_id}/sub_agent_histories`

Returns latest per-role sub-agent histories.

### `DELETE /agents/{agent_id}/history`

Clears conversation history, memory summaries, vector memory, and token usage for the agent.

### `DELETE /agents/{agent_id}`

Deletes the agent blueprint.

## Upload

### `POST /upload`

Uploads a file for dynamic-agent workflows.

Form field:

```text
file
```

Response:

```json
{
  "file_path": "server path",
  "filename": "original.pdf"
}
```

## Trace WebSocket

```text
WS /ws/trace/{trace_id}
WS /api/ws/trace/{trace_id}
```

Used to stream agent execution events.

## Export

### `GET /agents/{agent_id}/export/blueprint`

Downloads agent blueprint JSON.

### `GET /agents/{agent_id}/export?format=zip`

Downloads portable ZIP package.

### `GET /agents/{agent_id}/export?format=exe`

Builds a desktop client and returns a temporary download token.

## Arena APIs

Arena routes are mounted internally at:

```text
/arena/*
```

Frontend through gateway should call:

```text
/api/arena/*
```

Main auth token is required for mounted Arena routes unless route code explicitly does not require it.

### Arena Chat

```text
POST   /api/arena/chats
GET    /api/arena/chats
GET    /api/arena/chats/{chat_id}
PUT    /api/arena/chats/{chat_id}
POST   /api/arena/chats/{chat_id}/upload
DELETE /api/arena/chats/{chat_id}
POST   /api/arena/chats/generate-title
POST   /api/arena/chats/generate-title-stream
```

Data is stored in `arena_chats`.

### Arena Credentials

```text
GET    /api/arena/credentials/schema
POST   /api/arena/credentials
GET    /api/arena/credentials
DELETE /api/arena/credentials/{key_name}
```

Credentials are encrypted and stored in `arena_credentials`.

### Azure/OpenAI Services

```text
POST /api/arena/openai/chat
POST /api/arena/search/query
POST /api/arena/search/upload
GET  /api/arena/search/documents
DELETE /api/arena/search/documents/{doc_id}
POST /api/arena/vision/analyze
POST /api/arena/document/analyze
POST /api/arena/language/analyze
POST /api/arena/language/key_phrases
POST /api/arena/language/entities
POST /api/arena/language/pii
POST /api/arena/language/detect_language
POST /api/arena/language/summarize
POST /api/arena/speech/tts
POST /api/arena/speech/stt
POST /api/arena/translator/translate
POST /api/arena/content_safety/analyze
POST /api/arena/image/generate
POST /api/arena/video/upload
GET  /api/arena/video/health
```

### Fixed Arena Agents

```text
POST /api/arena/call-audit/analyze
POST /api/arena/recruitment/generate-jd
POST /api/arena/recruitment/analyze/single
POST /api/arena/recruitment/analyze/batch
POST /api/arena/gd/analyze
POST /api/arena/compliance/analyze/text
POST /api/arena/compliance/analyze/document
GET  /api/arena/compliance/thread/{thread_id}/messages
POST /api/arena/data-insights/analyze/text
POST /api/arena/data-insights/analyze/file
POST /api/arena/invoice-finance/analyze
POST /api/arena/legal/chat
POST /api/arena/legal/analyze
POST /api/arena/legal/draft
GET  /api/arena/legal/history/{thread_id}
POST /api/arena/legal/download-pdf
```

## Intentionally Not Mounted

Copied Arena auth routes:

```text
/api/auth/*
```

Reason: main backend auth is canonical.

Copied SQL/DuckDB routes:

```text
/api/sql-agent/*
```

Reason: project is moving MongoDB-only. Use planned `arena_data_tables` and `arena_data_rows` instead.
