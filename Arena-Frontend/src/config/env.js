// ─── Runtime Configuration ─────────────────────────────
// Single source of truth for the backend base URL and localStorage keys.
// Every service module imports from here — do not read import.meta.env elsewhere.
//
// API_BASE resolution:
//   • VITE_BACKEND_URL  — preferred
//   • VITE_API_BASE     — accepted alias
//   • fallback          — local FastAPI dev server (bare origin, no /api)
//
// Path convention (VERIFIED against Agent-Integration source — supersedes the
// docs, which are aspirational and wrong for this deployment):
//   Service modules use paths that INCLUDE the `/api` prefix
//   (e.g. `/api/auth/login`, `/api/agents/preview`, `/api/chats`). Every FastAPI
//   router is mounted under `/api/...` and the prefix is NOT stripped. A
//   PathFixerMiddleware only COLLAPSES an accidental `/api/api` back to `/api`.
//   Therefore API_BASE should be the backend ORIGIN (e.g. https://host); if a
//   deployment sets it to `.../api`, the resulting `/api/api` is de-duplicated by
//   the backend and still resolves. There is NO `/arena` segment anywhere.
export const API_BASE = (
  import.meta.env.VITE_BACKEND_URL ||
  import.meta.env.VITE_API_BASE_URL ||
  import.meta.env.VITE_API_BASE ||
  'https://agent-combine-dua2acajdkg8f6am.eastus-01.azurewebsites.net'
).replace(/\/+$/, '');

// localStorage keys (Meridian-namespaced). Shared by the http + auth layers and
// by AuthContext (meridian_user). Centralized so a rename touches one place.
export const STORAGE_KEYS = {
  accessToken: 'meridian_access_token',
  refreshToken: 'meridian_refresh_token',
  user: 'meridian_user',
};
