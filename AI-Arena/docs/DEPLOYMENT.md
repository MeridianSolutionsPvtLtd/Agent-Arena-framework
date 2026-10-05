# Production Deployment

## Prerequisites

- MongoDB/Cosmos Mongo API reachable from the workload
- Azure service credentials for enabled prebuilt and custom capabilities
- Blob Storage for user uploads
- Python dependencies from `requirements.txt`
- FFmpeg for audio/video tools (included in the Docker image)

## Required security configuration

Generate independent random values of at least 32 characters:

```text
JWT_SECRET
JWT_REFRESH_SECRET
```

Set explicit production origins:

```text
CORS_ORIGINS=https://arena.example.com
```

Configure `CREDENTIAL_ENCRYPTION_KEY` before allowing users to store service
credentials. Store all secrets in the deployment secret manager, not in image
layers, source control, or Kubernetes ConfigMaps.

Bootstrap seeding is off by default. If it is needed for a new environment,
enable it for the initial deployment only:

```text
SEED_DEFAULT_USER=true
DEFAULT_USER_NAME=...
DEFAULT_USER_EMAIL=...
DEFAULT_USER_PASSWORD=<12+ characters>
```

Disable it immediately after provisioning.

## Feature gates

Production defaults:

```text
ENABLE_UNSAFE_PYTHON_TOOL=false
ENABLE_ADVANCED_WEB_TOOL=false
```

The Python tool must run only in a separate hardened execution service or
container sandbox with resource limits, no secrets, read-only root filesystem,
no host mounts, and restricted egress.

The advanced web/data collector requires restricted outbound network policy
and isolated third-party credentials. Standard `web_search` remains available
and applies public-address checks.

## Database behavior

Use the existing Arena settings:

```text
MONGODB_URI
MONGODB_NAME
MONGODB_COLLECTION_NAME=users
```

No destructive migration is run. Startup:

1. Binds the Agentic persistence facade to Arena's existing Motor database.
2. Creates required indexes.
3. Idempotently upserts prebuilt metadata into `agents`.

New/used collections include:

- `agents`
- `agent_runs`
- `threads`
- `messages`
- `memory_summaries`
- `memory_vectors`
- `token_usage`

Back up the database before the first deployment and test index creation in a
staging database with the same Mongo/Cosmos configuration.

## Docker

Build:

```powershell
docker build -t meridian-ai-arena-backend:latest .
```

The image:

- installs FFmpeg and runtime libraries;
- copies Arena and Agentic runtime code;
- creates writable upload/output/memory directories;
- runs as the non-root `meridian` user;
- exposes port `5000`;
- includes an `/api/health` health check.

Run with secrets injected by the platform:

```powershell
docker run --rm -p 5000:5000 --env-file .env meridian-ai-arena-backend:latest
```

Do not bake `.env` into the image.

## Rollout

1. Back up MongoDB.
2. Deploy one staging instance with production-equivalent services.
3. Run the test suite.
4. Verify startup logs show one Mongo connection and tool registration.
5. Authenticate and call `GET /api/agents`.
6. Create and run a no-tool custom agent.
7. Preview/save/run a multi-agent blueprint.
8. Upload a small allowed file to a file-capable custom agent.
9. Verify a second user receives `404` for the first user's custom agent.
10. Verify `agent_runs`, chats, tokens, and user counters update.
11. Verify existing direct prebuilt endpoints still work.
12. Roll out remaining instances and monitor errors, latency, token usage, and
    storage growth.

## Smoke tests

Unauthenticated health:

```http
GET /api/health
```

Authenticated catalog:

```http
GET /api/agents
Authorization: Bearer <access-token>
```

Custom run:

```http
POST /api/agents/{agent-id}/run
Authorization: Bearer <access-token>
Content-Type: application/json

{"message":"Summarize the migration architecture.","payload":{}}
```

## Operational notes

- Audio execution needs FFmpeg; the Docker image includes it, but local Windows
  development must install it separately.
- Chroma persists under `CHROMA_PERSIST_DIR`; production storage should use an
  appropriate persistent volume if semantic memory must survive replacement.
- Pending HITL file runs retain their local authorized execution copy. Configure
  lifecycle cleanup for abandoned upload directories according to retention
  requirements.
- Blob uploads use randomized names and roll back when database quota accounting
  fails.
- Never expose `uploads`, `.chroma`, or raw `outputs` as public static folders.
