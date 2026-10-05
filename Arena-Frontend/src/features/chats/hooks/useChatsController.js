import { useState, useCallback, useEffect, useRef } from 'react';
import { useAuth } from '../../../context/AuthContext';
import {
  listArenaChats,
  getArenaChat,
  createArenaChat,
  updateArenaChat,
  deleteArenaChat,
} from '../../../services/chats.api';
import {
  readChatIndex,
  writeChatIndex,
  readPinnedIds,
  writePinnedIds,
  sortByRecency,
  toListItem,
} from '../chatIndex';
import { normalizeMessageAttachments } from '../../../utils/attachmentUtils';

// Owns the conversation list + the currently-open chat, and the CRUD that keeps
// them in sync with the backend (/api/chats). This is the persona-chat analogue
// of Arena's ChatContext list logic, rebuilt on Playground's service layer so
// every request flows through apiFetch (correct meridian_* bearer + 401 refresh).
//
// History survives reloads even though `GET /api/chats` is unusable on this
// deployment (Cosmos rejects its unindexed sort): the rail falls back to the
// local id index and re-reads each conversation through the sort-free
// `GET /api/chats/{id}`. See ../chatIndex.js for the full rationale.

// How many cached conversations to revalidate against the database per load.
// Bounded so a long history can't fire hundreds of requests on mount; the rest
// still render from cache and are corrected the moment they're opened, since
// selectChat fetches the real document anyway.
const REVALIDATE_LIMIT = 25;

