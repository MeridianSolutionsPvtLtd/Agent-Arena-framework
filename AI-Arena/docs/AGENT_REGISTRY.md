# Agent Registry

The Agent Registry allows authenticated users to publish text-based Azure AI Foundry
agents without adding an agent-specific FastAPI router or service. Registered
agents share the stable `POST /api/agents/{agent_id}/run` contract.

## Lifecycle

1. An authenticated user creates a draft registration.
2. The backend validates that the provider endpoint resolves only to public
   addresses and verifies the agent through Azure `DefaultAzureCredential`.
3. A successful test records a fingerprint of the tested configuration.
4. Activation is rejected when the configuration has not been verified or has
   changed since verification.
5. Active registrations appear in `GET /api/agents`.
6. The unified runner privately maps platform threads to Foundry threads and
   persists messages and run audits using the existing stores.

## Administration API

```text
POST   /api/agent-registry
GET    /api/agent-registry
GET    /api/agent-registry/{agent_id}
PATCH  /api/agent-registry/{agent_id}
POST   /api/agent-registry/{agent_id}/test
POST   /api/agent-registry/{agent_id}/activate
POST   /api/agent-registry/{agent_id}/deactivate
DELETE /api/agent-registry/{agent_id}
```

Every endpoint requires a valid user access token. Users can list, inspect,
test, update, activate, deactivate, or delete only registrations they created.
Active registrations remain public through the normal `GET /api/agents`
catalog endpoint.

## Registration example

```json
{
  "agent_id": "customer-support",
  "name": "Customer Support",
  "description": "Answers customer support questions",
  "provider": "azure_ai_foundry",
  "supports_files": false,
  "tags": ["support"],
  "provider_config": {
    "endpoint": "https://example.services.ai.azure.com/api/projects/project-name",
    "provider_agent_id": "asst_abc123"
  }
}
```

`agent_kind`, `runtime_type`, visibility, authentication mode, ownership, and
status are server-owned. New registrations are drafts and cannot be activated
until their current provider configuration passes a connection test.

## Security and fallbacks

- Provider configuration is never returned by the public catalog API.
- Provider URLs must use HTTPS and may not resolve to loopback, private,
  link-local, reserved, or metadata-network addresses.
- Production deployments can restrict registrations to approved provider
  domains with `AGENT_REGISTRY_ALLOWED_HOST_SUFFIXES`.
- Foundry calls use the platform's `DefaultAzureCredential`; no provider secret
  travels through the user-facing execution API.
- Provider timeouts return a sanitized `504`; provider failures and malformed
  responses return a sanitized `502`.
- Updating provider configuration resets the registration to draft and requires
  a fresh connection test.
- Existing code-owned agents retain `runtime_type=local_service` and their
  specialized execution paths. This is the backward-compatible fallback for
  audio, file, SQL, and other workflows not represented by the text adapter.

Implementation owner: Rajadurai Rajendran
