# Data Model

The project uses MongoDB through Motor with one database.

Database:

```text
agent-platform-hq
```

Environment:

```text
MONGO_URI
MONGO_DB_NAME
```

Legacy Arena env names are still supported for imported code compatibility:

```text
MONGODB_URI
MONGODB_NAME
```

## Database Structure

```text
MongoDB
└── agent-platform-hq
    │
    ├── users
    │
    ├── agents
    ├── threads
    ├── messages
    ├── memory_vectors
    ├── memory_summaries
    ├── token_usage
    │
    ├── arena_chats
    ├── arena_credentials
    ├── arena_files
    ├── arena_agent_runs
    ├── arena_service_runs
    ├── arena_usage_events
    ├── arena_agent_definitions
    ├── arena_db_mappings
    ├── arena_data_tables
    └── arena_data_rows
```

`users` is shared by both systems. Main Agentic AI records and Arena records reference the same user by `user_id`.

## Collection Groups

Shared identity:

```text
users
```

Dynamic agent system:

```text
agents
threads
messages
memory_summaries
memory_vectors
token_usage
```

Arena feature system:

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

## `users`

Current main auth collection.

```json
{
  "_id": "ObjectId",
  "username": "string",
  "email": "optional string",
  "name": "optional string",
  "password": "bcrypt hash",
  "role": "user",
  "created_at": "datetime optional",
  "updated_at": "datetime optional",
  "storage_used_bytes": 0,
  "storage_limit_bytes": 524288000,
  "total_tokens": 0
}
```

Current JWT subject is `username`.

## `agents`

Dynamic agent blueprint collection.

```json
{
  "_id": "ObjectId",
  "agent_id": "agent_1a2b3c4d",
  "user_id": "username",
  "name": "Agent name",
  "domain": "business domain",
  "tools": ["web_search", "extract_data_from_file"],
  "crew_roles": [
    {
      "role": "Analyst",
      "goal": "Analyze uploaded documents",
      "backstory": "Specialist persona",
      "assigned_tools": ["extract_data_from_file"],
      "communication_protocol": null
    }
  ],
  "system_prompt": "orchestrator instruction",
  "validator_config": {
    "checklist": [],
    "min_score": 0.5
  },
  "executor_policy": {
    "email_strategy": "auto",
    "allow_hallucinations": false,
    "strict_spec_compliance": true,
    "final_report_style": "professional_markdown",
    "max_steps": 8
  },
  "user_intent": "original agent creation request",
  "config_updated_at": "datetime optional"
}
```

Do not store fixed Arena agents here.

## `threads`

Dynamic agent conversation thread metadata.

```json
{
  "_id": "ObjectId",
  "thread_id": "thread_xxxx",
  "user_id": "username",
  "agent_id": "agent_xxxx",
  "created_at": "datetime",
  "updated_at": "datetime",
  "last_message_at": "datetime",
  "turn_count": 0,
  "token_totals": {
    "query_tokens": 0,
    "context_tokens": 0,
    "response_tokens": 0,
    "total_tokens": 0,
    "request_count": 0
  }
}
```

## `messages`

Dynamic agent user/assistant messages.

```json
{
  "_id": "ObjectId",
  "thread_id": "thread_xxxx",
  "user_id": "username",
  "agent_id": "agent_xxxx",
  "role": "user | assistant",
  "text": "message text",
  "pair_id": "pair_xxxx",
  "token_estimate": 100,
  "trace_id": "trace_xxxx",
  "metadata": {
    "source_user_message_id": "optional",
    "pii_map": {},
    "blackboard": {},
    "sub_agent_histories": {},
    "structured_plan": [],
    "collaboration": {}
  },
  "created_at": "datetime"
}
```

## `memory_summaries`

Rolling summaries for long conversations.

```json
{
  "_id": "ObjectId",
  "thread_id": "thread_xxxx",
  "user_id": "username",
  "agent_id": "agent_xxxx",
  "version": 1,
  "summary_text": "summary",
  "facts": [],
  "preferences": [],
  "constraints": [],
  "open_tasks": [],
  "updated_at": "datetime"
}
```

## `memory_vectors`

Mongo fallback for semantic memory.

```json
{
  "_id": "ObjectId",
  "thread_id": "thread_xxxx",
  "user_id": "username",
  "agent_id": "agent_xxxx",
  "source_type": "message | summary",
  "source_id": "source id",
  "text_chunk": "memory chunk",
  "embedding": [0.1, 0.2],
  "importance_score": 0.75,
  "metadata": {},
  "created_at": "datetime",
  "updated_at": "datetime"
}
```

Chroma is also used when available.

## `token_usage`

Per-run token tracking.

