// ─── API Service Layer (barrel) ────────────────────────
// Backend: FastAPI + uvicorn. Base URL & path convention: see config/env.js.
//
// This file used to hold every API function. It is now a compatibility barrel:
// the implementation lives in focused modules and is re-exported here so that
// existing `import { ... } from '.../services/api'` call sites keep working.
//
//   config/env.js   — API_BASE + storage keys (single source of truth)
//   http.js         — transport: tokens, apiFetch (+401 refresh), URLs, downloads
//   auth.api.js     — login / signup / logout
//   agents.api.js   — dynamic-agent CRUD, config, run, context, upload, export
//   chats.api.js    — arena chats (multimodal persona conversations)
//   arena.api.js    — arena services (speech, vision, language, …) + credentials
//
// Prefer importing from the specific module in new code; this barrel exists for
// backward compatibility and will be slimmed once call sites migrate (Phase 10).
export * from './http';
export * from './auth.api';
export * from './agents.api';
export * from './chats.api';
export * from './arena.api';
export * from './mcp.api';
