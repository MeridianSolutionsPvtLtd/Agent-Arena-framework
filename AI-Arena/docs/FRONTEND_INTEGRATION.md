# Frontend Integration Notes

## Auth

Use main backend login:

```text
POST /login
```

Store the `access_token`.

Send it for protected requests:

```http
Authorization: Bearer <access_token>
```

This token works for both:

```text
/api/agents/*
/api/arena/*
```

There is only one login system. Arena APIs reuse the main backend JWT auth directly through `core/security/auth.py`, so the frontend should not build a separate Arena login flow.

## Route Prefixes

Frontend should call through gateway-style paths:

```text
/api/...
```

Dynamic agent routes:

```text
/api/agents/...
```

Arena feature routes:

```text
/api/arena/...
```

The backend internally strips `/api`.

## Main Frontend Areas

Suggested navigation groups:

```text
Agents
Arena Services
Arena Chats
Credentials
Usage
```

## Agents UI

Useful APIs:

```text
POST /api/agents/preview
POST /api/agents/create
GET  /api/agents/me
POST /api/agents/{agent_id}/run
GET  /api/agents/{agent_id}/context
GET  /api/agents/{agent_id}/blackboard
GET  /api/agents/{agent_id}/sub_agent_histories
GET  /api/agents/{agent_id}/config
PATCH /api/agents/{agent_id}/config
```

Run response can include:

```json
{
  "response": "final answer",
  "trace_id": "trace_xxxx",
  "thread_id": "thread_xxxx",
  "collaboration": {},
  "token_usage": {},
  "hitl_pending": true,
  "flight_plan_steps": []
}
```

If `hitl_pending` is true, show approval UI.

## Trace UI

Connect WebSocket:

```text
/api/ws/trace/{trace_id}
```

Show live execution state from events.

## Arena Services UI

Use:

```text
/api/arena/openai/chat
/api/arena/search/query
/api/arena/vision/analyze
/api/arena/document/analyze
/api/arena/language/analyze
/api/arena/speech/tts
/api/arena/speech/stt
/api/arena/translator/translate
/api/arena/content_safety/analyze
/api/arena/image/generate
```

Most service routes require Azure credentials. If credentials are absent, service code falls back to environment values.

## Credentials UI

Use:

```text
GET    /api/arena/credentials/schema
POST   /api/arena/credentials
GET    /api/arena/credentials
DELETE /api/arena/credentials/{key_name}
```

Never show secret values after save. The API lists names only.

Credential keys are environment-style names:

```text
AZURE_OPENAI_ENDPOINT
AZURE_OPENAI_API_KEY
AZURE_OPENAI_DEPLOYMENT_NAME
AZURE_SEARCH_ENDPOINT
AZURE_SEARCH_API_KEY
AZURE_VISION_ENDPOINT
AZURE_VISION_API_KEY
AZURE_DOCUMENT_ENDPOINT
AZURE_DOCUMENT_API_KEY
AZURE_LANGUAGE_ENDPOINT
AZURE_LANGUAGE_API_KEY
AZURE_SPEECH_KEY
AZURE_SPEECH_REGION
AZURE_TRANSLATOR_KEY
AZURE_TRANSLATOR_REGION
AZURE_TRANSLATOR_ENDPOINT
AZURE_CONTENT_SAFETY_ENDPOINT
AZURE_CONTENT_SAFETY_API_KEY
```

## Arena Chats UI

Use:

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

Arena chats are separate from dynamic-agent `threads/messages`.

## Fixed Arena Agents UI

Mounted fixed agents:

```text
/api/arena/call-audit/analyze
/api/arena/recruitment/generate-jd
/api/arena/recruitment/analyze/single
/api/arena/recruitment/analyze/batch
/api/arena/gd/analyze
/api/arena/compliance/analyze/text
/api/arena/compliance/analyze/document
/api/arena/data-insights/analyze/text
/api/arena/data-insights/analyze/file
/api/arena/invoice-finance/analyze
/api/arena/legal/chat
/api/arena/legal/analyze
/api/arena/legal/draft
```

## Not Available Yet

Do not build UI for:

```text
/api/arena/sql-agent/*
```

Reason: the old route used DuckDB. The project is moving MongoDB-only.
