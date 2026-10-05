# Meridian AI Arena Backend

Unified FastAPI backend for Meridian AI services, prebuilt Arena agents, and
user-created Agentic AI workflows.

## Architecture

Arena is the application shell and owns FastAPI, authentication, MongoDB,
encrypted credentials, chats, storage, and usage tracking. The migrated
`core/` package supplies custom-agent blueprint generation, LangGraph
orchestration, tools, memory, guardrails, and audit behavior.

Prebuilt and custom definitions share one MongoDB `agents` collection and one
authenticated API surface under `/api/agents`.

## Local setup

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
Copy-Item .env.example .env
```

Set at minimum:

- `MONGODB_URI`
- `MONGODB_NAME`
- independent `JWT_SECRET` and `JWT_REFRESH_SECRET` values of 32+ characters
- Azure/OpenAI settings required by the agents being used

Start:

```powershell
uvicorn main:app --reload --port 5000
```

Verify:

```powershell
python -m pytest
```

## Documentation

- [Migration and database design](docs/AGENT_MIGRATION.md)
- [Complete agent workflow](docs/AGENT_WORKFLOW.md)
- [Code-flow validation](docs/CODE_FLOW_VALIDATION.md)
- [Production deployment](docs/DEPLOYMENT.md)

Interactive API documentation is available at `/docs` after startup.

## Secure defaults

- No fallback JWT secrets or hard-coded bootstrap credentials
- Private custom agents with server-controlled ownership
- Raw prompts excluded from `agent_runs`
- User-scoped file paths and randomized blob names
- Private/local network scrape targets blocked
- Arbitrary Python and broad automated web collection disabled by default
- Container runs as a non-root user

Do not enable `ENABLE_UNSAFE_PYTHON_TOOL` unless execution occurs inside a
dedicated operating-system sandbox with no application secrets, host mounts,
or unrestricted network access.
