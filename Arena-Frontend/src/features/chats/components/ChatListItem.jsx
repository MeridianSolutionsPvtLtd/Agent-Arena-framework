import React, { useState, useRef, useEffect } from 'react';
import { Trash2, Pencil, Check, X, Pin } from 'lucide-react';

// One conversation row: click to open, hover to reveal pin/rename/delete. Rename
// is an inline editor; delete confirms first (matches Arena's window.confirm).
// The pin button stays visible while pinned so the state is readable without
// hovering every row.
export default function ChatListItem({ chat, active, pinned, onSelect, onRename, onDelete, onTogglePin }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(chat.title || 'New Chat');
  const inputRef = useRef(null);

  useEffect(() => {
    if (editing) inputRef.current?.focus();
  }, [editing]);
  useEffect(() => {
    if (!editing) setDraft(chat.title || 'New Chat');
  }, [chat.title, editing]);

  const commit = () => {
    const clean = draft.trim();
    if (clean && clean !== chat.title) onRename(chat.id, clean);
    setEditing(false);
  };
  const cancel = () => {
    setDraft(chat.title || 'New Chat');
    setEditing(false);
  };
  const handleDelete = (e) => {
    e.stopPropagation();
    if (window.confirm('Delete this conversation? This cannot be undone.')) onDelete(chat.id);
  };

  if (editing) {
    return (
      <div className={`flex items-center gap-1 px-2 py-1.5 rounded-lg border ${active ? 'border-primary/40 bg-primary/5' : 'border-border bg-white'}`}>
        <input
          ref={inputRef}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') commit();
            if (e.key === 'Escape') cancel();
          }}
          className="flex-1 min-w-0 bg-transparent text-sm text-text-primary outline-none px-1"
        />
        <button onClick={commit} className="p-1 text-success hover:bg-success/10 rounded cursor-pointer" title="Save">
          <Check size={14} />
        </button>
        <button onClick={cancel} className="p-1 text-text-secondary hover:bg-gray-100 rounded cursor-pointer" title="Cancel">
          <X size={14} />
        </button>
      </div>
    );
  }

  return (
    <div
      onClick={() => onSelect(chat.id)}
      className={`group flex items-center gap-2 px-3 py-2 rounded-lg cursor-pointer transition-colors border-l-2
        ${active
          ? 'bg-primary/5 text-primary border-primary'
          : 'text-text-secondary hover:bg-gray-50 hover:text-text-primary border-transparent'}`}
    >
      <span className="flex-1 min-w-0 truncate text-sm font-medium">{chat.title || 'New Chat'}</span>
      <div className="flex items-center gap-0.5">
        <button
          onClick={(e) => { e.stopPropagation(); onTogglePin(chat.id); }}
          className={`p-1 rounded hover:bg-gray-200/70 cursor-pointer transition-opacity ${
            pinned
              ? 'text-primary opacity-100'
              : 'text-text-secondary opacity-0 group-hover:opacity-100'
          }`}
          title={pinned ? 'Unpin' : 'Pin'}
        >
          <Pin size={13} className={pinned ? 'fill-current' : undefined} />
        </button>
        <div className="flex items-center gap-0.5 opacity-0 group-hover:opacity-100 transition-opacity">
          <button
            onClick={(e) => { e.stopPropagation(); setEditing(true); }}
            className="p-1 rounded hover:bg-gray-200/70 text-text-secondary cursor-pointer"
            title="Rename"
          >
            <Pencil size={13} />
          </button>
          <button
            onClick={handleDelete}
            className="p-1 rounded hover:bg-red-50 text-text-secondary hover:text-red-600 cursor-pointer"
            title="Delete"
          >
            <Trash2 size={13} />
          </button>
        </div>
      </div>
    </div>
  );
}
