import React, { useState, useRef, useEffect } from 'react';
import { useParams, useNavigate, Link } from 'react-router-dom';
import { 
  Send, User, Paperclip, Plus, Activity, X, 
  CheckCircle2, Clock, ChevronLeft, ChevronRight, BrainCircuit, Settings,
  Sparkles, ShieldCheck, Zap, ArrowRightLeft, Search, LayoutGrid, GitBranch,
  FileStack, ScrollText, Database, Bookmark, Brain, Trash2, AlertTriangle,
  Download, Loader2, ChevronDown,
} from 'lucide-react';
import { useAgent } from '../context/AgentContext';
import {
  apiRunAgent,
  apiUploadFile,
  apiUpdateAgentConfig,
  getTraceWebSocketUrl,
  apiExportAgentExe,
  apiSubmitToolApproval,
  apiResumeToolExecution,
} from '../services/api';
import Button from '../components/Button';
import Badge from '../components/Badge';
import CollaborationTimeline from '../components/CollaborationTimeline';
import LiveMissionTrace from '../components/LiveMissionTrace';
import { applyLiveTraceEvent, initialLiveTrace, finalizeLiveTrace } from '../utils/liveTraceModel';
import MarkdownMessage from '../components/MarkdownMessage';
import AgentDNAEditor from '../components/AgentDNAEditor';
import CollaborationFlowCanvas from '../components/CollaborationFlowCanvas';
import { formatAgentToolOutputForMarkdown } from '../utils/formatAgentToolOutput';
import { normalizeMessageAttachments } from '../utils/attachmentUtils';
import { DESKTOP_AGENT_ID, IS_DESKTOP_AGENT } from '../utils/desktopAgent';
import DataCollectorArtifacts from '../components/DataCollectorArtifacts';
import ToolApprovalCard from '../components/chat/ToolApprovalCard';
import { SkeletonMessage, SkeletonConversationItem, SkeletonChatWorkspace } from '../components/skeleton';

function formatElapsed(ms) {
  if (ms == null || ms < 0) return '—';
  const s = Math.floor(ms / 1000);
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  return [h, m, sec].map((n) => String(n).padStart(2, '0')).join(':');
}

