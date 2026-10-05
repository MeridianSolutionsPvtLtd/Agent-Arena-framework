import React, { createContext, useContext } from 'react';
import { useChatsController } from '../hooks/useChatsController';
import { useSendMessage } from '../hooks/useSendMessage';

// Scoped provider for the /chats route subtree. Composes the list/CRUD controller
// with the text-send hook and exposes them as one context so the page + its
// presentational components stay thin. Not mounted app-wide — no global overhead.
const ChatsContext = createContext(null);

export function ChatsProvider({ children }) {
  const controller = useChatsController();
  const { sendMessage, isSending } = useSendMessage({
    activeChat: controller.activeChat,
    activeChatId: controller.activeChatId,
    setActiveChat: controller.setActiveChat,
    setChats: controller.setChats,
  });

  const value = { ...controller, sendMessage, isSending };
  return <ChatsContext.Provider value={value}>{children}</ChatsContext.Provider>;
}

export function useChats() {
  const ctx = useContext(ChatsContext);
  if (!ctx) throw new Error('useChats must be used within a ChatsProvider');
  return ctx;
}
