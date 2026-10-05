import React, { useEffect, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useChats } from './context/ChatsProvider';
import ConversationRail from './components/ConversationRail';
import MessageThread from './components/MessageThread';
import Composer from './components/Composer';
import EmptyState from './components/EmptyState';

// Orchestrator / route element for /chats and /chats/:chatId. Renders the
// conversation rail + the active thread + composer, and keeps the open chat in
// sync with the URL. Presentational children receive everything via props.
export default function ChatsPage() {
  const { chatId } = useParams();
  const navigate = useNavigate();
  const {
    chats,
    activeChat,
    activeChatId,
    pinnedIds,
    togglePin,
    isLocalHistory,
    isLoadingChats,
    isLoadingActive,
    isSending,
    selectChat,
    createChat,
    removeChat,
    renameChat,
    sendMessage,
  } = useChats();

  const [input, setInput] = useState('');

  // URL param is the source of truth for which chat is open.
  useEffect(() => {
    if (chatId && chatId !== activeChatId) selectChat(chatId);
  }, [chatId, activeChatId, selectChat]);

  const handleNewChat = async () => {
    const id = await createChat();
    if (id) {
      setInput('');
      navigate(`/chats/${id}`);
    }
  };

  const handleSelect = (id) => {
    if (id !== chatId) navigate(`/chats/${id}`);
  };

  const handleDelete = async (id) => {
    // Leave the URL *before* awaiting the removal when the open chat is the one
    // being deleted. Otherwise removeChat's state flush produces one render that
    // still carries the stale :chatId param, and the sync effect above re-fetches
    // the chat we just deleted (a pointless 404 round-trip).
    if (id === chatId) navigate('/chats');
    await removeChat(id);
  };

  const handleSend = async (text, attachments = []) => {
    setInput('');
    let id = activeChatId;
    if (!id) {
      // Auto-create a conversation on first send from the empty state.
      id = await createChat();
      if (!id) return;
      navigate(`/chats/${id}`);
    }
    await sendMessage(text, id, attachments);
  };

  const messages = activeChat?.messages || [];
  const showThread = messages.length > 0 || isLoadingActive || isSending;

  return (
    <div className="flex h-full w-full overflow-hidden">
      <ConversationRail
        chats={chats}
        activeChatId={activeChatId}
        isLoading={isLoadingChats}
        pinnedIds={pinnedIds}
        isLocalHistory={isLocalHistory}
        onNewChat={handleNewChat}
        onSelect={handleSelect}
        onRename={renameChat}
        onDelete={handleDelete}
        onTogglePin={togglePin}
      />

      <main className="flex-1 flex flex-col min-w-0 bg-section-bg">
        {showThread ? (
          <MessageThread messages={messages} isSending={isSending} isLoading={isLoadingActive} />
        ) : (
          <EmptyState onPick={(s) => setInput(s)} />
        )}
        <Composer value={input} onChange={setInput} onSend={handleSend} disabled={isSending} />
      </main>
    </div>
  );
}
