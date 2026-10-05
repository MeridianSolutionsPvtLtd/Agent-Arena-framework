/**
 * Accumulates WebSocket trace events into sidebar “live mission trace” state.
 */

export function initialLiveTrace() {
  return {
    runPhase: 'idle',
    pipeline: null,
    crewSteps: [],
    lastHandoff: null,
    planStepsHint: 0,
    awaitingApproval: false,
    approvalSummary: '',
    approvalPlanSteps: [],
  };
}

/**
 * @param {ReturnType<typeof initialLiveTrace> | null} prev
 * @param {Record<string, unknown>} d parsed WS payload (must include event string)
 */
export function applyLiveTraceEvent(prev, d) {
  const base = prev || { ...initialLiveTrace(), runPhase: 'running' };
  const ev = d && d.event;
  if (!ev) return base;

  switch (ev) {
    case 'planning_start':
      return {
        ...base,
        runPhase: 'running',
        pipeline: { stage: 'planning', label: d.label || 'Architecting flight plan…' },
      };
    case 'planning_complete': {
      const stepCount = Number(d.step_count) || base.planStepsHint;
      const mode = d.mode;
      const isHitl = mode === 'hitl';
      const rawSteps = d.plan_steps;
      const approvalPlanSteps = Array.isArray(rawSteps)
        ? rawSteps.map((p, idx) => ({
            step: Number(p.step) || idx + 1,
            role: String(p.role || ''),
            task: String(p.task || ''),
            tool: String(p.tool || ''),
          }))
        : [];
      return {
        ...base,
        pipeline: null,
        planStepsHint: stepCount,
        awaitingApproval: isHitl,
        approvalSummary: typeof d.label === 'string' ? d.label : '',
        approvalPlanSteps: isHitl ? approvalPlanSteps : [],
        runPhase: isHitl ? 'awaiting_approval' : 'running',
      };
    }
    case 'planning_failed':
      return {
        ...base,
        pipeline: { stage: 'failed', label: d.label || 'Planning issue' },
      };
    case 'compiling_start':
      return {
        ...base,
        runPhase: 'running',
        pipeline: { stage: 'compiling', label: d.label || 'Compiling execution protocol…' },
      };
    case 'compiling_complete':
      return { ...base, pipeline: null };
    case 'validating_start':
      return {
        ...base,
        runPhase: 'running',
        pipeline: { stage: 'validating', label: d.label || 'Quality audit…' },
      };
    case 'validating_complete':
      return { ...base, pipeline: null };
    case 'mission_start':
      return {
        ...base,
        runPhase: 'running',
        pipeline: null,
        planStepsHint: Number(d.plan_steps) || base.planStepsHint,
        awaitingApproval: false,
        approvalSummary: '',
        approvalPlanSteps: [],
      };
    case 'crew_step_start': {
      const stepId = Number(d.step_id);
      const role = d.role || 'Specialist';
      const task = String(d.task_preview || '').trim() || 'Working…';
      const tool = String(d.tool || 'none').toLowerCase();
      const crewSteps = [...base.crewSteps];
      const idx = crewSteps.findIndex((s) => s.stepId === stepId);
      const row = { stepId, role, task, tool, status: 'active' };
      if (idx >= 0) crewSteps[idx] = { ...crewSteps[idx], ...row };
      else crewSteps.push(row);
      return {
        ...base,
        runPhase: 'running',
        pipeline: null,
        crewSteps,
        awaitingApproval: false,
        approvalSummary: '',
        approvalPlanSteps: [],
      };
    }
    case 'crew_step_complete': {
      const stepId = Number(d.step_id);
      const ok = d.ok !== false;
      const crewSteps = base.crewSteps.map((s) =>
        s.stepId === stepId ? { ...s, status: 'done', ok } : s
      );
      return { ...base, crewSteps };
    }
    case 'crew_handoff':
      return {
        ...base,
        lastHandoff: {
          from: d.from_role || '',
          to: d.to_role || '',
          at: Date.now(),
        },
      };
    case 'mission_complete':
      return finalizeLiveTrace({ ...base, runPhase: 'done', pipeline: null });
    default:
      return base;
  }
}

/** Mark run finished and close any stray active steps (WS missed / race). */
export function finalizeLiveTrace(prev) {
  if (!prev) return prev;
  if (prev.runPhase === 'awaiting_approval' || prev.awaitingApproval) {
    return prev;
  }
  const crewSteps = prev.crewSteps.map((s) =>
    s.status === 'active' ? { ...s, status: 'done', ok: s.ok !== false } : s
  );
  return {
    ...prev,
    runPhase: 'done',
    pipeline: null,
    crewSteps,
    awaitingApproval: false,
    approvalSummary: '',
    approvalPlanSteps: [],
  };
}