```json
{
  "_id": "ObjectId",
  "thread_id": "thread_xxxx",
  "user_id": "username",
  "agent_id": "agent_xxxx",
  "pair_id": "pair_xxxx",
  "query_tokens": 10,
  "context_tokens": 100,
  "context_breakdown": {},
  "response_tokens": 80,
  "total_tokens": 190,
  "created_at": "datetime"
}
```

## `arena_chats`

Chat sessions for Arena feature UI.

```json
{
  "_id": "ObjectId",
  "user_id": "main auth user id",
  "title": "Chat title",
  "feature": "arena",
  "service": "openai | search | vision | document | legal",
  "agent_key": "optional fixed agent key",
  "messages": [
    {
      "role": "user | assistant | system",
      "content": "message content",
      "images": [],
      "files": [],
      "metadata": {},
      "created_at": "datetime"
    }
  ],
  "metadata": {},
  "created_at": "datetime",
  "updated_at": "datetime"
}
```

## `arena_credentials`

Encrypted per-user service credentials.

```json
{
  "_id": "ObjectId",
  "user_id": "main auth user id",
  "service": "openai | search | vision | speech",
  "key_name": "AZURE_OPENAI_API_KEY",
  "encrypted_value": "fernet encrypted value",
  "created_at": "datetime",
  "updated_at": "datetime"
}
```

Unique logical key:

```text
user_id + key_name
```

## `arena_files`

File metadata for Arena workflows.

```json
{
  "_id": "ObjectId",
  "user_id": "main auth user id",
  "chat_id": "optional arena_chats id",
  "service": "document | vision | speech | search | legal",
  "filename": "file.pdf",
  "content_type": "application/pdf",
  "size_bytes": 12345,
  "storage_provider": "local | azure_blob | mongodb",
  "storage_path": "path or blob key",
  "public_url": "optional",
  "metadata": {},
  "created_at": "datetime"
}
```

## `arena_usage_events`

Append-only usage events.

```json
{
  "_id": "ObjectId",
  "user_id": "main auth user id",
  "feature": "arena",
  "service": "openai | vision | document | speech",
  "agent_key": "optional fixed agent key",
  "operation": "service_call | agent_call | upload | analyze",
  "status": "success | error",
  "tokens": {
    "prompt": 0,
    "completion": 0,
    "total": 0
  },
  "storage_bytes_delta": 0,
  "latency_ms": 0,
  "error": null,
  "metadata": {},
  "created_at": "datetime"
}
```

## `arena_service_runs`

Direct service call records.

```json
{
  "_id": "ObjectId",
  "user_id": "main auth user id",
  "chat_id": "optional",
  "service": "vision | document | speech | search | language | translator | content_safety | image",
  "operation": "analyze | query | generate | translate | transcribe",
  "input": {},
  "output": {},
  "status": "success | error",
  "error": null,
  "created_at": "datetime"
}
```

## `arena_agent_runs`

Fixed Arena agent execution records.

```json
{
  "_id": "ObjectId",
  "user_id": "main auth user id",
  "chat_id": "optional",
  "agent_key": "call_audit | recruitment | legal | compliance | data_insights | invoice_finance",
  "input": {},
  "output": {},
  "status": "success | error",
  "error": null,
  "created_at": "datetime"
}
```

## `arena_agent_definitions`

Optional fixed-agent metadata.

```json
{
  "_id": "ObjectId",
  "agent_key": "recruitment",
  "name": "Recruitment Agent",
  "type": "fixed_arena_agent",
  "route_prefix": "/api/arena/recruitment",
  "description": "JD generation and resume analysis",
  "enabled": true,
  "required_credentials": [],
  "created_at": "datetime",
  "updated_at": "datetime"
}
```

## `arena_db_mappings`

Compatibility mapping for future MongoDB-only table features.

```json
{
  "_id": "ObjectId",
  "user_id": "main auth user id",
  "db_name": "logical database name",
  "table_name": "table name",
  "type": "mongodb_table",
  "file_id": "optional",
  "created_at": "datetime",
  "updated_at": "datetime"
}
```

## `arena_data_tables`

MongoDB-only table metadata.

```json
{
  "_id": "ObjectId",
  "user_id": "main auth user id",
  "file_id": "optional arena_files id",
  "table_name": "sales_data",
  "columns": [
    {
      "name": "amount",
      "type": "number"
    }
  ],
  "row_count": 0,
  "metadata": {},
  "created_at": "datetime",
  "updated_at": "datetime"
}
```

## `arena_data_rows`

MongoDB-only table rows.

```json
{
  "_id": "ObjectId",
  "user_id": "main auth user id",
  "table_id": "arena_data_tables id",
  "row_index": 0,
  "data": {
    "amount": 100
  },
  "created_at": "datetime"
}
```

## Data Ownership Rule

Arena routes must only write to:

```text
arena_*
```

Dynamic-agent routes must own:

```text
agents
threads
messages
memory_summaries
memory_vectors
token_usage
```
