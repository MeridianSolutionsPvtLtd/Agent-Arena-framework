import React from 'react';
import { Sparkles } from 'lucide-react';
import { SUGGESTIONS } from '../constants';

// Shown when no messages exist yet. Suggestion chips prefill the composer.
export default function EmptyState({ onPick }) {
  return (
    <div className="flex-1 overflow-y-auto custom-scrollbar px-6 py-8">
      <div className="max-w-2xl mx-auto h-full flex flex-col items-center justify-center text-center py-12">
        <div className="w-16 h-16 rounded-2xl bg-primary/10 flex items-center justify-center mb-5">
          <Sparkles size={30} className="text-primary" />
        </div>
        <h2 className="text-2xl font-black text-text-primary mb-2">How can I help today?</h2>
        <p className="text-sm text-text-secondary mb-8 max-w-md">
          Start a conversation with the assistant. Your chats are saved and appear in the list on the left.
        </p>
        <div className="grid sm:grid-cols-2 gap-3 w-full">
          {SUGGESTIONS.map((s) => (
            <button
              key={s}
              onClick={() => onPick(s)}
              className="text-left px-4 py-3 rounded-xl border border-border bg-white hover:border-primary/40 hover:bg-primary/5 text-sm text-text-secondary hover:text-text-primary transition-colors cursor-pointer"
            >
              {s}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
