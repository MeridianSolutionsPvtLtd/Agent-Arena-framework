import React from 'react';
import { CheckCircle2, Loader2, CircleDashed } from 'lucide-react';

/**
 * Graph-style collaboration canvas (node–link look) aligned with dashboard mock.
 * Status from liveMission; step hints from crew index + completed set.
 */
export default function CollaborationFlowCanvas({
  crewRoles = [],
  liveMission,
  onSelectScope,
  selectedScope,
  /** Fill parent flex region (tighter chrome for mission workspace) */
  variant = 'default',
}) {
  const workspace = variant === 'workspace';
  const pipelineBlocksCrew = ['planning', 'compiling', 'validating'].includes(
    liveMission?.pipelinePhase
  );
  const phase = liveMission?.phase;
  const completed = new Set(liveMission?.completedRoles || []);
  const activeRole = liveMission?.activeRole;
  const highlight = liveMission?.sidebarHighlight;

  const nodes = [
    { key: 'Overview', label: 'Mission Overview', kind: 'overview' },
    ...crewRoles.map((r) => ({
      key: r.role,
      label: r.role,
      kind: 'crew',
    })),
  ];

  const totalCrew = crewRoles.length;

  function statusForNode(node) {
    if (node.kind === 'overview') {
      if (phase === 'done') return 'complete';
      if (highlight === '_audit') return 'running';
      if (pipelineBlocksCrew && phase === 'running') return 'running';
      if (completed.size > 0 && totalCrew > 0) return 'complete';
      if (phase === 'running' && !pipelineBlocksCrew && !activeRole && completed.size === 0)
        return 'running';
      return 'queued';
    }

    const role = node.key;
    if (completed.has(role)) return 'complete';
    if (!pipelineBlocksCrew && phase === 'running' && activeRole === role) return 'running';
    return 'queued';
  }

  function stepLabel(node, crewIndex0, st) {
    if (node.kind === 'overview') {
      if (st === 'running') return 'Orchestrating pipeline…';
      if (st === 'complete') return 'Brief ready';
      return 'Awaiting execution';
    }
    const pos = crewIndex0 >= 0 ? crewIndex0 + 1 : 1;
    if (st === 'running') return `Step ${pos} of ${totalCrew} · Active`;
    if (st === 'complete') return `Step ${pos} of ${totalCrew} · Done`;
    return `Step ${pos} of ${totalCrew} · Pending`;
  }

  if (nodes.length <= 1) {
    return (
      <div
        className="relative flex min-h-[220px] items-center justify-center overflow-hidden rounded-2xl border border-slate-200/90 bg-slate-100/90 p-8 text-center shadow-inner"
        style={{
          backgroundImage: `radial-gradient(circle, rgb(148 163 184 / 0.35) 1px, transparent 1px)`,
          backgroundSize: '14px 14px',
        }}
      >
        <p className="max-w-sm rounded-xl border border-dashed border-slate-300/80 bg-white/90 px-6 py-5 text-[13px] font-medium leading-relaxed text-slate-600 shadow-sm">
          Add sub-agents in <span className="font-black text-primary">Settings</span> to see the
          collaboration map. Single-agent missions show orchestration only.
        </p>
      </div>
    );
  }

  return (
    <div
      className={`relative rounded-2xl border border-slate-200/90 shadow-[0_12px_40px_rgba(15,23,42,0.08)] ${
        workspace
          ? 'flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden'
          : 'overflow-hidden'
      }`}
      style={{
        backgroundImage: `radial-gradient(circle, rgb(148 163 184 / 0.28) 1px, transparent 1px)`,
        backgroundSize: '16px 16px',
        backgroundColor: 'rgb(226 232 240 / 0.65)',
      }}
    >
      <div className="pointer-events-none absolute inset-0 bg-gradient-to-b from-white/40 via-transparent to-slate-200/30" />

      <div
        className={`relative shrink-0 border-b border-slate-200/80 bg-white/85 backdrop-blur-sm sm:px-6 ${workspace ? 'px-4 py-2' : 'px-5 py-3'}`}
      >
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <p className="text-[9px] font-black uppercase tracking-[0.2em] text-slate-500">
              Collaboration flow
            </p>
            {!workspace && (
              <p className="mt-0.5 text-[11px] font-semibold text-slate-600">
                Live node map · click a node to open that scope
              </p>
            )}
            {workspace && (
              <p className="mt-0.5 text-[10px] text-slate-600">Live node map</p>
            )}
          </div>
          <div className="flex flex-wrap gap-2">
            {[
              ['Complete', 'bg-emerald-100 text-emerald-800 ring-emerald-200/80'],
              ['Running', 'bg-amber-100 text-amber-900 ring-amber-200/80'],
              ['Queued', 'bg-slate-200/90 text-slate-700 ring-slate-300/80'],
            ].map(([label, cls]) => (
              <span
                key={label}
                className={`rounded-full px-2.5 py-1 text-[9px] font-black uppercase tracking-widest ring-1 ${cls}`}
              >
                {label}
              </span>
            ))}
          </div>
        </div>
      </div>

      <div
        className={`relative px-3 sm:px-6 custom-scrollbar ${
          workspace
            ? 'min-h-0 flex-1 overflow-auto py-4'
            : 'min-h-[320px] overflow-auto py-8'
        }`}
      >
        <div className="mx-auto flex min-h-[200px] min-w-max items-center justify-center gap-0 pb-2 sm:min-h-[220px]">
          {nodes.map((node, idx) => {
            const st = statusForNode(node);
            const crewIdx = node.kind === 'crew' ? idx - 1 : -1;
            const isSelected =
              (node.key === 'Overview' && selectedScope === 'Overview') ||
              (node.key !== 'Overview' && selectedScope === node.key);

            const accent =
              st === 'complete'
                ? 'border-emerald-400/90 bg-white shadow-[0_8px_30px_rgba(16,185,129,0.18)]'
                : st === 'running'
                  ? 'border-amber-400 bg-white shadow-[0_12px_40px_rgba(245,158,11,0.28)] ring-2 ring-amber-300/70'
                  : 'border-slate-200/90 bg-white/95 shadow-[0_6px_24px_rgba(15,23,42,0.06)]';

            const topStripe =
              st === 'complete'
                ? 'from-emerald-500 to-emerald-600'
                : st === 'running'
                  ? 'from-amber-400 to-orange-500'
                  : 'from-slate-300 to-slate-400';

            const pill =
              st === 'complete' ? (
                <span className="rounded-md bg-emerald-600 px-2 py-0.5 text-[8px] font-black uppercase tracking-wide text-white shadow-sm">
                  Complete
                </span>
              ) : st === 'running' ? (
                <span className="rounded-md bg-amber-500 px-2 py-0.5 text-[8px] font-black uppercase tracking-wide text-white shadow-sm">
                  Running
                </span>
              ) : (
                <span className="rounded-md bg-slate-300 px-2 py-0.5 text-[8px] font-black uppercase tracking-wide text-slate-800 shadow-sm">
                  Queued
                </span>
              );

            const Icon =
              st === 'complete' ? CheckCircle2 : st === 'running' ? Loader2 : CircleDashed;

            return (
              <React.Fragment key={node.key}>
                {idx > 0 && (
                  <div className="flex h-[112px] w-9 shrink-0 flex-col items-center justify-center px-0.5 sm:h-[120px] sm:w-12">
                    <div className="relative h-1 w-full max-w-[56px] overflow-visible sm:max-w-[72px]">
                      <svg
                        className="absolute -left-1 -right-1 top-1/2 h-8 w-[calc(100%+8px)] -translate-y-1/2 overflow-visible text-slate-400/90 sm:w-[calc(100%+16px)]"
                        viewBox="0 0 100 24"
                        preserveAspectRatio="none"
                      >
                        <path
                          d="M 0 12 Q 25 4 50 12 T 100 12"
                          fill="none"
                          stroke="currentColor"
                          strokeWidth="2"
                          strokeLinecap="round"
                          vectorEffect="non-scaling-stroke"
                          className="text-slate-400"
                        />
                      </svg>
                      <div className="absolute left-1/2 top-1/2 h-2 w-2 -translate-x-1/2 -translate-y-1/2 rounded-full bg-primary shadow-[0_0_0_3px_rgba(255,255,255,0.95)] ring-1 ring-primary/30" />
                    </div>
                  </div>
                )}
                <button
                  type="button"
                  onClick={() => onSelectScope?.(node.key === 'Overview' ? 'Overview' : node.key)}
                  className={`relative flex h-[124px] w-[148px] shrink-0 flex-col overflow-hidden rounded-xl border-2 text-left transition-transform duration-200 hover:z-[1] hover:scale-[1.02] sm:h-[128px] sm:w-[158px] ${accent} ${
                    isSelected ? 'ring-2 ring-primary ring-offset-2 ring-offset-[#e2e8f0]' : ''
                  }`}
                >
                  <div className={`h-1.5 w-full bg-gradient-to-r ${topStripe}`} />
                  <div className="flex flex-1 flex-col p-2.5 sm:p-3">
                    <div className="flex items-start justify-between gap-1.5">
                      <Icon
                        className={`h-5 w-5 shrink-0 sm:h-6 sm:w-6 ${
                          st === 'running' ? 'animate-spin text-amber-600' : ''
                        } ${st === 'complete' ? 'text-emerald-600' : ''} ${
                          st === 'queued' ? 'text-slate-400' : ''
                        }`}
                        strokeWidth={2.2}
                      />
                      {pill}
                    </div>
                    <p className="mt-2 text-[8px] font-black uppercase tracking-[0.18em] text-slate-500">
                      {node.kind === 'overview' ? 'Orchestration' : 'Specialist'}
                    </p>
                    <p className="mt-0.5 line-clamp-2 min-h-[2.25rem] text-[12px] font-black leading-tight tracking-tight text-slate-900 sm:text-[13px]">
                      {node.label}
                    </p>
                    <p className="mt-auto pt-1 text-[9px] font-bold leading-snug text-slate-500 sm:text-[10px]">
                      {stepLabel(node, crewIdx, st)}
                    </p>
                  </div>
                </button>
              </React.Fragment>
            );
          })}
        </div>
      </div>
    </div>
  );
}
