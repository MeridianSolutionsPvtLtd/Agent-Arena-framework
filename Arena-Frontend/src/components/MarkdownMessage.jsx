import React from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

// Shared markdown renderer. The component map below was lifted verbatim from the
// agent chat (pages/Chat.jsx) so agent replies and persona-chat replies render
// identically. Keep this as the single source of truth for message markdown.
const components = {
  table: ({ node, ...props }) => (
    <div className="overflow-x-auto my-4">
      <table className="w-full border-collapse border border-border/60 text-sm" {...props} />
    </div>
  ),
  th: ({ node, ...props }) => <th className="border border-border/60 bg-section-bg px-4 py-2 font-black text-left" {...props} />,
  td: ({ node, ...props }) => <td className="border border-border/60 px-4 py-2" {...props} />,
  h1: ({ node, ...props }) => <h1 className="text-2xl font-black mb-4 mt-2" {...props} />,
  h2: ({ node, ...props }) => <h2 className="text-xl font-black mb-3 mt-2" {...props} />,
  h3: ({ node, ...props }) => <h3 className="text-lg font-black mb-2 mt-1" {...props} />,
  p: ({ node, ...props }) => <p className="mb-3 last:mb-0" {...props} />,
  ul: ({ node, ...props }) => <ul className="list-disc pl-5 mb-3" {...props} />,
  ol: ({ node, ...props }) => <ol className="list-decimal pl-5 mb-3" {...props} />,
  a: ({ node, ...props }) => <a className="text-primary font-bold hover:underline" target="_blank" rel="noopener noreferrer" {...props} />,
  code: ({ node, inline, ...props }) =>
    inline
      ? <code className="bg-primary/10 text-primary px-1.5 py-0.5 rounded text-[13px] font-bold" {...props} />
      : <code className="block bg-slate-900 text-slate-100 p-4 rounded-xl text-[13px] overflow-x-auto my-4 font-mono" {...props} />,
};

export default function MarkdownMessage({ content }) {
  return (
    <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
      {content || ''}
    </ReactMarkdown>
  );
}
