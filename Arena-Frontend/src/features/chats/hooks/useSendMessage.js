import { useState, useCallback, useRef } from 'react';
import { updateArenaChat, generateChatTitle } from '../../../services/chats.api';
import { arenaOpenAIChat } from '../../../services/arena.api';
import { DEFAULT_MODEL, DEFAULT_SYSTEM_PROMPT, CONTEXT_WINDOW } from '../constants';
import { normalizeMessageAttachments } from '../../../utils/attachmentUtils';

// Text-only send flow, ported from Arena's ChatContext.sendMessage (minus
// image-gen / file analysis / translate — those land in Slice 2). All network
// I/O goes through the shared service layer; the message shape is the backend's
// { role, content } (see Agent-Integration/models/chat.py ChatMessageSchema).
export function useSendMessage({ activeChat, activeChatId, setActiveChat, setChats }) {
  const [isSending, setIsSending] = useState(false);
  const titleGenRef = useRef(new Set()); // chats we've already auto-titled this session

  // Move a chat to the top of the list (mirrors the backend's updated_at sort).
  // Restamping updated_at matters as well as reordering: the rail persists to a
  // local index that is re-sorted by updated_at on the next load, so without the
  // new timestamp the order would snap back after a refresh.
  const bumpToTop = useCallback((chatId) => {
    setChats((prev) => {
      const idx = prev.findIndex((c) => c.id === chatId);
      if (idx < 0) return prev; // not in the list
      const stamped = { ...prev[idx], updated_at: new Date().toISOString() };
      return [stamped, ...prev.filter((c) => c.id !== chatId)];
    });
  }, [setChats]);

  const sendMessage = useCallback(async (rawContent, overrideChatId = null, attachments = []) => {
    const content = (rawContent || '').trim();
    const chatId = overrideChatId || activeChatId;
    const filesForThisMessage = Array.isArray(attachments) ? [...attachments] : [];
    if ((!content && filesForThisMessage.length === 0) || !chatId || isSending) return null;

    setIsSending(true);
    const { cleanText, attachments: normalizedAtts } = normalizeMessageAttachments(
      content,
      filesForThisMessage.length > 0 ? filesForThisMessage : null
    );
    const finalFiles = normalizedAtts || (filesForThisMessage.length > 0 ? filesForThisMessage : null);
    const fileIdsToSend = (finalFiles || [])
      .map((f) => (typeof f === 'string' ? f : (f.file_id || f.id)))
      .filter(Boolean);

    const userMsg = {
      role: 'user',
      content: cleanText || (finalFiles && finalFiles.length > 0 ? 'Analyze attached document' : ''),
      files: finalFiles,
      attachments: finalFiles,
      timestamp: new Date().toISOString(),
    };

    // Optimistically show the user's message (guarded to the target chat).
    setActiveChat((prev) =>
      prev && prev.id === chatId ? { ...prev, messages: [...(prev.messages || []), userMsg] } : prev
    );

    // Snapshot prior messages BEFORE awaits. Only trust the closure's activeChat
    // if it actually belongs to the target chat (auto-create passes a fresh id).
    const priorMessages = activeChat && activeChat.id === chatId ? activeChat.messages || [] : [];
    const currentMessages = [...priorMessages, userMsg];

    try {
      // 1. Persist the user message.
      await updateArenaChat(chatId, { message: userMsg });

      // 2. Build model context: last-N, coerce system→assistant, prepend prompt.
      const contextMessages = currentMessages
        .slice(-CONTEXT_WINDOW)
        .map((m) => {
          const role = m.role === 'system' ? 'assistant' : m.role;
          let msgContent = m.content || ' ';
          const atts = m.attachments || m.files;
          if (Array.isArray(atts) && atts.length > 0) {
            const docBlocks = atts
              .filter((a) => a && (a.preview || a.text || a.filename))
              .map((a) => {
                const name = a.filename || (typeof a === 'string' ? a : 'Document');
                const textBody = a.preview || a.text || '';
                return textBody ? `--- Document: ${name} ---\n${textBody}` : `--- Document: ${name} ---`;
              })
              .join('\n\n');
            if (docBlocks) {
              msgContent = `${docBlocks}\n\n${msgContent}`;
            }
          }
          return { role, content: msgContent };
        });
      contextMessages.unshift({ role: 'system', content: DEFAULT_SYSTEM_PROMPT });

      // 3. Ask the model. /api/openai/chat returns a single { response } (no stream).
      const chatPayload = { messages: contextMessages, model: DEFAULT_MODEL };
      if (fileIdsToSend.length > 0) {
        chatPayload.file_ids = fileIdsToSend;
      }
      const result = await arenaOpenAIChat(chatPayload);
      const finalContent = (result && result.response) || '';

      // 4. Append + persist the assistant reply.
      const assistantMsg = { role: 'assistant', content: finalContent, timestamp: new Date().toISOString() };
      setActiveChat((prev) =>
        prev && prev.id === chatId ? { ...prev, messages: [...(prev.messages || []), assistantMsg] } : prev
      );
      await updateArenaChat(chatId, { message: assistantMsg });
      bumpToTop(chatId);

      // 5. Auto-title once per chat, after the first real exchange (best-effort).
      if (!titleGenRef.current.has(chatId)) {
        titleGenRef.current.add(chatId);
        try {
          const { title } = await generateChatTitle({ messages: [...currentMessages, assistantMsg] });
          if (title) {
            await updateArenaChat(chatId, { title });
            setActiveChat((prev) => (prev && prev.id === chatId ? { ...prev, title } : prev));
            setChats((prev) => prev.map((c) => (c.id === chatId ? { ...c, title } : c)));
          }
        } catch {
          /* title generation is non-critical — ignore failures */
        }
      }

      return finalContent;
    } catch (e) {
      // Surface the failure as an inline assistant bubble (Playground has no toast).
      const errorMsg = {
        role: 'assistant',
        content: `⚠️ ${e.message || 'Something went wrong. Please try again.'}`,
        timestamp: new Date().toISOString(),
      };
      setActiveChat((prev) =>
        prev && prev.id === chatId ? { ...prev, messages: [...(prev.messages || []), errorMsg] } : prev
      );
      return null;
    } finally {
      setIsSending(false);
    }
  }, [activeChat, activeChatId, isSending, setActiveChat, setChats, bumpToTop]);

  return { sendMessage, isSending };
}
