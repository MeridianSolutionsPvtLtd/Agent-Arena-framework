import React from 'react';
import { Sparkles } from 'lucide-react';

// Assistant "thinking" placeholder shown while a reply is in flight.
// Bouncing-dots treatment matches the agent chat's reasoning indicator.
export default function TypingIndicator() {
  return (
    <div className="flex gap-4 animate-in fade-in duration-500">
      <div className="w-9 h-9 rounded-xl bg-white border border-border/60 flex items-center justify-center shrink-0 shadow-sm">
        <Sparkles size={18} className="text-primary animate-pulse" />
      </div>
      <div className="bg-white border border-border/40 px-5 py-4 rounded-3xl rounded-tl-md shadow-sm flex items-center gap-3">
        <div className="flex gap-1.5">
          <div className="w-1.5 h-1.5 bg-primary/40 rounded-full animate-bounce"></div>
          <div className="w-1.5 h-1.5 bg-primary/40 rounded-full animate-bounce [animation-delay:0.2s]"></div>
          <div className="w-1.5 h-1.5 bg-primary/40 rounded-full animate-bounce [animation-delay:0.4s]"></div>
        </div>
        <span className="text-[11px] font-black text-text-secondary/60 uppercase tracking-[0.15em]">Thinking…</span>
      </div>
    </div>
  );
}
