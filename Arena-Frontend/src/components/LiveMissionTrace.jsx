import React, { useEffect, useState } from 'react';
import {
  Users,
  ChevronDown,
  ChevronUp,
  Zap,
  Loader2,
  CheckCircle2,
  CircleSlash,
  Cpu,
  Wrench,
} from 'lucide-react';

function toolLabel(tool) {
  if (!tool || tool === 'none') return 'Reasoning';
  return tool.replace(/_/g, ' ');
}

/**
 * Sidebar live mission trace: same structure as post-turn Mission Trace,
 * driven by WebSocket events (crew steps + orchestration pipeline).
 */
export default function LiveMissionTrace({ liveTrace }) {
  const [open, setOpen] = useState(true);
  const [handoffVisible, setHandoffVisible] = useState(null);

  useEffect(() => {
    if (!liveTrace?.lastHandoff) {
      setHandoffVisible(null);
      return;
    }
    setHandoffVisible(liveTrace.lastHandoff);
    const t = setTimeout(() => setHandoffVisible(null), 2200);
    return () => clearTimeout(t);
  }, [
    liveTrace?.lastHandoff?.from,
    liveTrace?.lastHandoff?.to,
    liveTrace?.lastHandoff?.at,
  ]);

  if (!liveTrace) return null;

  const {
    runPhase,
    pipeline,
    crewSteps = [],
    planStepsHint,
    awaitingApproval,
    approvalSummary,
    approvalPlanSteps = [],
  } = liveTrace;
  const awaitingHitl = awaitingApproval === true || runPhase === 'awaiting_approval';
  const hasCrew = crewSteps.length > 0;
  const pipelineSpinStages = ['planning', 'compiling', 'validating'];
  const showPipelineBanner = !!(pipeline && pipeline.label);
  const pipelineSpin = !!(pipeline && pipelineSpinStages.includes(pipeline.stage));
  const idleEmpty = runPhase === 'idle' && !hasCrew && !showPipelineBanner;

  if (idleEmpty) return null;

  const sortedSteps = [...crewSteps].sort((a, b) => a.stepId - b.stepId);
  const sortedPlanSteps = [...approvalPlanSteps].sort((a, b) => a.step - b.step);

  /** Flow only from steps that actually ran — never the full blueprint roster */
  const flowRoles = [];
  for (const s of sortedSteps) {
    if (s.role && !flowRoles.includes(s.role)) flowRoles.push(s.role);
  }
  const roleLine = flowRoles.length > 0 ? flowRoles.join(' → ') : '';

  let subtitleParts = [];
  if (awaitingHitl) {
    subtitleParts = ['Planning done', 'Awaiting approval'];
  } else if (hasCrew) {
    subtitleParts.push(`${sortedSteps.length} step${sortedSteps.length !== 1 ? 's' : ''}`);
    if (runPhase === 'running') subtitleParts.push('Live');
    else if (runPhase === 'done') subtitleParts.push('Complete');
  } else if (showPipelineBanner) {
    if (pipeline.stage === 'planning') subtitleParts.push('Planning phase');
    else if (pipeline.stage === 'compiling') subtitleParts.push('Compiling protocol');
    else if (pipeline.stage === 'validating') subtitleParts.push('Quality audit');
    else if (pipeline.stage === 'failed') subtitleParts.push('Planning issue');
    else subtitleParts.push('Orchestrating…');
    if (runPhase === 'running') subtitleParts.push('Live');
  } else if (planStepsHint > 0 && runPhase === 'running') {
    subtitleParts.push(`Planned ${planStepsHint} execution step${planStepsHint !== 1 ? 's' : ''}`);
    subtitleParts.push('Live');
  } else {
    if (runPhase === 'running') subtitleParts.push('Live');
    else if (runPhase === 'done') subtitleParts.push('Complete');
  }

  const subtitleText =
    subtitleParts.length > 0 ? subtitleParts.join(' · ') : runPhase === 'running' ? 'Starting…' : 'Collaboration';

  const titleAccent =
    awaitingHitl ? (
      <span className="relative flex h-2 w-2 ml-1">
        <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-amber-400 opacity-75" />
        <span className="relative inline-flex rounded-full h-2 w-2 bg-amber-500" />
      </span>
    ) : runPhase === 'running' ? (
      <span className="relative flex h-2 w-2 ml-1">
        <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-500 opacity-75" />
        <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500" />
      </span>
    ) : null;

  return (
    <div className="rounded-2xl border border-primary/15 bg-gradient-to-br from-primary/[0.06] via-white to-violet-500/[0.04] shadow-[0_8px_40px_rgba(29,78,216,0.08)] overflow-hidden animate-in fade-in slide-in-from-right-3 duration-500">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="w-full flex items-center justify-between gap-2 px-4 py-3 text-left hover:bg-white/60 transition-colors"
      >
        <div className="flex items-center gap-2.5 min-w-0">
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-primary text-white shadow-lg shadow-primary/25">
            <Users size={16} />
          </div>
          <div className="min-w-0">
            <p className="text-[10px] font-black uppercase tracking-[0.2em] text-primary flex items-center gap-1.5">
              Mission trace
              {titleAccent}
            </p>
            <p className="text-[12px] font-bold text-text-primary truncate">{subtitleText}</p>
          </div>
        </div>
        <div className="shrink-0 text-text-secondary">{open ? <ChevronUp size={16} /> : <ChevronDown size={16} />}</div>
      </button>

      {open && (
        <div className="px-4 pb-4 space-y-3 border-t border-primary/10 bg-white/40">
          {awaitingHitl && (
            <div className="pt-3 rounded-xl border border-emerald-200 bg-emerald-50/95 px-3 py-3 shadow-sm">
              <div className="flex items-start gap-2.5">
                <CheckCircle2 className="w-5 h-5 text-emerald-600 shrink-0 mt-0.5" />
                <div className="min-w-0">
                  <p className="text-[10px] font-black uppercase tracking-[0.2em] text-emerald-800 mb-1">
                    Planning complete
                  </p>
                  {sortedPlanSteps.length > 0 ? (
                    <ol className="mt-1.5 space-y-2.5 list-none pl-0">
                      {sortedPlanSteps.map((p) => (
                        <li
                          key={`${p.step}-${p.role}-${p.tool}`}
                          className="rounded-lg border border-emerald-200/90 bg-white/90 px-3 py-2.5 shadow-sm"
                        >
                          <div className="flex flex-wrap items-center gap-x-2 gap-y-1 mb-1.5">
                            <span className="text-[10px] font-black uppercase tracking-widest text-emerald-800">
                              Step {p.step}
                            </span>
                            <span className="text-[11px] font-bold text-primary">{p.role}</span>
                            <span className="text-[9px] font-bold text-text-secondary/80 uppercase tracking-wide flex items-center gap-0.5">
                              <Wrench size={10} className="shrink-0" />
                              {toolLabel(p.tool)}
                            </span>
                          </div>
                          <p className="text-[11px] text-text-primary leading-relaxed whitespace-pre-wrap break-words">
                            {p.task}
                          </p>
                        </li>
                      ))}
                    </ol>
                  ) : (
                    <p className="text-[12px] font-bold text-text-primary leading-snug whitespace-pre-wrap">
                      {approvalSummary ||
                        (planStepsHint > 0
                          ? `Flight plan ready (${planStepsHint} step${planStepsHint !== 1 ? 's' : ''}).`
                          : 'Flight plan ready.')}
                    </p>
                  )}
                  <p className="text-[10px] text-text-secondary mt-2 leading-relaxed">
                    Reply in chat to approve the plan — execution trace appears after you approve.
                  </p>
                </div>
              </div>
            </div>
          )}

          {showPipelineBanner && (
            <div className="pt-3 rounded-xl border border-amber-200 bg-amber-50/90 px-3 py-2.5 flex items-start gap-2">
              {pipelineSpin ? (
                <Loader2 className="w-4 h-4 text-amber-600 shrink-0 animate-spin mt-0.5" />
              ) : (
                <Cpu className="w-4 h-4 text-amber-700 shrink-0 mt-0.5" />
              )}
              <div className="min-w-0">
                <p className="text-[9px] font-black uppercase tracking-widest text-amber-800/90 mb-0.5">
                  {pipeline.stage === 'planning' && 'Orchestration'}
                  {pipeline.stage === 'compiling' && 'Compilation'}
                  {pipeline.stage === 'validating' && 'Quality audit'}
                  {pipeline.stage === 'failed' && 'Planning'}
                  {!['planning', 'compiling', 'validating', 'failed'].includes(pipeline.stage) && 'Orchestration'}
                </p>
                <p className="text-[11px] font-semibold text-text-primary leading-snug">{pipeline.label}</p>
              </div>
            </div>
          )}

          {!hasCrew && runPhase === 'running' && !showPipelineBanner && !awaitingHitl && (
            <div className="pt-2 flex items-center gap-2 text-[11px] text-text-secondary font-medium">
              <Loader2 className="w-3.5 h-3.5 animate-spin shrink-0 text-primary" />
              Waiting for execution steps…
            </div>
          )}

          {handoffVisible && (
            <p className="text-[11px] font-bold text-center text-amber-700 bg-amber-50 border border-amber-100 rounded-lg py-2 px-2 animate-in zoom-in duration-300">
              Handoff{' '}
              <span className="text-text-primary">{handoffVisible.from}</span>
              <span className="mx-1.5 text-amber-500">→</span>
              <span className="text-text-primary">{handoffVisible.to}</span>
            </p>
          )}

          {roleLine && (
            <div className="flex flex-wrap items-center gap-2 text-[10px] text-text-secondary pt-1">
              <Zap size={11} className="text-amber-500 shrink-0" />
              <span className="font-black uppercase tracking-widest">Flow</span>
              <span className="text-text-primary font-bold">{roleLine}</span>
            </div>
          )}

          {sortedSteps.length > 0 && (
            <div className="rounded-xl border border-border/50 bg-white/90 p-2">
              <div className="space-y-0">
                {sortedSteps.map((s, i) => {
                  const active = s.status === 'active';
                  const ok = s.ok !== false;
                  const failed = s.status === 'done' && !ok;
                  const done = s.status === 'done' && ok;
                  const prev = i > 0 ? sortedSteps[i - 1] : null;
                  const prevDone = prev && prev.status === 'done' && prev.ok !== false;
                  const isLast = i === sortedSteps.length - 1;

                  const railAbove =
                    i > 0
                      ? prevDone
                        ? 'bg-primary shadow-[0_0_6px_rgba(29,78,216,0.35)]'
                        : 'bg-border/45'
                      : '';
                  const railBelow = !isLast
                    ? done
                      ? 'bg-primary shadow-[0_0_6px_rgba(29,78,216,0.25)]'
                      : active
                        ? 'bg-gradient-to-b from-amber-400 via-amber-200 to-border/40'
                        : 'bg-border/40'
                    : '';

                  const nodeClass =
                    done
                      ? 'bg-primary border-primary text-white shadow-[0_2px_10px_rgba(29,78,216,0.35)]'
                      : active
                        ? 'bg-amber-400 border-amber-500 text-slate-900 shadow-[0_0_14px_rgba(251,191,36,0.45)] ring-2 ring-amber-100'
                        : failed
                          ? 'bg-red-500 border-red-600 text-white shadow-sm'
                          : 'bg-section-bg border-border/70 text-text-secondary';

                  return (
                    <div key={`${s.stepId}-${i}`} className="flex gap-2.5 items-stretch">
                      <div className="flex w-10 shrink-0 flex-col items-center">
                        {i > 0 && (
                          <div className={`w-[4px] flex-1 min-h-[10px] rounded-full transition-colors duration-300 ${railAbove}`} />
                        )}
                        <div
                          className={`relative z-[1] flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border-2 text-[10px] font-black transition-all duration-300 ${nodeClass}`}
                        >
                          {done ? (
                            <CheckCircle2 size={16} strokeWidth={2.5} className="text-white" />
                          ) : failed ? (
                            <CircleSlash size={16} strokeWidth={2.5} />
                          ) : (
                            <span>{s.stepId ?? i + 1}</span>
                          )}
                        </div>
                        {!isLast && (
                          <div className={`w-[4px] flex-1 min-h-[14px] rounded-full transition-colors duration-500 ${railBelow}`} />
                        )}
                      </div>

                      <details className="group mb-1 flex-1 min-w-0 rounded-xl border border-border/40 bg-white/95 open:border-primary/25 open:bg-white open:shadow-sm">
                        <summary className="cursor-pointer px-3 py-2.5 flex items-start gap-2 list-none [&::-webkit-details-marker]:hidden">
                          <div className="flex-1 min-w-0">
                            <div className="flex items-center gap-2 flex-wrap mb-0.5">
                              <span className="text-[9px] font-black uppercase tracking-widest text-primary">{s.role}</span>
                              {active ? (
                                <span className="text-[8px] font-black uppercase px-1.5 py-px rounded-full bg-amber-100 text-amber-800 border border-amber-200 flex items-center gap-1">
                                  <Cpu size={10} className="shrink-0" /> Active
                                </span>
                              ) : ok ? (
                                <span className="text-[8px] font-black uppercase px-1.5 py-px rounded-full bg-emerald-50 text-emerald-700 border border-emerald-100 flex items-center gap-0.5">
                                  <CheckCircle2 size={10} /> Done
                                </span>
                              ) : (
                                <span className="text-[8px] font-black uppercase px-1.5 py-px rounded-full bg-red-50 text-red-700 border border-red-100 flex items-center gap-0.5">
                                  <CircleSlash size={10} /> Issue
                                </span>
                              )}
                              <span className="text-[8px] font-bold text-text-secondary/70 uppercase tracking-wide flex items-center gap-0.5">
                                <Wrench size={10} />
                                {toolLabel(s.tool)}
                              </span>
                            </div>
                            <span className="text-[11px] font-bold text-text-primary line-clamp-2 leading-snug">{s.task}</span>
                          </div>
                          <ChevronDown className="w-3.5 h-3.5 text-text-secondary shrink-0 mt-1 group-open:rotate-180 transition-transform" />
                        </summary>
                        <div className="px-3 pb-2.5 pt-0">
                          <p className="text-[10px] leading-relaxed text-text-secondary bg-section-bg/80 rounded-lg p-2 border border-border/40">
                            {active ? (
                              <>
                                <span className="font-black text-primary uppercase tracking-wide text-[9px]">In progress</span>
                                {' — '}
                                Output will appear in this specialist&apos;s tab and in the recap below when the step finishes.
                              </>
                            ) : ok ? (
                              <>
                                Step finished successfully. Full formatted output is in the{' '}
                                <span className="font-bold text-text-primary">{s.role}</span> thread and in Mission recap on the
                                latest reply.
                              </>
                            ) : (
                              <>This step reported an error or partial failure; check the specialist tab for details.</>
                            )}
                          </p>
                        </div>
                      </details>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {runPhase === 'done' && hasCrew && !awaitingHitl && (
            <p className="text-[10px] font-bold text-emerald-700/90 flex items-center gap-1.5 pt-1">
              <CheckCircle2 size={14} className="shrink-0" />
              Mission trace complete — see overview for full recap.
            </p>
          )}
        </div>
      )}
    </div>
  );
}
