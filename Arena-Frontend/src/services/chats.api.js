// ─── Chats API ─────────────────────────────────────────
// Multimodal persona conversations, stored server-side and SEPARATE from
// dynamic-agent threads/messages (see agents.api.js). Routes VERIFIED against
// Agent-Integration/routers/chat.py — router prefix `/api/chats`:
//   POST /api/chats                     create
//   GET  /api/chats                     list
//   GET  /api/chats/{id}                fetch one (with messages)
//   PUT  /api/chats/{id}                update (messages, title, agent, …)
//   DELETE /api/chats/{id}              delete
//   POST /api/chats/{id}/upload         attach a file (multipart)
//   POST /api/chats/generate-title      non-streaming title
//   POST /api/chats/generate-title-stream   SSE title (URL builder below)
// (There is NO `/arena` segment — the docs were wrong.)
import { API_BASE } from '../config/env';
import { apiFetch, parseApiErrorDetail } from './http';

async function asJson(res, fallback) {
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    const error = new Error(parseApiErrorDetail(err) || fallback);
    // Keep the HTTP status on the error so callers can branch on it. The rail
    // needs to tell "this chat is gone" (404 → drop it from the local index)
    // apart from "the backend is unreachable" (network/5xx → keep it and retry).
    error.status = res.status;
    throw error;
  }
  return res.json();
}

/** GET /api/chats — list the current user's chats. */
export async function listArenaChats() {
  return asJson(await apiFetch('/api/chats'), 'Failed to load chats');
}

/** GET /api/chats/{id} — fetch one chat with its messages. */
export async function getArenaChat(chatId) {
  return asJson(await apiFetch(`/api/chats/${encodeURIComponent(chatId)}`), 'Failed to load chat');
}

/** POST /api/chats — create a new chat. */
export async function createArenaChat(payload = {}) {
  return asJson(
    await apiFetch('/api/chats', { method: 'POST', body: JSON.stringify(payload) }),
    'Failed to create chat'
  );
}

/** PUT /api/chats/{id} — update a chat (messages, title, agent, …). */
export async function updateArenaChat(chatId, payload) {
  return asJson(
    await apiFetch(`/api/chats/${encodeURIComponent(chatId)}`, {
      method: 'PUT',
      body: JSON.stringify(payload),
    }),
    'Failed to update chat'
  );
}

/** DELETE /api/chats/{id} — delete a chat. */
export async function deleteArenaChat(chatId) {
  return asJson(
    await apiFetch(`/api/chats/${encodeURIComponent(chatId)}`, { method: 'DELETE' }),
    'Failed to delete chat'
  );
}

/** POST /api/chats/{id}/upload — attach a file to a chat (multipart). */
export async function uploadToArenaChat(chatId, file) {
  const formData = new FormData();
  formData.append('file', file);
  // apiFetch injects Authorization; pass empty headers so it does NOT force
  // Content-Type: application/json (the browser sets the multipart boundary).
  const res = await apiFetch(`/api/chats/${encodeURIComponent(chatId)}/upload`, {
    method: 'POST',
    headers: {},
    body: formData,
  });
  return asJson(res, 'Failed to upload file to chat');
}

/** POST /api/chats/generate-title — non-streaming title generation. */
export async function generateChatTitle(payload) {
  return asJson(
    await apiFetch('/api/chats/generate-title', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
    'Failed to generate title'
  );
}

/**
 * Absolute URL for POST /api/chats/generate-title-stream (SSE).
 * The chat layer streams this with fetch()+Bearer and reads the response body;
 * a bare URL keeps that transport concern in one place.
 */
export function arenaChatTitleStreamUrl() {
  return `${API_BASE}/api/chats/generate-title-stream`;
}
