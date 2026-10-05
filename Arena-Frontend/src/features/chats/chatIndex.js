// Browser-local, per-user record of WHICH conversations exist, plus which ones
// the user pinned.
//
// Why this exists: on this deployment `GET /api/chats` cannot enumerate history.
// It sorts on `updated_at` (Agent-Integration/routers/chat.py list_chats) and the
// CosmosDB `chats` collection indexes only `_id`, so Cosmos rejects the query and
// the endpoint 500s. The single-chat route `GET /api/chats/{id}` has no sort and
// works fine — so we remember the ids here and rehydrate each conversation from
// the real database. Message content is therefore always server-truth; this file
// only remembers what to ask for. Once the backend adds the `updated_at` index,
// loadChats() prefers the server list again and this quietly becomes a warm
// cache — no code change needed.
//
// Pins have no server home at all: `UpdateChatRequest` accepts only
// { message, title } (Agent-Integration/models/chat.py), so a pin flag cannot be
// persisted backend-side without a backend change. Pins are per-browser by
// necessity, not by preference.

const INDEX_PREFIX = 'meridian_chat_index';
const PIN_PREFIX = 'meridian_chat_pins';

// The rail is a recency list, not an archive — keep the cache bounded.
export const MAX_INDEXED = 200;

const keyFor = (prefix, userId) => `${prefix}_${userId || 'anon'}`;

function readArray(key) {
  try {
    const parsed = JSON.parse(localStorage.getItem(key) || '[]');
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return []; // corrupt or unavailable storage must never break the rail
  }
}

function writeArray(key, value) {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch {
    /* quota exceeded / private mode — the rail still works from server state */
  }
}

function timeOf(item) {
  const t = new Date(item?.updated_at || item?.created_at || 0).getTime();
  return Number.isNaN(t) ? 0 : t;
}

/** Newest first — the ordering the backend's rejected sort was meant to give us. */
export function sortByRecency(items) {
  return [...items].sort((a, b) => timeOf(b) - timeOf(a));
}

/** Normalize to a rail list item, dropping message bodies (keeps storage small). */
export function toListItem(chat, fallbackId) {
  return {
    id: chat?.id || fallbackId,
    title: chat?.title || 'New Chat',
    agent_id: chat?.agent_id ?? null,
    created_at: chat?.created_at || '',
    updated_at: chat?.updated_at || chat?.created_at || '',
    message_count: Array.isArray(chat?.messages) ? chat.messages.length : chat?.message_count ?? 0,
  };
}

/** Cached list items for a user, newest first. */
export function readChatIndex(userId) {
  return sortByRecency(readArray(keyFor(INDEX_PREFIX, userId)).filter((c) => c && c.id));
}

/** Replace the cached list (normalized, ordered, trimmed). */
export function writeChatIndex(userId, items) {
  if (!userId) return;
  const trimmed = sortByRecency(items)
    .filter((c) => c && c.id)
    .slice(0, MAX_INDEXED)
    .map((c) => toListItem(c));
  writeArray(keyFor(INDEX_PREFIX, userId), trimmed);
}

/** Pinned chat ids for a user, most recently pinned first. */
export function readPinnedIds(userId) {
  return readArray(keyFor(PIN_PREFIX, userId)).filter((id) => typeof id === 'string');
}

export function writePinnedIds(userId, ids) {
  if (!userId) return;
  writeArray(keyFor(PIN_PREFIX, userId), [...new Set(ids)]);
}
