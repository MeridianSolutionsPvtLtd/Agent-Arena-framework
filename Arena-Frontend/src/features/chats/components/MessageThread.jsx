import React, { useRef, useEffect } from 'react';
import MessageBubble from './MessageBubble';
import TypingIndicator from './TypingIndicator';
import { SkeletonMessage } from '../../../components/skeleton';

// Scrollable message list. Auto-scrolls to the newest message / typing state.
export default function MessageThread({ messages, isSending, isLoading = false }) {
  const endRef = useRef(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, isSending]);

  if (isLoading && messages.length === 0) {
    return (
      <div className="flex-1 overflow-y-auto custom-scrollbar px-6 py-8">
        <div className="max-w-3xl mx-auto space-y-6">
          <SkeletonMessage sender="user" />
          <SkeletonMessage sender="ai" />
          <SkeletonMessage sender="user" />
          <SkeletonMessage sender="ai" />
        </div>
      </div>
    );
  }

  return (
    <div className="flex-1 overflow-y-auto custom-scrollbar px-6 py-8">
      <div className="max-w-3xl mx-auto space-y-6">
        {messages.map((m, i) => (
          <MessageBubble key={i} message={m} />
        ))}
        {isSending && <TypingIndicator />}
        <div ref={endRef} className="h-2" />
      </div>
    </div>
  );
}