export default function Chat({ forcedAgentId = null }) {
  const { agentId } = useParams();
  const navigate = useNavigate();
  const {
    agents,
    chats,
    activities,
    loading,
    addMessage,
    addActivity,
    clearActivities,
    loadChatHistory,
    fetchAgents,
    subAgentHistories,
    syncIntelligence,
    clearAgentHistory,
  } = useAgent();
  
  const [input, setInput] = useState('');
  const [isLoadingHistory, setIsLoadingHistory] = useState(true);
  const [showDetails, setShowDetails] = useState(false);
  const [showAllTools, setShowAllTools] = useState(false);
  const [editedConfig, setEditedConfig] = useState(null);
  const [isProcessing, setIsProcessing] = useState(false);
  const [showClearConfirm, setShowClearConfirm] = useState(false);
  const [lastRunTokens, setLastRunTokens] = useState(0);
  const [cumulativeTokens, setCumulativeTokens] = useState(0);
  const [threadId, setThreadId] = useState(null);
  const [uploadedFiles, setUploadedFiles] = useState([]);
  /** Live WebSocket-driven crew highlights during /agents/run */
  const [liveMission, setLiveMission] = useState(null);
  /** Accumulated step-wise trace for sidebar Mission Trace (same shape as post-turn recap) */
  const [liveTrace, setLiveTrace] = useState(null);
  /** Right System Trace + activity panel — collapsible to give chat full width */
  const [tracePanelOpen, setTracePanelOpen] = useState(false);
  /** Dashboard workspace: collaboration canvas vs chat-focused views */
  const [workspaceTab, setWorkspaceTab] = useState('flow');
  const [agentSearch, setAgentSearch] = useState('');
  const [missionClockStart, setMissionClockStart] = useState(null);
  const [nowTick, setNowTick] = useState(() => Date.now());
  const [exportMenuOpen, setExportMenuOpen] = useState(false);
  const [exportingKind, setExportingKind] = useState(null);

  // ── NEW: Sub-Agent Command State ──
  const [activeTab, setActiveTab] = useState('Overview'); // 'Overview' or specific Agent Role
  const [handoffs, setHandoffs] = useState([]);

  const endRef = useRef(null);
  const fileInputRef = useRef(null);
  /** Cancels staged “Analyzing…” sidebar timers when a new send starts */
  const activityStageTimersRef = useRef([]);

  const effectiveAgentId = forcedAgentId || agentId;
  const activeAgent = agents.find(a => a.id === effectiveAgentId)
    || (IS_DESKTOP_AGENT ? agents.find(a => a.id === DESKTOP_AGENT_ID) : agents[0]);
  const activeChat = activeAgent ? (chats[activeAgent.id] || []) : [];
  const activeActivity = activeAgent ? (activities[activeAgent.id] || []) : [];

  useEffect(() => {
    const handleEsc = (e) => {
      if (e.key !== 'Escape') return;
      if (showDetails) setShowDetails(false);
      else if (tracePanelOpen) setTracePanelOpen(false);
    };
    window.addEventListener('keydown', handleEsc);
    return () => window.removeEventListener('keydown', handleEsc);
  }, [showDetails, tracePanelOpen]);

  useEffect(() => {
    if (!effectiveAgentId && activeAgent) navigate(`/chat/${activeAgent.id}`, { replace: true });
  }, [effectiveAgentId, activeAgent, navigate]);

  useEffect(() => {
    if (activeAgent?.id) {
      setIsLoadingHistory(true);
      loadChatHistory(activeAgent.id)
        .then((data) => {
          if (data?.threadId) setThreadId(data.threadId);
          setCumulativeTokens(data?.totalTokens || 0);
          setLastRunTokens(0);
        })
        .finally(() => {
          setIsLoadingHistory(false);
        });
      syncIntelligence(activeAgent.id);
    }
  }, [activeAgent?.id, loadChatHistory, syncIntelligence]);

  useEffect(() => {
    setMissionClockStart(null);
    setWorkspaceTab('flow');
  }, [activeAgent?.id]);

  useEffect(() => { endRef.current?.scrollIntoView({ behavior: 'smooth' }); }, [activeChat]);

  const missionRunning =
    isProcessing || liveMission?.phase === 'running';

  useEffect(() => {
    if (!missionRunning) return undefined;
    const id = setInterval(() => setNowTick(Date.now()), 1000);
    return () => clearInterval(id);
  }, [missionRunning]);

  const buildHistory = () => {
    return activeChat.slice(-10).map(m => `${m.sender === 'user' ? 'User' : 'Agent'}: ${m.text}`).join('\n');
  };

  const handleExportExe = async () => {
    if (!activeAgent?.id || exportingKind) return;
    setExportMenuOpen(false);
    setExportingKind('exe');
    addActivity(activeAgent.id, {
      id: Date.now(),
      status: 'processing',
      text: 'Building downloadable agent app (.exe)…',
      timestamp: new Date().toISOString(),
    });
    try {
      await apiExportAgentExe(activeAgent.id);
      addActivity(activeAgent.id, {
        id: Date.now() + 1,
        status: 'success',
        text: 'Portable agent app downloaded (.exe)',
        timestamp: new Date().toISOString(),
      });
    } catch (err) {
      addActivity(activeAgent.id, {
        id: Date.now() + 1,
        status: 'error',
        text: err.message || 'Portable app build failed',
        timestamp: new Date().toISOString(),
      });
    } finally {
      setExportingKind(null);
    }
  };

  const handleFileUpload = async (e) => {
    const files = Array.from(e.target.files || []);
    if (files.length === 0) return;
    
    try {
      for (const file of files) {
        addActivity(activeAgent.id, { id: Date.now() + Math.random(), status: 'processing', text: `Uploading ${file.name}...`, timestamp: new Date().toISOString() });
        const result = await apiUploadFile(file);
        if (result.files && result.files.length > 0) {
          setUploadedFiles(prev => [...prev, ...result.files]);
          addActivity(activeAgent.id, { id: Date.now() + Math.random(), status: 'success', text: `File uploaded: ${file.name}`, timestamp: new Date().toISOString() });
        }
        if (result.errors && result.errors.length > 0) {
          result.errors.forEach((err) => {
            addActivity(activeAgent.id, { id: Date.now() + Math.random(), status: 'error', text: `Upload error (${err.filename}): ${err.detail || err.code}`, timestamp: new Date().toISOString() });
          });
        }
      }
    } catch (err) {
      addActivity(activeAgent.id, { id: Date.now(), status: 'error', text: `Upload failed: ${err.message}`, timestamp: new Date().toISOString() });
    } finally {
      if (e.target) e.target.value = '';
    }
  };

  const handleSend = async () => {
    if (!input.trim() || !activeAgent || isProcessing) return;
    const userText = input.trim();
    const filesForThisMessage = [...uploadedFiles];
    const fileIdsToSend = filesForThisMessage
      .map(f => (typeof f === 'string' ? f : (f.file_id || f.id)))
      .filter(Boolean);

    setInput('');
    setUploadedFiles([]);
    setIsProcessing(true);
    setMissionClockStart(Date.now());
    setNowTick(Date.now());

    activityStageTimersRef.current.forEach(clearTimeout);
    activityStageTimersRef.current = [];
    clearActivities(activeAgent.id);

    const { cleanText: cleanUserText, attachments: normalizedUserAttachments } = normalizeMessageAttachments(
      userText,
      filesForThisMessage.length > 0 ? filesForThisMessage : null
    );

    addMessage(activeAgent.id, {
      id: Date.now(),
      sender: 'user',
      text: cleanUserText,
      timestamp: new Date().toISOString(),
      attachments: normalizedUserAttachments,
    });

    const stages = [
      { text: 'Analyzing instruction...', delay: 200 },
      { text: 'Planning workflow...', delay: 800 },
      { text: 'Executing sub-tasks...', delay: 1800 },
    ];
    stages.forEach((stage, i) => {
      const tid = setTimeout(() => {
        addActivity(activeAgent.id, { id: Date.now() + i, status: 'processing', text: stage.text, timestamp: new Date().toISOString() });
      }, stage.delay);
      activityStageTimersRef.current.push(tid);
    });

    const traceId = `trace_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 10)}`;
    let traceWs = null;

    setLiveMission({
      phase: 'running',
      activeRole: null,
      completedRoles: [],
      handoff: null,
      taskPreview: '',
      planSteps: 0,
      pipelinePhase: null,
      pipelineLabel: '',
      sidebarHighlight: null,
    });
    setLiveTrace({ ...initialLiveTrace(), runPhase: 'running' });

    try {
      traceWs = await new Promise((resolve, reject) => {
        const url = getTraceWebSocketUrl(traceId);
        const ws = new WebSocket(url);
        const timer = setTimeout(() => {
          try {
            ws.close();
          } catch (_) {}
          reject(new Error('trace_ws_timeout'));
        }, 8000);
        ws.onopen = () => {
          clearTimeout(timer);
          try {
            ws.send('ping');
          } catch (_) {}
          resolve(ws);
        };
        ws.onerror = () => {
          clearTimeout(timer);
          reject(new Error('trace_ws_error'));
        };
      });

      traceWs.onmessage = (ev) => {
        let d;
        try {
          d = JSON.parse(ev.data);
        } catch {
          return;
        }
        if (!d?.event) return;
        setLiveTrace((prev) => applyLiveTraceEvent(prev, d));
        setLiveMission((prev) => {
          const base = { ...(prev || {}), phase: 'running' };
          switch (d.event) {
            case 'planning_start':
              return {
                ...base,
                pipelinePhase: 'planning',
                pipelineLabel: d.label || 'Architecting flight plan…',
                activeRole: null,
                sidebarHighlight: null,
              };
            case 'planning_complete':
              return {
                ...base,
                pipelinePhase: 'planning_done',
                pipelineLabel: d.label || '',
                planSteps: Number(d.step_count) || base.planSteps || 0,
              };
            case 'planning_failed':
              return {
                ...base,
                pipelinePhase: 'planning_done',
                pipelineLabel: d.label || 'Planning encountered an issue',
              };
            case 'compiling_start':
              return {
                ...base,
                pipelinePhase: 'compiling',
                pipelineLabel: d.label || 'Compiling execution protocol…',
                activeRole: null,
              };
            case 'compiling_complete':
              return {
                ...base,
                pipelinePhase: 'compiling_done',
                pipelineLabel: d.label || '',
              };
            case 'validating_start':
              return {
                ...base,
                pipelinePhase: 'validating',
                pipelineLabel: d.label || 'Quality audit…',
                activeRole: null,
                sidebarHighlight: '_audit',
              };
            case 'validating_complete':
              return {
                ...base,
                pipelinePhase: 'validating_done',
                sidebarHighlight: null,
              };
            case 'mission_start':
              return {
                ...base,
                planSteps: Number(d.plan_steps) || 0,
                pipelinePhase: null,
                pipelineLabel: '',
              };
            case 'crew_step_start':
              return {
                ...base,
                activeRole: d.role,
                taskPreview: d.task_preview || '',
                sidebarHighlight: d.role,
              };
            case 'crew_handoff':
              return {
                ...base,
                handoff: { from: d.from_role, to: d.to_role, at: Date.now() },
                activeRole: d.to_role,
                sidebarHighlight: d.to_role,
              };
            case 'crew_step_complete': {
              const cr = [...(base.completedRoles || [])];
              if (d.role && !cr.includes(d.role)) cr.push(d.role);
              return { ...base, completedRoles: cr };
            }
            case 'mission_complete':
              return { ...base, phase: 'done', activeRole: null, sidebarHighlight: null };
            default:
              return prev;
          }
        });
      };
    } catch (wsErr) {
      console.warn('Live crew trace unavailable:', wsErr?.message || wsErr);
    }

    try {
      const history = buildHistory();
      const result = await apiRunAgent(
        activeAgent.id,
        userText,
        history,
        threadId,
        traceId,
        fileIdsToSend
      );

      if (result.thread_id) setThreadId(result.thread_id);
      if (result.token_usage?.per_query?.total_tokens) {
        setLastRunTokens(result.token_usage.per_query.total_tokens);
      }
      if (result.token_usage?.cumulative_all_threads != null) {
        setCumulativeTokens(result.token_usage.cumulative_all_threads);
      } else if (result.token_usage?.cumulative?.total_tokens) {
        setCumulativeTokens(result.token_usage.cumulative.total_tokens);
      }

      if (result.hitl_pending) {
        const apiSteps = Array.isArray(result.flight_plan_steps) ? result.flight_plan_steps : [];
        setLiveTrace((prev) => ({
          ...(prev || { ...initialLiveTrace(), runPhase: 'running' }),
          runPhase: 'awaiting_approval',
          awaitingApproval: true,
          pipeline: null,
          approvalSummary: prev?.approvalSummary || '',
          planStepsHint:
            apiSteps.length > 0 ? apiSteps.length : (prev?.planStepsHint ?? 0),
          approvalPlanSteps: apiSteps.length > 0 ? apiSteps : (prev?.approvalPlanSteps || []),
        }));
      }

      const toolExecutionId =
        result.tool_execution_id ||
        result.data?.tool_execution_id ||
        result.metadata?.tool_execution_id ||
        null;

      addMessage(activeAgent.id, {
        id: Date.now() + 100,
        sender: 'ai',
        text: result.response,
        timestamp: new Date().toISOString(),
        trace_id: result.trace_id,
        collaboration: result.collaboration || null,
        artifacts: result.artifacts || null,
        tool_execution_id: toolExecutionId,
        hitl_pending: Boolean(result.hitl_pending),
      });
      addActivity(activeAgent.id, {
        id: Date.now() + 200,
        status: 'success',
        text: result.hitl_pending ? 'Approval required — review in chat to continue' : 'Task completed',
        timestamp: new Date().toISOString(),
      });
      setUploadedFiles([]);
      
      syncIntelligence(activeAgent.id).then(() => {
         if (result.agent_sequence && result.agent_sequence.length > 1) {
            const seq = result.agent_sequence;
            const uniqueSeq = [...new Set(seq)];
            if (uniqueSeq.length > 1) {
               const toast = {
                  id: Date.now(),
                  type: 'handoff',
                  text: `Mission Handoff: ${uniqueSeq.join(' → ')}`,
                  timestamp: new Date().toISOString()
               };
               setHandoffs(prev => [...prev, toast]);
               setTimeout(() => setHandoffs(prev => prev.filter(t => t.id !== toast.id)), 6000);
            }
         }
      });
    } catch (err) {
      addMessage(activeAgent.id, { id: Date.now() + 100, sender: 'ai', text: `Error: ${err.message}`, timestamp: new Date().toISOString() });
      addActivity(activeAgent.id, { id: Date.now() + 200, status: 'error', text: `Failed: ${err.message}`, timestamp: new Date().toISOString() });
    } finally {
      try {
        if (traceWs && traceWs.readyState === WebSocket.OPEN) traceWs.close();
      } catch (_) {}
      setLiveMission((prev) =>
        prev && prev.phase !== 'idle' ? { ...prev, phase: 'done', activeRole: null, sidebarHighlight: null } : prev
      );
      setLiveTrace((prev) => (prev ? finalizeLiveTrace(prev) : prev));
      setIsProcessing(false);
    }
  };

  const handleApproveTool = async (executionId) => {
    if (!activeAgent || isProcessing) return;
    setIsProcessing(true);
    addActivity(activeAgent.id, {
      id: Date.now(),
      status: 'processing',
      text: 'Approving and resuming tool execution…',
      timestamp: new Date().toISOString(),
    });

    try {
      await apiSubmitToolApproval(executionId, 'approved');
      const resumed = await apiResumeToolExecution(executionId);

      const responseText =
        resumed.response ||
        resumed.data?.response ||
        resumed.data?.message ||
        resumed.message ||
        'Tool execution resumed successfully.';

      addMessage(activeAgent.id, {
        id: Date.now() + 100,
        sender: 'ai',
        text: responseText,
        timestamp: new Date().toISOString(),
        artifacts: resumed.data?.artifacts || resumed.artifacts || null,
        collaboration: resumed.data?.collaboration || resumed.collaboration || null,
      });

      addActivity(activeAgent.id, {
        id: Date.now() + 200,
        status: 'success',
        text: 'Approved tool executed successfully',
        timestamp: new Date().toISOString(),
      });
    } catch (err) {
      console.error('Failed to resume tool execution:', err);
      addMessage(activeAgent.id, {
        id: Date.now() + 100,
        sender: 'ai',
        text: `Error executing approved tool: ${err.message}`,
        timestamp: new Date().toISOString(),
      });
      addActivity(activeAgent.id, {
        id: Date.now() + 200,
        status: 'error',
        text: `Resume failed: ${err.message}`,
        timestamp: new Date().toISOString(),
      });
      throw err;
    } finally {
      setIsProcessing(false);
    }
  };

  const handleRejectTool = async (executionId, reason) => {
    if (!activeAgent || isProcessing) return;
    setIsProcessing(true);
    addActivity(activeAgent.id, {
      id: Date.now(),
      status: 'processing',
      text: 'Rejecting tool execution…',
      timestamp: new Date().toISOString(),
    });

    try {
      await apiSubmitToolApproval(executionId, 'rejected', reason);

      addMessage(activeAgent.id, {
        id: Date.now() + 100,
        sender: 'ai',
        text: `Tool execution was rejected${reason ? `: "${reason}"` : '.'}`,
        timestamp: new Date().toISOString(),
      });

      addActivity(activeAgent.id, {
        id: Date.now() + 200,
        status: 'error',
        text: 'Tool execution rejected by user',
        timestamp: new Date().toISOString(),
      });
    } catch (err) {
      console.error('Failed to reject tool execution:', err);
      addActivity(activeAgent.id, {
        id: Date.now() + 200,
        status: 'error',
        text: `Rejection failed: ${err.message}`,
        timestamp: new Date().toISOString(),
      });
      throw err;
    } finally {
      setIsProcessing(false);
    }
  };

  const handleKeyDown = (e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend(); } };
  const formatTime = (iso) => {
    if (!iso || typeof iso !== 'string') return '';
    const d = new Date(iso);
    return Number.isNaN(d.getTime()) ? '' : d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  };

  if (!activeAgent) {
    if (loading) {
      return <SkeletonChatWorkspace />;
    }
    return (
      <div className="flex h-screen w-screen items-center justify-center bg-section-bg p-6 text-center">
        <div className="max-w-md p-8 bg-white border border-border/60 rounded-3xl shadow-sm">
          <div className="w-16 h-16 bg-primary/10 rounded-2xl flex items-center justify-center mx-auto mb-4 text-primary">
            <ShieldCheck size={32} />
          </div>
          <h2 className="text-xl font-bold text-text-primary mb-2">No custom agents found</h2>
          <p className="text-text-secondary mb-6 text-sm font-medium">You haven't created any custom agents yet. Deploy a new agent to start chatting in the workspace.</p>
          <Button onClick={() => navigate('/builder')} className="rounded-xl px-6">Deploy New Agent</Button>
        </div>
      </div>
    );
  }

  const crewRoles = activeAgent?._blueprint?.crew_roles || activeAgent?.crew_roles || [];
  const showScopeTabs = crewRoles.length > 0;

  const filteredAgents = agents.filter(
    (a) =>
      !agentSearch.trim() ||
      a.name.toLowerCase().includes(agentSearch.trim().toLowerCase())
  );
  const elapsedMs =
    missionClockStart != null ? Math.max(0, nowTick - missionClockStart) : null;
  const completedRolesCount = (liveMission?.completedRoles || []).length;
  const runningSpecialists =
    missionRunning &&
    liveMission?.activeRole &&
    !['planning', 'compiling', 'validating'].includes(liveMission?.pipelinePhase)
      ? 1
      : 0;
  const confidenceLabel =
    liveMission?.phase === 'done' ? '94%' : missionRunning ? '…' : '—';
  const missionIdLabel = threadId
    ? `M-${String(threadId).replace(/[^a-zA-Z0-9]/g, '').slice(-8).toUpperCase()}`
    : '—';
  const traceProgressPct =
    liveMission?.phase === 'done'
      ? 100
      : crewRoles.length > 0
        ? Math.min(100, Math.round((completedRolesCount / crewRoles.length) * 100))
        : missionRunning
          ? 12
          : 0;

  const workspaceTabs = [
    { id: 'flow', label: 'Collaboration flow', Icon: LayoutGrid },
    { id: 'timeline', label: 'Timeline', Icon: GitBranch },
  ];

  const messagesSection = (
    <>
      {isLoadingHistory ? (
        <div className="space-y-6 py-6 animate-in fade-in duration-300">
          <SkeletonMessage sender="user" />
          <SkeletonMessage sender="ai" />
          <SkeletonMessage sender="user" />
          <SkeletonMessage sender="ai" />
        </div>
      ) : activeChat.length === 0 ? (
        <div className="py-20 flex flex-col items-center text-center space-y-6 animate-in fade-in slide-in-from-bottom-4 duration-1000">
          <div className="w-20 h-20 bg-primary/5 rounded-[2.5rem] flex items-center justify-center text-primary shadow-inner border border-primary/10">
            <Sparkles size={40} className="animate-pulse" />
          </div>
          <div className="space-y-2">
            <h2 className="text-2xl font-black text-text-primary tracking-tight">Deployment Successful</h2>
            <p className="text-text-secondary font-medium max-w-sm mx-auto">
              I am <span className="text-primary font-bold">{activeAgent.name}</span>, your specialized AI agent. I've initialized my reasoning engine and am ready for your first instruction.
            </p>
          </div>
          <div className="w-full max-w-md p-6 bg-section-bg rounded-[2rem] border border-border/60 text-left">
            <p className="text-[10px] font-black text-text-secondary uppercase tracking-[0.2em] mb-3 border-l-2 border-primary pl-3">Initial Mission</p>
            <p className="text-sm text-text-primary font-bold leading-relaxed">{activeAgent.purpose}</p>
          </div>
          <p className="text-[11px] font-bold text-text-secondary/40 uppercase tracking-widest">Awaiting your command below</p>
        </div>
      ) : (
        <div className="space-y-6">
              {(activeTab === 'Overview' ? activeChat : (subAgentHistories[activeAgent.id]?.[activeTab] || [])).map((msg, i) => {
                const roleColors = ['text-blue-600', 'text-purple-600', 'text-emerald-600', 'text-amber-600', 'text-rose-600'];
                const roleIndex = activeTab === 'Overview' ? 0 : (activeAgent._blueprint?.crew_roles || []).findIndex(r => r.role === activeTab) % roleColors.length;
                const roleColor = roleColors[roleIndex >= 0 ? roleIndex : 0];

                const isUserMsg = msg.sender === 'user';
                const { cleanText, attachments } = isUserMsg
                  ? normalizeMessageAttachments(msg.text, msg.attachments)
                  : { cleanText: msg.text, attachments: msg.attachments };

                return (
                  <div key={i} className={`flex gap-6 ${isUserMsg ? 'flex-row-reverse' : ''}`}>
                    <div className={`w-9 h-9 rounded-xl flex items-center justify-center shrink-0 shadow-sm border transition-all duration-500 ${
                      isUserMsg ? 'bg-primary text-white border-primary/10' : 'bg-white border-border/60 ' + roleColor
                    }`}>
                      {isUserMsg ? <User size={18} /> : (
                        <div className="font-black text-[10px]">
                          {activeTab === 'Overview' ? 'AI' : activeTab.substring(0, 2).toUpperCase()}
                        </div>
                      )}
                    </div>
                    <div className={`flex flex-col ${isUserMsg ? 'items-end' : 'items-start'} max-w-[80%]`}>
                      {activeTab !== 'Overview' && !isUserMsg && (
                        <div className="flex items-center gap-1.5 mb-1.5 px-2 py-0.5 bg-section-bg rounded-full border border-border/40">
                           <div className={`w-1 h-1 rounded-full bg-current ${roleColor}`}></div>
                           <span className={`text-[9px] font-black uppercase tracking-[0.2em] ${roleColor}`}>{activeTab}</span>
                        </div>
                      )}
                      {!isUserMsg && msg.collaboration && activeTab === 'Overview' && (
                        <div className="w-full max-w-full mb-3">
                          <CollaborationTimeline
                            collaboration={msg.collaboration}
                            crewRoles={activeAgent._blueprint?.crew_roles || activeAgent.crew_roles || []}
                          />
                        </div>
                      )}
                      <div className={`p-5 text-[15px] leading-relaxed shadow-[0_2px_10px_rgba(0,0,0,0.02)] transition-all ${
                        isUserMsg
                          ? 'bg-primary text-white rounded-3xl rounded-tr-md'
                          : 'bg-white border border-border/60 text-text-primary rounded-3xl rounded-tl-md'
                      }`}>
                      {isUserMsg && Array.isArray(attachments) && attachments.length > 0 && (
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
                      {cleanText ? (
                        <MarkdownMessage
                          content={isUserMsg ? cleanText : formatAgentToolOutputForMarkdown(cleanText)}
                        />
                      ) : null}
                      {msg.sender === 'ai' && (
                        <DataCollectorArtifacts text={msg.text} artifacts={msg.artifacts} />
                      )}
                      {msg.sender === 'ai' && msg.tool_execution_id && (
                        <ToolApprovalCard
                          executionId={msg.tool_execution_id}
                          onApprove={handleApproveTool}
                          onReject={handleRejectTool}
                          disabled={isProcessing}
                        />
                      )}
                    </div>
                    <div className="mt-2 flex items-center gap-3 px-2">
                      <span className="text-[10px] font-bold text-text-secondary/40 uppercase tracking-[0.1em]">{formatTime(msg.timestamp)}</span>
                      {msg.sender === 'ai' && msg.trace_id && (
                        <span className="text-[10px] font-bold text-primary/40 uppercase tracking-[0.1em] flex items-center gap-1">
                          <ShieldCheck size={10} /> Verified Trace
                        </span>
                      )}
                    </div>
                  </div>
                </div>
                );
              })}
              {isProcessing && (
                <div className="flex gap-6 animate-in fade-in duration-500">
                  <div className="w-9 h-9 rounded-xl bg-white border border-border/60 flex items-center justify-center shrink-0 shadow-sm">
                    <Zap size={18} className="text-primary animate-pulse" />
                  </div>
                  <div className="bg-white border border-border/40 p-5 rounded-3xl rounded-tl-md shadow-sm flex items-center gap-4">
                    <div className="flex gap-1.5">
                      <div className="w-1.5 h-1.5 bg-primary/40 rounded-full animate-bounce"></div>
                      <div className="w-1.5 h-1.5 bg-primary/40 rounded-full animate-bounce [animation-delay:0.2s]"></div>
                      <div className="w-1.5 h-1.5 bg-primary/40 rounded-full animate-bounce [animation-delay:0.4s]"></div>
                    </div>
                    <span className="text-[11px] font-black text-text-secondary/60 uppercase tracking-[0.15em]">Reasoning...</span>
                  </div>
                </div>
              )}
              <div ref={endRef} className="h-6" />
            </div>
      )}
    </>
  );

  return (
    <div className="flex h-screen w-screen overflow-hidden bg-[#c5d0dd] selection:bg-primary/10">
      {/* ─── LEFT SIDEBAR: FUNCTIONAL AGENTS ──────────────────────────────── */}
      {!IS_DESKTOP_AGENT && (
      <div className="z-20 flex w-[300px] shrink-0 flex-col border-r border-slate-300/50 bg-white shadow-[6px_0_32px_rgba(15,23,42,0.06)]">
        <div className="flex h-[72px] items-center justify-between border-b border-slate-200/90 px-5">
          <div className="flex min-w-0 items-center gap-3">
            <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-primary text-white shadow-lg shadow-primary/25">
              <ShieldCheck size={18} />
            </div>
            <div className="min-w-0">
              <h2 className="text-[11px] font-black uppercase tracking-[0.2em] text-slate-500">Functional agents</h2>
              <div className="mt-1 flex items-center gap-2">
                <span className="truncate text-[14px] font-bold tracking-tight text-slate-900">Workspace</span>
                <span className="flex h-6 min-w-[1.5rem] items-center justify-center rounded-full bg-slate-100 px-2 text-[11px] font-black text-slate-700 ring-1 ring-slate-200/80">
                  {agents.length}
                </span>
              </div>
            </div>
          </div>
          <Link to="/dashboard" className="p-2 text-text-secondary hover:text-primary transition-all hover:bg-section-bg rounded-lg flex items-center gap-2 group shrink-0">
            <ChevronLeft size={18} className="group-hover:-translate-x-1 transition-transform" />
          </Link>
        </div>

        <div className="px-3 pb-2 pt-3">
          <div className="relative">
            <Search size={14} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
            <input
              type="search"
              value={agentSearch}
              onChange={(e) => setAgentSearch(e.target.value)}
              placeholder="Search agents…"
              className="w-full rounded-xl border border-slate-200 bg-slate-50 py-2.5 pl-9 pr-3 text-[12px] font-medium text-slate-900 placeholder:text-slate-400 outline-none focus:border-primary/40 focus:bg-white focus:ring-2 focus:ring-primary/15"
            />
          </div>
        </div>
        
        <div className="flex-1 overflow-y-auto p-3 space-y-1 custom-scrollbar">
          {loading && agents.length === 0 ? (
            <div className="space-y-2 py-1">
              <SkeletonConversationItem />
              <SkeletonConversationItem />
              <SkeletonConversationItem />
              <SkeletonConversationItem />
            </div>
          ) : (
            filteredAgents.map(agent => (
              <div key={agent.id} className="space-y-1">
                <button onClick={() => navigate(`/chat/${agent.id}`)}
                  className={`w-full flex items-center gap-3.5 p-3 rounded-xl text-left transition-all group relative ${
                    agent.id === activeAgent.id ? 'bg-primary/5 text-primary shadow-[inset_0_0_0_1px_rgba(29,78,216,0.1)]' : 'hover:bg-section-bg text-text-secondary'
                  }`}>
                  <div className={`w-10 h-10 rounded-xl border flex items-center justify-center font-bold shrink-0 transition-all ${
                    agent.id === activeAgent.id ? 'border-primary/20 bg-white text-primary shadow-sm scale-110' : 'border-border/60 bg-white text-text-secondary'
                  }`}>{agent.name.charAt(0).toUpperCase()}</div>
                  <div className="flex-1 min-w-0">
                    <p className={`text-sm font-bold truncate ${agent.id === activeAgent.id ? 'text-primary' : 'text-text-primary'}`}>{agent.name}</p>
                    <p className="text-[11px] truncate opacity-60 font-medium">Active Mission</p>
                  </div>
                  {agent.id === activeAgent.id && (
                    <div className="absolute right-3 top-1/2 -translate-y-1/2 w-1.5 h-1.5 bg-primary rounded-full animate-pulse shadow-[0_0_8px_rgba(29,78,216,0.5)]"></div>
                  )}
                </button>
              </div>
            ))
          )}
        </div>

        <div className="border-t border-slate-200/90 bg-slate-50/50 p-4">
          <button
            type="button"
            onClick={() => navigate('/builder')}
            className="flex w-full items-center justify-center gap-2 rounded-xl border border-dashed border-slate-300 bg-white py-3 text-xs font-bold text-slate-600 shadow-sm transition-all hover:border-primary/40 hover:bg-primary/5 hover:text-primary"
          >
            <Plus size={16} /> New functional agent
          </button>
        </div>
      </div>
      )}

      {/* ─── MAIN CONTENT (elevated dashboard card) ──────────────────────────────── */}
      <div className="flex min-h-0 min-w-0 flex-1 flex-col p-2 sm:p-2.5">
        <div className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-2xl border border-white/70 bg-white shadow-[0_28px_90px_rgba(15,23,42,0.14)] ring-1 ring-slate-200/80">
        <div className="shrink-0 border-b border-slate-200/90 bg-white px-4 py-2.5 sm:px-6">
          <div className="flex flex-wrap items-center justify-between gap-2 sm:gap-3">
            <div className="flex min-w-0 items-center gap-3">
              <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border border-slate-200 bg-gradient-to-br from-slate-50 to-slate-100 text-[15px] font-black text-primary shadow-inner">
                {activeAgent.name.charAt(0).toUpperCase()}
              </div>
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
                  <h1 className="text-[15px] font-black leading-tight tracking-tight text-text-primary">{activeAgent.name}</h1>
                  <span
                    className={`rounded-md px-2.5 py-1 text-[9px] font-black uppercase tracking-[0.15em] shadow-sm ${
                      missionRunning
                        ? 'bg-amber-400 text-amber-950 ring-1 ring-amber-500/40'
                        : 'bg-slate-200 text-slate-700 ring-1 ring-slate-300/80'
                    }`}
                  >
                    {missionRunning ? 'Running' : 'Idle'}
                  </span>
                  <span className="rounded-md bg-indigo-50 text-indigo-700 ring-1 ring-indigo-500/20 px-2.5 py-1 text-[9px] font-black uppercase tracking-[0.08em] shadow-sm flex items-center gap-1.5 animate-in fade-in duration-300">
                    <Database size={10} className="text-indigo-500" />
                    Total: {cumulativeTokens.toLocaleString()} tokens
                  </span>
                </div>
                <div className="mt-0.5 flex flex-wrap items-center gap-1.5 text-[10px] text-text-secondary">
                  <span className="font-bold uppercase tracking-wider text-text-secondary/70">Active mission</span>
                  <code className="rounded border border-slate-200 bg-slate-100 px-1.5 py-px font-mono text-[10px] font-bold text-slate-800">
                    {missionIdLabel}
                  </code>
                </div>
              </div>
            </div>
            <div className="flex items-center gap-2">
              {/*
              {!IS_DESKTOP_AGENT && (
              <div className="relative">
                <button
                  type="button"
                  disabled={!activeAgent?.id || !!exportingKind}
                  onClick={() => setExportMenuOpen((o) => !o)}
                  className="flex shrink-0 items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-[11px] font-bold text-slate-600 shadow-sm transition-all hover:border-primary/35 hover:bg-slate-50 hover:text-primary cursor-pointer disabled:opacity-50"
                >
                  {exportingKind ? (
                    <Loader2 size={14} className="animate-spin" />
                  ) : (
                    <Download size={14} />
                  )}
                  Download
                  <ChevronDown size={12} className={exportMenuOpen ? 'rotate-180' : ''} />
                </button>
                {exportMenuOpen && (
                  <>
                    <div
                      className="fixed inset-0 z-40"
                      aria-hidden
                      onClick={() => setExportMenuOpen(false)}
                    />
                    <div className="absolute right-0 top-[calc(100%+6px)] z-50 min-w-[240px] rounded-xl border border-slate-200 bg-white py-1 shadow-xl">
                      <button
                        type="button"
                        disabled={!!exportingKind}
                        onClick={handleExportExe}
                        className="flex w-full flex-col items-start gap-0.5 px-4 py-2.5 text-left text-[11px] font-bold text-primary hover:bg-primary/5 disabled:opacity-50"
                      >
                        <span>Download Agent (.exe)</span>
                        <span className="text-[9px] font-medium text-slate-500">Thin app · connects to backend</span>
                      </button>
                    </div>
                  </>
                )}
              </div>
              )}
              */}
              <button
                type="button"
                onClick={() => setShowClearConfirm(true)}
                className="flex shrink-0 items-center gap-1.5 rounded-lg border border-red-200 bg-red-50/50 px-3 py-1.5 text-[11px] font-bold text-red-600 shadow-sm transition-all hover:border-red-300 hover:bg-red-50 hover:text-red-700 cursor-pointer animate-in fade-in"
              >
                <Trash2 size={14} /> Clear History
              </button>
              <button
                type="button"
                onClick={() => {
                  const blueprint = activeAgent._blueprint || {};
                  setEditedConfig({
                    name: activeAgent.name,
                    system_prompt: activeAgent.system_prompt || blueprint.system_prompt,
                    crew_roles: blueprint.crew_roles || activeAgent.crew_roles || [],
                    tools: blueprint.tools || activeAgent.tools || [],
                    executor_policy: blueprint.executor_policy || blueprint.agent_config?.executor_policy || {},
                    validator_config: blueprint.validator_config || blueprint.agent_config?.validator_config || { checklist: [] },
                  });
                  setShowDetails(true);
                }}
                className="flex shrink-0 items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-[11px] font-bold text-slate-600 shadow-sm transition-all hover:border-primary/35 hover:bg-slate-50 hover:text-primary cursor-pointer"
              >
                <Settings size={14} /> Settings
              </button>
            </div>
          </div>
          <div className="mt-2 overflow-hidden rounded-lg border border-slate-200/90 bg-slate-50/90 shadow-inner">
            <div className="flex flex-wrap divide-x divide-slate-200/90 sm:flex-nowrap">
              {[
                { k: 'Sub-agents', v: String(crewRoles.length) },
                {
                  k: 'Complete',
                  v: crewRoles.length ? `${completedRolesCount}/${crewRoles.length}` : '—',
                },
                { k: 'Running', v: String(runningSpecialists) },
                { k: 'Confidence', v: confidenceLabel },
                { k: 'Tokens', v: lastRunTokens != null ? lastRunTokens.toLocaleString() : '0' },
                {
                  k: 'Elapsed time',
                  v: elapsedMs != null ? formatElapsed(elapsedMs) : '—',
                },
              ].map((s) => (
                <div
                  key={s.k}
                  className="min-w-[88px] flex-1 px-2.5 py-2 text-center sm:min-w-0 sm:flex-none sm:px-3 sm:text-left"
                >
                  <p className="text-[8px] font-black uppercase tracking-[0.16em] text-slate-500">{s.k}</p>
                  <p className="mt-0.5 text-[13px] font-black tabular-nums leading-tight tracking-tight text-slate-900">{s.v}</p>
                </div>
              ))}
            </div>
          </div>
        </div>

        <div className="flex shrink-0 gap-0 overflow-x-auto border-b border-slate-200/90 bg-white px-1 sm:px-3">
          {workspaceTabs.map(({ id, label, Icon }) => (
            <button
              key={id}
              type="button"
              onClick={() => setWorkspaceTab(id)}
              className={`flex shrink-0 items-center gap-1.5 border-b-2 px-3 py-2 text-[9px] font-black uppercase tracking-[0.1em] transition-colors sm:px-4 ${
                workspaceTab === id
                  ? 'border-primary text-primary'
                  : 'border-transparent text-slate-500 hover:border-slate-200 hover:text-slate-800'
              }`}
            >
              <Icon size={13} strokeWidth={2.5} className={workspaceTab === id ? 'text-primary' : 'opacity-70'} />
              <span className="whitespace-nowrap">{label}</span>
            </button>
          ))}
        </div>

        {/* Mission scope: Overview vs sub-agents — horizontal tabs */}
        {showScopeTabs && (
          <div className="shrink-0 border-b border-slate-200/80 bg-gradient-to-b from-slate-50/90 to-white px-3 sm:px-6">
            <div
              className="-mx-1 flex max-w-full items-center gap-1 overflow-x-auto px-1 py-1.5 [scrollbar-width:thin]"
              role="tablist"
              aria-label="Mission scope"
            >
              <button
                type="button"
                role="tab"
                aria-selected={activeTab === 'Overview'}
                onClick={() => setActiveTab('Overview')}
                className={`flex shrink-0 items-center gap-1.5 rounded-full px-3 py-1.5 text-[9px] font-black uppercase tracking-widest transition-all ${
                  activeTab === 'Overview'
                    ? 'bg-primary text-white shadow-md shadow-primary/25'
                    : 'border border-border/60 bg-white/90 text-text-secondary hover:border-primary/30 hover:bg-white hover:text-text-primary'
                } ${liveMission?.sidebarHighlight === '_audit' ? 'ring-2 ring-violet-400 ring-offset-2' : ''}`}
              >
                <span
                  className={`h-1.5 w-1.5 shrink-0 rounded-full ${
                    activeTab === 'Overview'
                      ? 'bg-white'
                      : liveMission?.sidebarHighlight === '_audit'
                        ? 'bg-violet-500 animate-pulse'
                        : 'bg-text-secondary/30'
                  }`}
                />
                <span className="max-w-[200px] truncate sm:max-w-none">Mission Overview</span>
              </button>

              {crewRoles.map((sub, i) => {
                const pipelineBlocksCrew = ['planning', 'compiling', 'validating'].includes(liveMission?.pipelinePhase);
                const execBusy = liveMission?.phase === 'running' && !pipelineBlocksCrew;
                const roleLive = execBusy && liveMission?.activeRole === sub.role;
                const isActive = activeTab === sub.role;
                return (
                  <button
                    key={`${sub.role}-${i}`}
                    type="button"
                    role="tab"
                    aria-selected={isActive}
                    onClick={() => setActiveTab(sub.role)}
                    className={`flex shrink-0 items-center gap-1.5 rounded-full px-3 py-1.5 text-[9px] font-black uppercase tracking-widest transition-all ${
                      isActive
                        ? 'border-2 border-primary bg-white text-primary shadow-sm'
                        : 'border border-transparent bg-white/60 text-text-secondary hover:border-border/80 hover:bg-white'
                    } ${roleLive ? 'ring-2 ring-amber-400 ring-offset-1 bg-amber-50/90' : ''}`}
                  >
                    <span
                      className={`h-1.5 w-1.5 shrink-0 rounded-full ${
                        isActive ? 'bg-primary animate-pulse' : roleLive ? 'scale-125 bg-amber-500 animate-pulse' : 'bg-text-secondary/30'
                      }`}
                    />
                    <span className="max-w-[min(12rem,40vw)] truncate" title={sub.role}>
                      {sub.role}
                    </span>
                  </button>
                );
              })}
            </div>
          </div>
        )}

        <div className="flex min-h-0 flex-1 flex-col overflow-hidden bg-slate-100/60">
          <div
            className={`mx-auto flex min-h-0 w-full flex-1 flex-col px-3 py-3 sm:px-5 ${
              workspaceTab === 'flow'
                ? 'max-w-5xl min-h-0 flex flex-col overflow-hidden'
                : 'max-w-4xl overflow-y-auto'
            } custom-scrollbar`}
          >
              {workspaceTab === 'flow' && (
                <div className="flex min-h-0 min-w-0 flex-1 flex-col [&>*]:min-h-0">
                  <CollaborationFlowCanvas
                    crewRoles={crewRoles}
                    liveMission={liveMission}
                    selectedScope={activeTab}
                    onSelectScope={(scope) => {
                      setActiveTab(scope);
                      setWorkspaceTab('timeline');
                    }}
                    variant="workspace"
                  />
                </div>
              )}
              {workspaceTab === 'timeline' && (
                <div className="rounded-xl border border-border/50 bg-white p-4 shadow-[0_8px_30px_rgba(15,23,42,0.06)] sm:p-6">
                  {messagesSection}
                </div>
              )}

          </div>
        </div>

        {/* Input Bar Area */}
        <div className="z-10 shrink-0 border-t border-slate-200/90 bg-white px-4 pb-4 pt-2.5 sm:px-6">
          <div className="mx-auto max-w-4xl">
            <p className="mb-1.5 text-[9px] font-black uppercase tracking-[0.22em] text-slate-500">
              User command
            </p>
            {uploadedFiles.length > 0 && (
              <div className="mb-3 flex flex-wrap gap-2">
                {uploadedFiles.map((file, i) => (
                  <div key={i} className="flex items-center gap-2 bg-section-bg border border-border/60 px-3 py-1.5 rounded-xl shadow-sm animate-in slide-in-from-bottom-2 duration-300">
                    <Paperclip size={12} className="text-primary" />
                    <span className="text-[11px] font-bold text-text-primary" title={file.file_id || ''}>
                      {file.filename || (typeof file === 'string' ? file : 'File Attached')}
                    </span>
                    <button onClick={() => setUploadedFiles(prev => prev.filter((_, idx) => idx !== i))} className="text-text-secondary hover:text-red-500 transition-colors"><X size={14} /></button>
                  </div>
                ))}
              </div>
            )}
            
            <p className="mb-2 text-center text-[11px] font-normal text-slate-500 select-none">
              Meridian AI can make mistakes. Check important information.
            </p>

            <div className="relative group">
              <div className="absolute inset-0 rounded-xl bg-primary/5 blur-lg opacity-0 transition-opacity duration-300 group-focus-within:opacity-100"></div>
              <div className="relative flex flex-col overflow-hidden rounded-xl border border-slate-200 bg-white shadow-[0_2px_16px_rgba(15,23,42,0.06)] transition-all duration-300 focus-within:border-primary/40 focus-within:shadow-[0_8px_28px_rgba(29,78,216,0.12)]">
                <textarea 
                  value={input} 
                  onChange={(e) => setInput(e.target.value)} 
                  onKeyDown={handleKeyDown}
                  placeholder={`Direct ${activeAgent.name}…`}
                  className="min-h-[76px] max-h-[220px] w-full resize-y border-none bg-transparent px-4 pb-11 pt-3 text-[13px] font-medium leading-snug text-text-primary outline-none placeholder:text-text-secondary/40 focus:ring-0 sm:min-h-[80px]" 
                ></textarea>
                <div className="absolute bottom-2 left-3 right-3 flex flex-wrap items-center justify-between gap-2">
                  <div className="flex flex-wrap items-center gap-0.5">
                    <button type="button" onClick={() => fileInputRef.current?.click()} className="rounded-lg border border-transparent p-2 text-slate-500 transition-all hover:bg-slate-100 hover:text-primary" title="Attach">
                      <Paperclip size={16} />
                    </button>
                    <input type="file" multiple ref={fileInputRef} onChange={handleFileUpload} className="hidden" />
                    <button type="button" className="rounded-lg border border-transparent p-2 text-slate-500 hover:bg-slate-100 hover:text-primary" title="Data source (preview)">
                      <Database size={16} />
                    </button>
                    <button type="button" className="rounded-lg border border-transparent p-2 text-slate-500 hover:bg-slate-100 hover:text-primary" title="Save draft (preview)">
                      <Bookmark size={16} />
                    </button>
                    <button type="button" className="rounded-lg border border-transparent p-2 text-slate-500 hover:bg-slate-100 hover:text-primary" title="Reasoning mode (preview)">
                      <Brain size={16} />
                    </button>
                  </div>
                  <button 
                    type="button"
                    onClick={handleSend} 
                    disabled={!input.trim() || isProcessing}
                    className="flex items-center gap-2 rounded-xl bg-primary px-4 py-2 font-black text-[10px] uppercase tracking-widest text-white shadow-md shadow-primary/20 transition-all hover:bg-primary-hover disabled:cursor-not-allowed disabled:opacity-25"
                  >
                    <Send size={13} />
                    Execute task
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>
        </div>
      </div>

      {/* ── HANDOFF TOASTS ── */}
      <div
        className={`fixed bottom-24 z-50 flex flex-col gap-3 pointer-events-none transition-[right] duration-300 ease-out ${
          tracePanelOpen ? 'right-[360px]' : 'right-14'
        }`}
      >
        {handoffs.map(toast => (
          <div key={toast.id} className="flex items-center gap-3 bg-slate-900 text-white px-5 py-3 rounded-2xl shadow-2xl border border-white/10 animate-in slide-in-from-right-10 duration-500 max-w-sm pointer-events-auto">
            <div className={`p-2 rounded-xl ${toast.type === 'handoff' ? 'bg-primary/20 text-primary' : 'bg-green-500/20 text-green-400'}`}>
              {toast.type === 'handoff' ? <ArrowRightLeft size={16} /> : <Activity size={16} />}
            </div>
            <div className="flex-1">
              <p className="text-[11px] font-black uppercase tracking-widest opacity-40 mb-0.5">{toast.type}</p>
              <p className="text-[12px] font-bold leading-tight">{toast.text}</p>
            </div>
            <button onClick={() => setHandoffs(prev => prev.filter(t => t.id !== toast.id))} className="p-1 hover:bg-white/10 rounded-lg"><X size={14} /></button>
          </div>
        ))}
      </div>

      {/* ─── RIGHT: collapsible System Trace + activity ───────────────── */}
      {!tracePanelOpen && (
        <button
          type="button"
          onClick={() => setTracePanelOpen(true)}
          className="flex w-11 shrink-0 flex-col items-center gap-3 border-l border-border/60 bg-[#FAFBFC] py-6 shadow-[-6px_0_20px_rgba(0,0,0,0.04)] z-20 transition-colors hover:bg-white group"
          title="Open System Trace"
          aria-expanded="false"
          aria-controls="system-trace-panel"
        >
          <Activity size={18} className="text-primary shrink-0 group-hover:scale-110 transition-transform" />
          <span className="text-[9px] font-black uppercase tracking-[0.15em] text-text-secondary group-hover:text-primary transition-colors [writing-mode:vertical-rl] rotate-180 select-none">
            Trace
          </span>
        </button>
      )}

      <div
        id="system-trace-panel"
        className={`relative flex shrink-0 overflow-hidden border-border/60 transition-[width] duration-300 ease-out z-20 ${
          tracePanelOpen ? 'w-[340px] border-l' : 'w-0 border-l-0'
        }`}
        aria-hidden={!tracePanelOpen}
      >
        <div className="flex h-full min-h-0 w-[340px] flex-col bg-[#FAFBFC]">
          <div className="flex h-[72px] shrink-0 items-center gap-3 border-b border-border/60 bg-white px-6">
            <div className="rounded-xl bg-primary/10 p-2 text-primary shadow-sm">
              <Activity size={18} />
            </div>
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-2">
                <h2 className="font-black text-[13px] uppercase tracking-tight text-text-primary">System Trace</h2>
                {missionRunning && (
                  <span className="rounded-md bg-emerald-50 px-2 py-0.5 text-[8px] font-black uppercase tracking-widest text-emerald-700 ring-1 ring-emerald-100">
                    Live
                  </span>
                )}
              </div>
              <p className="text-[9px] font-bold uppercase tracking-[0.2em] text-text-secondary">Real-time Telemetry</p>
            </div>
            <button
              type="button"
              onClick={() => setTracePanelOpen(false)}
              className="shrink-0 rounded-xl border border-border/60 p-2 text-text-secondary transition-all hover:border-primary/30 hover:bg-section-bg hover:text-primary"
              title="Hide System Trace"
              aria-expanded="true"
              aria-controls="system-trace-panel"
            >
              <ChevronRight size={18} strokeWidth={2.5} />
            </button>
          </div>

          <div className="border-b border-border/40 bg-white px-6 pb-3 pt-0">
            <div className="mb-1 flex items-center justify-between text-[9px] font-black uppercase tracking-widest text-text-secondary">
              <span>Mission progress</span>
              <span className="text-primary">{traceProgressPct}%</span>
            </div>
            <div className="h-2 overflow-hidden rounded-full bg-border/70">
              <div
                className="h-full rounded-full bg-gradient-to-r from-primary to-primary-hover transition-[width] duration-500 ease-out"
                style={{ width: `${traceProgressPct}%` }}
              />
            </div>
          </div>

          <div className="custom-scrollbar flex-1 space-y-8 overflow-y-auto p-6">
            <div className="space-y-6">
              <LiveMissionTrace liveTrace={liveTrace} />

              <div className="my-2 h-px bg-border/40"></div>

              <p className="mb-2 text-[10px] font-black uppercase tracking-widest text-text-primary">Activity log</p>
              {activeActivity.length === 0 && (
                <div className="flex flex-col items-center justify-center py-12 text-center opacity-10">
                  <BrainCircuit size={32} className="mb-4" />
                  <p className="text-[10px] font-black uppercase tracking-[0.3em]">Awaiting Instruction</p>
                </div>
              )}
              <div className="relative space-y-4">
                <div className="absolute bottom-2 left-0 top-2 w-px bg-border/40"></div>
                {activeActivity.map((act, i) => (
                  <div
                    key={act.id}
                    className="group relative animate-in slide-in-from-right-4 duration-500 pl-6"
                    style={{ animationDelay: `${i * 100}ms` }}
                  >
                    <div
                      className={`absolute left-[-3px] top-2 z-10 h-1.5 w-1.5 rounded-full transition-transform group-hover:scale-150 ${
                        act.status === 'processing'
                          ? 'bg-amber-400 shadow-[0_0_10px_rgba(251,191,36,0.8)]'
                          : act.status === 'error'
                            ? 'bg-red-400'
                            : 'bg-primary shadow-[0_0_10px_rgba(29,78,216,0.6)]'
                      }`}
                    ></div>
                    <div className="rounded-2xl border border-border/60 border-l-4 border-l-primary/10 bg-white p-4 shadow-[0_2px_8px_rgba(0,0,0,0.02)] transition-all hover:shadow-md">
                      <div className="mb-2 flex items-center justify-between">
                        <span
                          className={`rounded px-2 py-0.5 text-[8px] font-black uppercase tracking-widest ${
                            act.status === 'processing'
                              ? 'bg-amber-50 text-amber-600'
                              : act.status === 'error'
                                ? 'bg-red-50 text-red-600'
                                : 'bg-primary/5 text-primary'
                          }`}
                        >
                          {act.status}
                        </span>
                        <span className="text-[8px] font-black text-text-secondary/30">{formatTime(act.timestamp)}</span>
                      </div>
                      <p className="text-[12px] font-bold leading-snug tracking-tight text-text-primary">{act.text}</p>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Agent DNA editor — full viewport */}
      {showDetails && (
        <div
          className="fixed inset-0 z-[100] flex flex-col h-[100dvh] w-full bg-white animate-in fade-in duration-300"
          role="dialog"
          aria-modal="true"
          aria-labelledby="agent-dna-editor-title"
        >
          <AgentDNAEditor
            fullScreen
            config={editedConfig}
            onChange={setEditedConfig}
            onCancel={() => setShowDetails(false)}
            onConfirm={async () => {
              try {
                await apiUpdateAgentConfig(activeAgent.id, editedConfig);
                fetchAgents();
                setShowDetails(false);
              } catch (err) {
                alert(err.message);
              }
            }}
          />
        </div>
      )}

      {/* Premium Clear History Confirmation Dialog */}
      {showClearConfirm && (
        <div className="fixed inset-0 z-[110] flex items-center justify-center bg-slate-900/60 p-4 backdrop-blur-sm animate-in fade-in duration-200">
          <div 
            className="w-full max-w-md rounded-2xl border border-slate-100 bg-white p-6 shadow-2xl animate-in zoom-in-95 duration-200"
            role="dialog"
            aria-modal="true"
            aria-labelledby="clear-history-title"
          >
            <div className="flex items-center gap-3.5 border-b border-slate-100 pb-4">
              <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-red-50 text-red-500">
                <AlertTriangle size={20} className="animate-pulse" />
              </div>
              <div>
                <h3 id="clear-history-title" className="text-base font-black text-text-primary">
                  Clear Agent History
                </h3>
                <p className="text-[9px] font-black uppercase tracking-[0.15em] text-red-500/80">
                  Critical Handoff Wipe
                </p>
              </div>
            </div>

            <div className="my-5">
              <p className="text-sm font-semibold leading-relaxed text-text-secondary">
                Are you sure you want to clear <strong className="text-text-primary">{activeAgent.name}</strong>'s complete history?
              </p>
              <div className="mt-3 rounded-xl bg-slate-50 border border-slate-100 p-3.5">
                <p className="text-[11px] font-bold text-text-secondary/70 leading-snug">
                  This will permanently delete all conversation threads, active messages, vector memories, and backend telemetry contexts. <strong>This action cannot be undone.</strong>
                </p>
              </div>
            </div>

            <div className="flex items-center justify-end gap-3 pt-3 border-t border-slate-100">
              <button
                type="button"
                onClick={() => setShowClearConfirm(false)}
                className="rounded-xl border border-slate-200 bg-white px-4.5 py-2.5 text-xs font-bold text-slate-600 hover:bg-slate-50 transition-colors cursor-pointer"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={async () => {
                  try {
                    await clearAgentHistory(activeAgent.id);
                    setThreadId(null);
                    setLastRunTokens(0);
                    setCumulativeTokens(0);
                    setShowClearConfirm(false);
                  } catch (err) {
                    console.error(err);
                  }
                }}
                className="flex items-center gap-2 rounded-xl bg-red-600 px-5 py-2.5 text-xs font-bold text-white hover:bg-red-700 shadow-md shadow-red-600/20 transition-all cursor-pointer"
              >
                <Trash2 size={14} /> Yes, Clear History
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
