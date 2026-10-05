import React from 'react';
import { Link } from 'react-router-dom';
import { Plus, MessageSquare, ChevronLeft } from 'lucide-react';
import ChatListItem from './ChatListItem';
import RailUserBlock from './RailUserBlock';
import { SkeletonConversationItem } from '../../../components/skeleton';

// Left conversation rail: back-to-dashboard, New Chat, and the Today/Previous
// grouped list. Adapted from Arena's Sidebar.jsx into Playground's light theme.
function startOfDay(date) {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime();
}
function isToday(iso) {
  if (!iso) return false;
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return false;
  return startOfDay(new Date(t)) === startOfDay(new Date());
}

export default function ConversationRail({
  chats,
  activeChatId,
  isLoading,
  pinnedIds = [],
  isLocalHistory = false,
  onNewChat,
  onSelect,
  onRename,
  onDelete,
  onTogglePin,
}) {
  const pinnedSet = new Set(pinnedIds);
  const pinned = [];
  const today = [];
  const previous = [];
  // Pinned chats are lifted out of the date groups so they never appear twice.
  for (const c of chats) {
    if (pinnedSet.has(c.id)) pinned.push(c);
    else if (isToday(c.updated_at)) today.push(c);
    else previous.push(c);
  }
  // Within Pinned, keep the user's own order (most recently pinned first)
  // rather than recency — that's the point of pinning.
  pinned.sort((a, b) => pinnedIds.indexOf(a.id) - pinnedIds.indexOf(b.id));

  const renderGroup = (label, items) =>
    items.length > 0 && (
      <div className="mb-4">
        <p className="px-3 mb-1.5 text-[10px] font-black uppercase tracking-[0.15em] text-text-secondary/50">{label}</p>
        <div className="space-y-0.5">
          {items.map((c) => (
            <ChatListItem
              key={c.id}
              chat={c}
              active={c.id === activeChatId}
              pinned={pinnedSet.has(c.id)}
              onSelect={onSelect}
              onRename={onRename}
              onDelete={onDelete}
              onTogglePin={onTogglePin}
            />
          ))}
        </div>
      </div>
    );

  return (
    <aside className="w-[300px] shrink-0 h-full flex flex-col bg-white border-r border-border">
      {/* Header / back to dashboard */}
      <div className="h-16 flex items-center px-4 border-b border-border shrink-0">
        <Link
          to="/dashboard"
          className="flex items-center gap-2 text-text-secondary hover:text-text-primary transition-colors"
          title="Back to dashboard"
        >
          <ChevronLeft size={18} />
          <span className="text-sm font-bold">Chats</span>
        </Link>
      </div>

      {/* New chat */}
      <div className="p-3 shrink-0">
        <button
          onClick={onNewChat}
          className="w-full flex items-center justify-center gap-2 px-4 py-2.5 rounded-xl bg-primary text-white text-sm font-bold hover:bg-primary-hover transition-colors active:scale-[0.98] cursor-pointer"
        >
          <Plus size={16} /> New Chat
        </button>
      </div>

      {/* List */}
      <div className="flex-1 overflow-y-auto custom-scrollbar px-2 pb-4">
        {isLoading && chats.length === 0 ? (
          <div className="space-y-1.5 py-2 px-1">
            <SkeletonConversationItem />
            <SkeletonConversationItem />
            <SkeletonConversationItem />
            <SkeletonConversationItem />
            <SkeletonConversationItem />
          </div>
        ) : chats.length === 0 ? (
          <div className="px-3 py-10 text-center">
            <MessageSquare size={28} className="mx-auto text-border mb-2" />
            <p className="text-sm text-text-secondary/70">No conversations yet.</p>
          </div>
        ) : (
          <>
            {renderGroup('Pinned', pinned)}
            {renderGroup('Today', today)}
            {renderGroup('Previous', previous)}
            {isLocalHistory && (
              <p className="px-3 pt-1 text-[10px] leading-relaxed text-text-secondary/45">
                History and pins are remembered on this device.
              </p>
            )}
          </>
        )}
      </div>

      {/* Signed-in identity → Settings (pinned to the bottom of the rail) */}
      <RailUserBlock />
    </aside>
  );
}
