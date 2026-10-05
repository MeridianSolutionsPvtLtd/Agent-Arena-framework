import React from 'react';
import { Download, ExternalLink, FileText, Image as ImageIcon, Table2 } from 'lucide-react';
import { extractDataCollectorArtifacts } from '../utils/dataCollectorArtifacts';

function iconFor(kind) {
  if (kind === 'chart') return <ImageIcon size={14} />;
  if (kind === 'csv') return <Table2 size={14} />;
  return <FileText size={14} />;
}

export default function DataCollectorArtifacts({ text, artifacts }) {
  const items = extractDataCollectorArtifacts(text, artifacts);
  if (!items.length) return null;

  const chart = items.find((item) => item.kind === 'chart');
  const files = items.filter((item) => item.kind !== 'chart');

  return (
    <div className="mt-4 space-y-3">
      {chart && (
        <div className="overflow-hidden rounded-2xl border border-border/60 bg-section-bg/50">
          <div className="flex items-center justify-between gap-3 border-b border-border/50 bg-white px-4 py-2.5">
            <div className="flex items-center gap-2 text-[10px] font-black uppercase tracking-[0.16em] text-text-secondary">
              <ImageIcon size={13} className="text-primary" />
              Generated Visualization
            </div>
            <a
              href={chart.url}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1.5 rounded-lg border border-border/60 px-2.5 py-1.5 text-[10px] font-black uppercase tracking-widest text-text-secondary transition hover:border-primary/40 hover:text-primary"
            >
              <ExternalLink size={12} />
              Open
            </a>
          </div>
          <img
            src={chart.url}
            alt={chart.filename || 'Generated data visualization'}
            className="block max-h-[420px] w-full bg-white object-contain"
          />
        </div>
      )}

      {files.length > 0 && (
        <div className="grid gap-2 sm:grid-cols-2">
          {files.map((item) => (
            <a
              key={`${item.kind}-${item.url}`}
              href={item.downloadUrl || item.url}
              target="_blank"
              rel="noopener noreferrer"
              download={item.filename}
              className="flex items-center justify-between gap-3 rounded-xl border border-border/60 bg-white px-3 py-2.5 text-text-primary transition hover:border-primary/40 hover:bg-primary/5"
            >
              <span className="flex min-w-0 items-center gap-2">
                <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-primary/5 text-primary">
                  {iconFor(item.kind)}
                </span>
                <span className="min-w-0">
                  <span className="block text-[10px] font-black uppercase tracking-[0.16em] text-text-secondary">
                    {item.label}
                  </span>
                  <span className="block truncate text-xs font-bold">{item.filename}</span>
                </span>
              </span>
              <Download size={14} className="shrink-0 text-primary" />
            </a>
          ))}
        </div>
      )}
    </div>
  );
}