export function useChatsController() {
  const { isAuthenticated, user } = useAuth();
  const userId = user?.id || null;

  // Seed from the local index so previous conversations are on screen
  // immediately, before any network round-trip resolves.
  const [chats, setChats] = useState(() => readChatIndex(user?.id));
  const [pinnedIds, setPinnedIds] = useState(() => readPinnedIds(user?.id));
  const [activeChatId, setActiveChatId] = useState(null);
  const [activeChat, setActiveChat] = useState(null); // full chat: {id,title,messages:[...]}
  const [isLoadingChats, setIsLoadingChats] = useState(false);
  const [isLoadingActive, setIsLoadingActive] = useState(false);
  const [isLocalHistory, setIsLocalHistory] = useState(false);
  const [error, setError] = useState(null);

  // One effect per store: hydrate once for the resolved user, then persist every
  // later change. The hydrate/persist split matters because `user` can arrive a
  // render late — persisting first would write an empty list over real history.
  const indexHydratedRef = useRef(false);
  useEffect(() => {
    if (!userId) return;
    if (!indexHydratedRef.current) {
      indexHydratedRef.current = true;
      setChats((prev) => (prev.length ? prev : readChatIndex(userId)));
      return;
    }
    writeChatIndex(userId, chats);
  }, [userId, chats]);

  const pinsHydratedRef = useRef(false);
  useEffect(() => {
    if (!userId) return;
    if (!pinsHydratedRef.current) {
      pinsHydratedRef.current = true;
      setPinnedIds(readPinnedIds(userId));
      return;
    }
    writePinnedIds(userId, pinnedIds);
  }, [userId, pinnedIds]);

  // Forget a chat that the server says no longer exists.
  const forgetChat = useCallback((chatId) => {
    setChats((prev) => prev.filter((c) => c.id !== chatId));
    setPinnedIds((prev) => (prev.includes(chatId) ? prev.filter((id) => id !== chatId) : prev));
  }, []);

  // Fallback path: rebuild the rail from the local index, re-reading each chat
  // from the database so titles/timestamps are real rather than remembered.
  const rebuildFromIndex = useCallback(async () => {
    const cached = readChatIndex(userId);
    if (!cached.length) return [];

    const targets = cached.slice(0, REVALIDATE_LIMIT);
    const results = await Promise.allSettled(targets.map((c) => getArenaChat(c.id)));

    const gone = new Set();
    const fresh = new Map();
    results.forEach((r, i) => {
      const id = targets[i].id;
      if (r.status === 'fulfilled' && r.value) {
        fresh.set(id, toListItem(r.value, id));
      } else if (r.reason?.status === 404) {
        // Deleted (here or on another device) — drop it. Any other failure
        // (offline, 5xx, expired token) keeps the cached entry so a temporary
        // outage never destroys the user's history.
        gone.add(id);
      }
    });

    if (gone.size) setPinnedIds((prev) => prev.filter((id) => !gone.has(id)));
    return sortByRecency(cached.filter((c) => !gone.has(c.id)).map((c) => fresh.get(c.id) || c));
  }, [userId]);

  const loadChats = useCallback(async () => {
    setIsLoadingChats(true);
    try {
      let serverList = null;
      try {
        const data = await listArenaChats();
        serverList = Array.isArray(data) ? data : [];
      } catch {
        serverList = null; // endpoint unavailable → fall back to the local index
      }

      if (serverList) {
        setIsLocalHistory(false);
        setChats(sortByRecency(serverList.map((c) => toListItem(c))));
        setError(null);
        return;
      }

      setIsLocalHistory(true);
      setChats(await rebuildFromIndex());
      setError(null);
    } catch (e) {
      setError(e.message || 'Failed to load chats');
    } finally {
      setIsLoadingChats(false);
    }
  }, [rebuildFromIndex]);

  // Load the list once the user is authenticated (route is behind login).
  useEffect(() => {
    if (isAuthenticated) loadChats();
  }, [isAuthenticated, loadChats]);

  const selectChat = useCallback(async (chatId) => {
    if (!chatId) return;
    setActiveChatId(chatId);
    setIsLoadingActive(true);
    try {
      const full = await getArenaChat(chatId);
      const normalizedMessages = (full.messages || []).map((m) => {
        const rawAtts = m.attachments || m.files || m.metadata?.attachments || null;
        const isUser = m.role === 'user';
        const { cleanText, attachments } = isUser
          ? normalizeMessageAttachments(m.content, rawAtts)
          : { cleanText: m.content, attachments: rawAtts };
        return {
          ...m,
          content: cleanText,
          attachments,
        };
      });
      setActiveChat({ ...full, messages: normalizedMessages });
      // Keep the rail row honest about what the database actually holds.
      setChats((prev) =>
        prev.some((c) => c.id === chatId)
          ? prev.map((c) => (c.id === chatId ? toListItem(full, chatId) : c))
          : sortByRecency([toListItem(full, chatId), ...prev])
      );
    } catch (e) {
      // A chat that failed to load is NOT the active chat, so clear the id too.
      // This matters right after a delete: the URL param can still briefly hold
      // the removed id, and leaving activeChatId set would make the next send
      // target a chat that no longer exists (PUT /api/chats/{gone} -> 404, and
      // the message is lost) instead of auto-creating a fresh conversation.
      setError(e.message || 'Failed to open chat');
      setActiveChatId(null);
      setActiveChat(null);
      if (e.status === 404) forgetChat(chatId);
    } finally {
      setIsLoadingActive(false);
    }
  }, [forgetChat]);

  const createChat = useCallback(async () => {
    try {
      const created = await createArenaChat({ title: 'New Chat' });
      setChats((prev) => [toListItem(created), ...prev]);
      setActiveChatId(created.id);
      setActiveChat({ ...created, messages: created.messages || [] });
      return created.id;
    } catch (e) {
      setError(e.message || 'Failed to create chat');
      return null;
    }
  }, []);

  const removeChat = useCallback(async (chatId) => {
    try {
      await deleteArenaChat(chatId);
      forgetChat(chatId);
      setActiveChatId((prev) => {
        if (prev === chatId) {
          setActiveChat(null);
          return null;
        }
        return prev;
      });
    } catch (e) {
      setError(e.message || 'Failed to delete chat');
    }
  }, [forgetChat]);

  const renameChat = useCallback(async (chatId, title) => {
    const clean = (title || '').trim();
    if (!clean) return;
    try {
      await updateArenaChat(chatId, { title: clean });
      setChats((prev) => prev.map((c) => (c.id === chatId ? { ...c, title: clean } : c)));
      setActiveChat((prev) => (prev && prev.id === chatId ? { ...prev, title: clean } : prev));
    } catch (e) {
      setError(e.message || 'Failed to rename chat');
    }
  }, []);

  // Pin / unpin. Local-only by necessity — the backend has no field for it.
  // Most recently pinned goes first.
  const togglePin = useCallback((chatId) => {
    setPinnedIds((prev) =>
      prev.includes(chatId) ? prev.filter((id) => id !== chatId) : [chatId, ...prev]
    );
  }, []);

  return {
    chats,
    setChats,
    pinnedIds,
    togglePin,
    isLocalHistory,
    activeChatId,
    activeChat,
    setActiveChat,
    isLoadingChats,
    isLoadingActive,
    error,
    setError,
    loadChats,
    selectChat,
    createChat,
    removeChat,
    renameChat,
  };
}
