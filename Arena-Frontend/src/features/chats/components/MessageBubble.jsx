import React from 'react';
import { User, Sparkles, Paperclip } from 'lucide-react';
import MarkdownMessage from '../../../components/MarkdownMessage';
import { normalizeMessageAttachments } from '../../../utils/attachmentUtils';

// A single message. User text is shown verbatim (whitespace preserved); assistant
// replies render through the shared MarkdownMessage. Styling mirrors the agent
// chat bubbles (pages/Chat.jsx) so the two chat surfaces feel like one product.
export default function MessageBubble({ message }) {
  const isUser = message.role === 'user';
  const rawAttachments = message.attachments || message.files || message.metadata?.attachments || null;
  const { cleanText, attachments: normalizedAttachments } = isUser
    ? normalizeMessageAttachments(message.content, rawAttachments)
    : { cleanText: message.content, attachments: rawAttachments };
  const attachments = normalizedAttachments || [];

  return (
    <div className={`flex gap-4 animate-in fade-in slide-in-from-bottom-4 duration-500 ${isUser ? 'flex-row-reverse' : ''}`}>
      <div
        className={`w-9 h-9 rounded-xl flex items-center justify-center shrink-0 shadow-sm
          ${isUser ? 'bg-primary text-white' : 'bg-white border border-border/60 text-primary'}`}
      >
        {isUser ? <User size={18} /> : <Sparkles size={18} />}
      </div>
      <div
        className={`max-w-[75%] p-5 text-[15px] leading-relaxed shadow-[0_2px_10px_rgba(0,0,0,0.02)]
          ${isUser
            ? 'bg-primary text-white rounded-3xl rounded-tr-md whitespace-pre-wrap'
            : 'bg-white border border-border/60 text-text-primary rounded-3xl rounded-tl-md'}`}
      >
        {isUser && Array.isArray(attachments) && attachments.length > 0 && (
          <div className="mb-3 flex flex-wrap gap-2">
            {attachments.map((att, attIdx) => {
              const name = att.filename || (typeof att === 'string' ? att : 'Attachment');
              const sizeStr = att.size_bytes
                ? att.size_bytes > 1024 * 1024
                  ? `${(att.size_bytes / (1024 * 1024)).toFixed(1)} MB`
                  : `${(att.size_bytes / 1024).toFixed(0)} KB`
                : null;
              return (
                <div
                  key={att.file_id || attIdx}
                  className="inline-flex items-center gap-1.5 rounded-xl bg-white/20 px-3 py-1.5 text-[12px] font-semibold text-white shadow-sm border border-white/25 backdrop-blur-sm"
                  title={att.file_id || name}
                >
                  <Paperclip size={13} className="shrink-0 text-white/90" />
                  <span className="truncate max-w-[240px]">{name}</span>
                  {sizeStr && (
                    <span className="text-[10px] text-white/75 font-normal">({sizeStr})</span>
                  )}
                </div>
              );
            })}
          </div>
        )}
        {cleanText ? (isUser ? cleanText : <MarkdownMessage content={cleanText} />) : null}
      </div>
    </div>
  );
}
