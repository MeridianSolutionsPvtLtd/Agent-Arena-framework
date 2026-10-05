import React, { useState } from 'react';
import { Users, ChevronDown, ChevronUp, Zap } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { formatAgentToolOutputForMarkdown } from '../utils/formatAgentToolOutput';

/**
 * Post-turn recap on the assistant message (full outputs). Sidebar shows live trace during the run.
 */
export default function CollaborationTimeline({ collaboration, crewRoles = [] }) {
  const [open, setOpen] = useState(true);

  const sequence = collaboration?.agent_sequence || [];
  const steps = collaboration?.steps || [];

  if (!collaboration) return null;
  const hasVisual = steps.length > 0 || sequence.length > 0;
  if (!hasVisual) return null;

  const rolesFromSteps = [];
  for (const s of steps) {
    const r = s?.role;
    if (r && !rolesFromSteps.includes(r)) rolesFromSteps.push(r);
  }
  const roleLine =
    rolesFromSteps.length > 0
      ? rolesFromSteps.join(' → ')
      : sequence.length > 0
        ? [...new Set(sequence)].join(' → ')
        : (crewRoles || []).map((r) => r.role).filter(Boolean).join(' → ') || '';

  return (
    <div className="mb-5 rounded-2xl border border-primary/15 bg-gradient-to-br from-primary/[0.06] via-white to-violet-500/[0.04] shadow-[0_8px_40px_rgba(29,78,216,0.08)] overflow-hidden animate-in fade-in slide-in-from-bottom-3 duration-700">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="w-full flex items-center justify-between gap-3 px-5 py-4 text-left hover:bg-white/60 transition-colors"
      >
        <div className="flex items-center gap-3 min-w-0">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-primary text-white shadow-lg shadow-primary/25">
            <Users size={18} />
          </div>
          <div className="min-w-0">
            <p className="text-[11px] font-black uppercase tracking-[0.2em] text-primary">Mission recap</p>
            <p className="text-sm font-bold text-text-primary truncate">
              {steps.length} step{steps.length !== 1 ? 's' : ''}
              {sequence.length ? ` · ${sequence.length} role transition${sequence.length !== 1 ? 's' : ''}` : ''}
            </p>
          </div>
        </div>
        <div className="shrink-0 text-text-secondary">
          {open ? <ChevronUp size={18} /> : <ChevronDown size={18} />}
        </div>
      </button>

      {open && (
        <div className="px-5 pb-5 space-y-4 border-t border-primary/10 bg-white/40">
          {roleLine && (
            <div className="pt-3 flex flex-wrap items-center gap-2 text-[11px] text-text-secondary">
              <Zap size={12} className="text-amber-500 shrink-0" />
              <span className="font-black uppercase tracking-widest">Flow</span>
              <span className="text-text-primary font-bold">{roleLine}</span>
            </div>
          )}

          {steps.length > 0 && (
            <div className="rounded-xl border border-border/50 bg-white/80 divide-y divide-border/40">
              {steps.map((s, i) => (
                <details key={i} className="group">
                  <summary className="cursor-pointer px-4 py-3 flex items-center gap-3 list-none [&::-webkit-details-marker]:hidden">
                    <span className="flex h-7 min-w-7 items-center justify-center rounded-lg bg-section-bg text-[10px] font-black text-primary border border-primary/10">
                      {s.step ?? i + 1}
                    </span>
                    <span className="text-[13px] font-bold text-text-primary flex-1 line-clamp-2">
                      {s.task || 'Step'}
                    </span>
                    <ChevronDown className="w-4 h-4 text-text-secondary shrink-0 group-open:rotate-180 transition-transform" />
                  </summary>
                  <div className="px-4 pb-3 pt-0">
                    <div className="text-[13px] leading-relaxed text-text-primary bg-section-bg/80 rounded-lg p-3 border border-border/40 max-h-64 overflow-y-auto">
                      <ReactMarkdown
                        remarkPlugins={[remarkGfm]}
                        components={{
                          table: ({ node, ...props }) => (
                            <div className="overflow-x-auto my-3">
                              <table className="w-full border-collapse border border-border/60 text-[12px]" {...props} />
                            </div>
                          ),
                          th: ({ node, ...props }) => (
                            <th className="border border-border/60 bg-white px-2 py-1.5 font-bold text-left" {...props} />
                          ),
                          td: ({ node, ...props }) => (
                            <td className="border border-border/60 px-2 py-1.5" {...props} />
                          ),
                          h3: ({ node, ...props }) => <h3 className="text-[13px] font-black mb-2 mt-1 text-text-primary" {...props} />,
                          p: ({ node, ...props }) => <p className="mb-2 last:mb-0 whitespace-pre-wrap" {...props} />,
                          code: ({ node, inline, ...props }) =>
                            inline ? (
                              <code className="bg-primary/10 text-primary px-1 rounded text-[12px] font-mono" {...props} />
                            ) : (
                              <code
                                className="block bg-slate-900 text-slate-100 p-3 rounded-lg text-[11px] overflow-x-auto my-2 font-mono whitespace-pre"
                                {...props}
                              />
                            ),
                        }}
                      >
                        {formatAgentToolOutputForMarkdown(s.output_preview || '') || '—'}
                      </ReactMarkdown>
                    </div>
                  </div>
                </details>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
