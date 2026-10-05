import React, { useState, useEffect, useRef, useMemo } from 'react';
import { 
  Settings, X, CheckCircle2, Plus, Send, ShieldCheck, ShieldAlert, 
  TriangleAlert, RefreshCw, Search, Check, AlertCircle, Wrench
} from 'lucide-react';
import Badge from './Badge';
import { useMcp } from '../context/McpContext';

/** Defensive helper to extract tool metadata from backend builderTool items */
const extractToolMeta = (tool) => {
  if (typeof tool === 'string') {
    return {
      id: tool,
      name: tool,
      rawName: tool,
      version: '1.0.0',
      displayName: tool.replace(/_/g, ' '),
      description: '',
      category: '',
      riskLevel: 'READ',
      requiresApproval: false,
      sourceType: 'native',
      serverName: 'Native',
    };
  }
  const id = tool?.capability_id || tool?.id || tool?.name || '';
  const rawName = tool?.name || id;
  const version = tool?.version || tool?.spec?.version || '1.0.0';
  const displayName = tool?.display_name || tool?.spec?.builder_metadata?.display_name || tool?.spec?.display_name || tool?.name || id.replace(/_/g, ' ');
  const description = tool?.description || tool?.spec?.description || '';
  const category = tool?.category || tool?.spec?.category || '';
  const riskLevel = String(tool?.risk_level || tool?.spec?.risk_level || 'READ').toUpperCase();
  const requiresApproval = Boolean(tool?.requires_approval ?? tool?.spec?.requires_approval);
  const serverName = tool?.server_name || tool?.spec?.builder_metadata?.server_name || tool?.spec?.server_name || (tool?.source_type === 'native' || tool?.spec?.builder_metadata?.source_type === 'native' ? 'Native' : '');
  const sourceType = tool?.source_type || tool?.spec?.builder_metadata?.source_type || (serverName === 'Native' ? 'native' : 'mcp');

  return {
    id,
    name: id,
    rawName,
    version,
    displayName,
    description,
    category,
    riskLevel,
    requiresApproval,
    sourceType,
    serverName,
  };
};

export default function AgentDNAEditor({ config, onChange, onCancel, onConfirm, isNew = false, fullScreen = false }) {
  const { 
    builderTools = [], 
    builderToolsLoading, 
    builderToolsError, 
    fetchBuilderTools 
  } = useMcp();

  const [showAllTools, setShowAllTools] = useState(false);
  const [toolSearch, setToolSearch] = useState('');
  const [isRetrying, setIsRetrying] = useState(false);
  const hasFetchedToolsRef = useRef(false);

  // Safely trigger catalog fetch if not already loaded
  useEffect(() => {
    if (!hasFetchedToolsRef.current && builderTools.length === 0 && !builderToolsLoading && !builderToolsError) {
      hasFetchedToolsRef.current = true;
      fetchBuilderTools().catch(() => {});
    }
  }, [builderTools.length, builderToolsLoading, builderToolsError, fetchBuilderTools]);

  const handleRetryTools = async () => {
    setIsRetrying(true);
    try {
      await fetchBuilderTools();
    } catch (err) {
      console.error('Retry fetching builder tools failed:', err);
    } finally {
      setIsRetrying(false);
    }
  };

  if (!config) return null;

  const shellClass = fullScreen
    ? 'bg-white w-full h-full min-h-0 overflow-hidden flex flex-col rounded-none shadow-none border-0'
    : 'bg-white rounded-[2.5rem] shadow-2xl w-full max-w-2xl overflow-hidden border border-white/20 flex flex-col max-h-[85vh]';

  const updateConfig = (updates) => {
    onChange({ ...config, ...updates });
  };

  const parsedTools = useMemo(() => {
    return (builderTools || []).map(extractToolMeta);
  }, [builderTools]);

  const toolLookupMap = useMemo(() => {
    const map = new Map();
    parsedTools.forEach(t => {
      if (t.id) map.set(t.id, t);
      if (t.rawName) map.set(t.rawName, t);
      if (t.displayName) map.set(t.displayName, t);
      if (t.id) map.set(t.id.toLowerCase(), t);
      if (t.rawName) map.set(t.rawName.toLowerCase(), t);
      if (t.displayName) map.set(t.displayName.toLowerCase(), t);
    });
    return map;
  }, [parsedTools]);

  const canonicalizeToolId = (toolKey) => {
    if (!toolKey) return '';
    const keyStr = String(toolKey).trim();
    const meta = toolLookupMap.get(keyStr) || toolLookupMap.get(keyStr.toLowerCase());
    return meta?.id || keyStr;
  };

  const buildToolRefs = (toolsList) => {
    const canonicalTools = Array.from(new Set((toolsList || []).map(canonicalizeToolId).filter(Boolean)));
    return canonicalTools.map(toolId => {
      const toolMeta = toolLookupMap.get(toolId) || toolLookupMap.get(toolId.toLowerCase());
      return {
        tool_id: toolId,
        version: toolMeta?.version || '1.0.0',
      };
    });
  };

  // Sync tool_refs and canonicalize tools on mount or when catalog/config tools change
  useEffect(() => {
    if (!config) return;
    const currentToolsRaw = Array.isArray(config.tools) ? config.tools : [];
    const canonicalTools = Array.from(new Set(currentToolsRaw.map(canonicalizeToolId).filter(Boolean)));
    
    const currentRefs = Array.isArray(config.tool_refs) ? config.tool_refs : [];
    const currentRefIds = new Set(currentRefs.map(r => r.tool_id));
    const canonicalToolSet = new Set(canonicalTools);
    
    const isToolsSame = currentToolsRaw.length === canonicalTools.length && 
      currentToolsRaw.every((t, i) => t === canonicalTools[i]);
    const isRefsSynced = currentRefIds.size === canonicalToolSet.size && 
      [...canonicalToolSet].every(id => currentRefIds.has(id)) &&
      currentRefs.length === canonicalTools.length;

    if (!isToolsSame || !isRefsSynced) {
      const syncedRefs = buildToolRefs(canonicalTools);
      updateConfig({ 
        tools: canonicalTools,
        tool_refs: syncedRefs 
      });
    }
  }, [parsedTools.length, config?.tools, config?.tool_refs]);

  const filteredTools = useMemo(() => {
    if (!toolSearch.trim()) return parsedTools;
    const q = toolSearch.toLowerCase();
    return parsedTools.filter(t => 
      t.id.toLowerCase().includes(q) ||
      t.displayName.toLowerCase().includes(q) ||
      t.description.toLowerCase().includes(q) ||
      t.serverName.toLowerCase().includes(q) ||
      t.category.toLowerCase().includes(q)
    );
  }, [parsedTools, toolSearch]);

  const handleToggleTool = (toolIdOrName) => {
    const targetId = canonicalizeToolId(toolIdOrName);
    if (!targetId) return;

    const currentTools = Array.from(new Set((config.tools || []).map(canonicalizeToolId).filter(Boolean)));
    const isEnabled = currentTools.includes(targetId);
    const nextTools = isEnabled
      ? currentTools.filter(t => t !== targetId)
      : [...currentTools, targetId];

    let nextRoles = (config.crew_roles || []).map(role => ({
      ...role,
      assigned_tools: (role.assigned_tools || []).map(canonicalizeToolId).filter(t => nextTools.includes(t)),
    }));

    const nextToolRefs = buildToolRefs(nextTools);
    
    // Clean up governance for deselected tool
    const nextGovernance = { ...(config.tool_governance || {}) };
    if (isEnabled && nextGovernance[targetId]) {
      delete nextGovernance[targetId];
    }

    updateConfig({
      tools: nextTools,
      tool_refs: nextToolRefs,
      crew_roles: nextRoles,
      tool_governance: nextGovernance,
    });
  };

  const handleSelectAll = () => {
    const allIds = Array.from(new Set(parsedTools.map(t => t.id).filter(Boolean)));
    const nextToolRefs = buildToolRefs(allIds);
    updateConfig({ tools: allIds, tool_refs: nextToolRefs });
  };

  const handleClearAll = () => {
    const nextRoles = (config.crew_roles || []).map(role => ({
      ...role,
      assigned_tools: [],
    }));
    updateConfig({ tools: [], tool_refs: [], tool_governance: {}, crew_roles: nextRoles });
  };

  return (
    <div className={shellClass}>
      {/* Header */}
      <div className="px-8 py-6 border-b border-border/60 flex items-center justify-between bg-section-bg/30 shrink-0">
        <div className="flex items-center gap-3">
          <Settings size={20} className="text-primary" />
          <h3 id="agent-dna-editor-title" className="font-black text-text-primary text-[11px] uppercase tracking-[0.2em]">
            {isNew ? 'Review Agent DNA' : 'Agent DNA Configuration'}
          </h3>
        </div>
        {onCancel && (
          <button onClick={onCancel} className="p-2.5 hover:bg-white rounded-xl transition-all shadow-sm border border-transparent hover:border-border/60">
            <X size={20} />
          </button>
        )}
      </div>

      {/* Content */}
      <div className={`flex-1 p-10 space-y-10 overflow-y-auto custom-scrollbar min-h-0 ${fullScreen ? 'pb-4' : ''}`}>
        <div className="flex items-center gap-6">
          <div className="w-20 h-20 bg-primary/5 rounded-[2rem] flex items-center justify-center text-primary font-black text-3xl border-2 border-primary/10 shadow-inner">
            {config.name?.charAt(0).toUpperCase()}
          </div>
          <div>
            <h4 className="font-black text-text-primary text-2xl tracking-tighter">{config.name}</h4>
            <div className="flex items-center gap-2.5 mt-2">
              <Badge variant="primary" className="text-[10px] px-3 py-1 uppercase font-black tracking-widest">DNA EXPERT MODE</Badge>
              <Badge variant="secondary" className="text-[10px] px-3 py-1 uppercase font-black tracking-widest bg-white border border-amber-200 text-amber-600">
                Stage: Reviewing Blueprint
              </Badge>
            </div>
          </div>
        </div>

        <div className="space-y-8">
          <div className="p-8 bg-section-bg rounded-[2rem] space-y-8 border border-border/40">
            
            {/* AGENT NAME (Editable in preview) */}
            <div className="space-y-4">
              <label className="text-[10px] font-black text-text-primary uppercase tracking-[0.2em] border-l-4 border-primary pl-3">Display Name</label>
              <input 
                value={config.name || ""}
                onChange={(e) => updateConfig({ name: e.target.value })}
                className="w-full bg-white border border-border rounded-2xl p-4 text-sm font-bold text-text-primary focus:ring-4 focus:ring-primary/5 focus:border-primary/40 outline-none transition-all shadow-sm"
              />
            </div>

            {/* EMAIL STRATEGY */}
            <div className="space-y-4">
              <label className="text-[10px] font-black text-text-primary uppercase tracking-[0.2em] border-l-4 border-primary pl-3">Email Dispatch Strategy</label>
              <select 
                value={config.executor_policy?.email_strategy || 'auto'}
                onChange={(e) => updateConfig({
                  executor_policy: { ...config.executor_policy, email_strategy: e.target.value }
                })}
                className="w-full bg-white border border-border rounded-2xl p-4 text-sm font-bold text-text-primary focus:ring-4 focus:ring-primary/5 focus:border-primary/40 outline-none transition-all shadow-sm"
              >
                <option value="auto">Auto-Determine (Context Aware)</option>
                <option value="broadcast">Broadcast (Multi-Recipient)</option>
                <option value="winner_only">Selective (Targeted Result)</option>
              </select>
            </div>

            {/* GLOBAL TOOLKIT */}
            <div className="space-y-4">
              <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                <div className="flex items-center gap-3">
                  <label className="text-[10px] font-black text-text-primary uppercase tracking-[0.2em] border-l-4 border-primary pl-3">
                    Active Toolkit
                  </label>
                  <div className="px-2.5 py-1 bg-primary/10 rounded-md border border-primary/20 text-[9px] font-black text-primary uppercase">
                    {(config.tools || []).length} / {parsedTools.length} Tools Enabled
                  </div>
                </div>
                
                <div className="flex items-center gap-2">
                  {showAllTools && parsedTools.length > 0 && (
                    <>
                      <button
                        type="button"
                        onClick={handleSelectAll}
                        className="text-[9px] font-bold uppercase tracking-wider text-text-secondary hover:text-primary px-2.5 py-1 rounded-lg border border-border/60 hover:border-primary/30 transition-all"
                      >
                        Select All
                      </button>
                      <button
                        type="button"
                        onClick={handleClearAll}
                        className="text-[9px] font-bold uppercase tracking-wider text-text-secondary hover:text-red-500 px-2.5 py-1 rounded-lg border border-border/60 hover:border-red-300 transition-all"
                      >
                        Clear All
                      </button>
                    </>
                  )}

                  <button 
                    type="button"
                    onClick={() => setShowAllTools(!showAllTools)} 
                    className={`text-[9px] font-black uppercase transition-all flex items-center gap-1.5 px-3 py-1.5 rounded-lg border ${
                      showAllTools 
                        ? 'bg-slate-900 text-white border-slate-900 shadow-sm' 
                        : 'text-primary border-primary/20 hover:bg-primary/5'
                    }`}
                  >
                    <Plus size={12} className={showAllTools ? 'rotate-45 transition-transform' : 'transition-transform'} />
                    {showAllTools ? "Collapse Library" : "Expand Library"}
                  </button>
                </div>
              </div>
              
              <div className="p-6 bg-white border border-border/60 rounded-2xl space-y-4 shadow-sm">
                {/* Loading State */}
                {(builderToolsLoading || isRetrying) && parsedTools.length === 0 && (
                  <div className="space-y-3 py-4">
                    <div className="flex items-center justify-center gap-2 text-text-secondary/60 text-xs font-bold uppercase tracking-wider mb-2">
                      <RefreshCw size={14} className="animate-spin text-primary" />
                      Loading backend tool catalog...
                    </div>
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                      {[1, 2, 3, 4].map(n => (
                        <div key={n} className="p-4 rounded-xl border border-border/40 bg-section-bg/30 animate-pulse space-y-2.5">
                          <div className="h-4 bg-slate-200 rounded w-1/2"></div>
                          <div className="h-3 bg-slate-100 rounded w-3/4"></div>
                          <div className="flex gap-2 pt-1">
                            <div className="h-4 bg-slate-200 rounded w-12"></div>
                            <div className="h-4 bg-slate-200 rounded w-16"></div>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Error State (e.g. 503 Service Unavailable) */}
                {!builderToolsLoading && !isRetrying && builderToolsError && parsedTools.length === 0 && (
                  <div className="p-5 bg-amber-50/70 border border-amber-200 rounded-xl space-y-3 text-left">
                    <div className="flex items-start gap-3">
                      <AlertCircle size={18} className="text-amber-600 shrink-0 mt-0.5" />
                      <div className="flex-1 space-y-1">
                        <h5 className="text-xs font-black uppercase tracking-wider text-amber-900">
                          Unable to load available tools
                        </h5>
                        <p className="text-xs text-amber-700 font-medium">
                          {builderToolsError.includes('503') 
                            ? 'The capability subsystem is currently unavailable (503). You may retry to connect to the backend catalog.'
                            : builderToolsError}
                        </p>
                      </div>
                    </div>
                    <div className="flex justify-end pt-1">
                      <button
                        type="button"
                        onClick={handleRetryTools}
                        disabled={isRetrying}
                        className="flex items-center gap-1.5 px-3 py-1.5 bg-amber-600 hover:bg-amber-700 text-white rounded-lg text-xs font-bold uppercase tracking-wider shadow-sm transition-all active:scale-95 disabled:opacity-50"
                      >
                        <RefreshCw size={12} className={isRetrying ? 'animate-spin' : ''} />
                        Retry
                      </button>
                    </div>
                  </div>
                )}

                {/* Empty State */}
                {!builderToolsLoading && !isRetrying && !builderToolsError && parsedTools.length === 0 && (
                  <div className="text-center py-8 space-y-2">
                    <Wrench size={24} className="mx-auto text-text-secondary/30" />
                    <p className="text-xs font-bold text-text-secondary/60 uppercase tracking-widest">
                      No tools are currently available.
                    </p>
                  </div>
                )}

                {/* Compact View (When library is collapsed) */}
                {!showAllTools && parsedTools.length > 0 && (
                  <div>
                    {(config.tools || []).length === 0 ? (
                      <div className="text-center py-6 space-y-2">
                        <p className="text-xs text-text-secondary/50 font-bold uppercase tracking-wider">
                          No tools assigned to this agent yet.
                        </p>
                        <button
                          type="button"
                          onClick={() => setShowAllTools(true)}
                          className="text-xs font-black text-primary hover:underline uppercase tracking-wide inline-flex items-center gap-1"
                        >
                          <Plus size={12} /> Open Library to Add Tools
                        </button>
                      </div>
                    ) : (
                      <div className="flex flex-wrap gap-2">
                        {(config.tools || []).map(toolItem => {
                          const toolId = canonicalizeToolId(toolItem);
                          const meta = toolLookupMap.get(toolId) || extractToolMeta(toolId);
                          const assignedRoles = (config.crew_roles || []).filter(role => 
                            (role.assigned_tools || []).map(canonicalizeToolId).includes(toolId)
                          );
                          const isAssigned = assignedRoles.length > 0;
                          const isOrphaned = !isAssigned;

                          return (
                            <div 
                              key={toolId}
                              className={`group relative inline-flex items-center gap-2 px-3 py-2 rounded-xl text-[10px] font-black uppercase tracking-tight border transition-all ${
                                isAssigned 
                                  ? 'bg-primary/5 text-primary border-primary/20 shadow-sm' 
                                  : 'bg-amber-50 text-amber-700 border-amber-200'
                              }`}
                            >
                              <span className="font-bold">{meta.displayName}</span>
                              {meta.serverName && (
                                <span className={`text-[8px] px-1.5 py-0.5 rounded font-bold ${
                                  meta.serverName === 'Native'
                                    ? 'bg-slate-100 text-slate-700'
                                    : 'bg-blue-100 text-blue-700'
                                }`}>
                                  {meta.serverName}
                                </span>
                              )}
                              {meta.riskLevel && (
                                <span className={`text-[8px] px-1.5 py-0.5 rounded font-bold ${
                                  meta.riskLevel === 'READ' ? 'bg-emerald-100 text-emerald-700' :
                                  meta.riskLevel === 'WRITE' ? 'bg-amber-100 text-amber-700' :
                                  'bg-rose-100 text-rose-700'
                                }`}>
                                  {meta.riskLevel}
                                </span>
                              )}
                              {meta.requiresApproval && (
                                <span className="text-[8px] px-1.5 py-0.5 rounded bg-purple-100 text-purple-700 font-bold flex items-center gap-0.5">
                                  <ShieldAlert size={8} /> Approval Required
                                </span>
                              )}

                              {isAssigned && (
                                <span className="px-1.5 py-0.5 bg-primary/20 rounded-md text-[8px] font-bold text-primary" title={`Assigned to ${assignedRoles.length} sub-agent(s)`}>
                                  {assignedRoles.length}
                                </span>
                              )}

                              {isOrphaned && (
                                <div className="relative flex items-center">
                                  <TriangleAlert size={12} className="text-amber-500 animate-pulse" />
                                  <div className="absolute bottom-full mb-2 left-1/2 -translate-x-1/2 w-48 p-2.5 bg-slate-900 text-white text-[9px] rounded-lg opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none z-[60] shadow-xl text-center font-bold">
                                    Enabled globally but not assigned to any sub-agent.
                                  </div>
                                </div>
                              )}

                              <button
                                type="button"
                                onClick={() => handleToggleTool(toolId)}
                                className="p-0.5 text-text-secondary/40 hover:text-red-500 transition-colors ml-1"
                                title="Remove from agent"
                              >
                                <X size={12} />
                              </button>
                            </div>
                          );
                        })}
                      </div>
                    )}
                  </div>
                )}

                {/* Expanded Library View */}
                {showAllTools && parsedTools.length > 0 && (
                  <div className="space-y-4">
                    {/* Search Filter */}
                    <div className="relative">
                      <Search size={14} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-text-secondary/40" />
                      <input
                        type="text"
                        placeholder="Search tools by name, description, server or category..."
                        value={toolSearch}
                        onChange={(e) => setToolSearch(e.target.value)}
                        className="w-full bg-section-bg/40 border border-border/60 rounded-xl pl-9 pr-8 py-2.5 text-xs font-bold text-text-primary placeholder:text-text-secondary/30 focus:outline-none focus:ring-2 focus:ring-primary/20 transition-all"
                      />
                      {toolSearch && (
                        <button
                          type="button"
                          onClick={() => setToolSearch('')}
                          className="absolute right-3 top-1/2 -translate-y-1/2 text-text-secondary/40 hover:text-text-primary p-0.5"
                        >
                          <X size={12} />
                        </button>
                      )}
                    </div>

                    {/* Dynamic Tool Grid */}
                    {filteredTools.length === 0 ? (
                      <p className="text-xs text-text-secondary/40 font-bold uppercase tracking-wider text-center py-6">
                        No tools match your search.
                      </p>
                    ) : (
                      <div className="grid grid-cols-1 md:grid-cols-2 gap-3 max-h-[380px] overflow-y-auto custom-scrollbar pr-1">
                        {filteredTools.map(tool => {
                          const toolId = tool.id;
                          const isEnabled = (config.tools || []).map(canonicalizeToolId).includes(toolId);
                          const assignedRoles = (config.crew_roles || []).filter(role => 
                            (role.assigned_tools || []).map(canonicalizeToolId).includes(toolId)
                          );
                          const isAssigned = assignedRoles.length > 0;
                          const isOrphaned = isEnabled && !isAssigned;

                          return (
                            <div
                              key={toolId}
                              onClick={() => handleToggleTool(toolId)}
                              className={`p-4 rounded-xl border text-left cursor-pointer transition-all duration-200 select-none flex flex-col justify-between gap-2.5 ${
                                isEnabled
                                  ? 'bg-primary/[0.03] border-primary/40 shadow-sm ring-1 ring-primary/20'
                                  : 'bg-white border-border/60 hover:border-primary/30 hover:bg-slate-50/50'
                              }`}
                            >
                              <div className="flex items-start justify-between gap-2">
                                <div className="space-y-0.5 flex-1 min-w-0">
                                  <div className="flex items-center gap-1.5 flex-wrap">
                                    <span className="text-xs font-black text-text-primary truncate">
                                      {tool.displayName}
                                    </span>
                                    {isOrphaned && (
                                      <span className="inline-flex items-center gap-1 text-[8px] font-black uppercase px-1.5 py-0.5 rounded bg-amber-50 text-amber-700 border border-amber-200" title="Enabled but not assigned to any sub-agent">
                                        <TriangleAlert size={8} /> Unassigned
                                      </span>
                                    )}
                                  </div>
                                  <div className="text-[10px] font-mono text-text-secondary/60 truncate">
                                    {tool.id}
                                  </div>
                                </div>

                                <div className={`w-4 h-4 rounded-md border flex items-center justify-center shrink-0 transition-colors ${
                                  isEnabled ? 'bg-primary border-primary text-white' : 'border-border/80 bg-white'
                                }`}>
                                  {isEnabled && <Check size={12} strokeWidth={3} />}
                                </div>
                              </div>

                              {tool.description && (
                                <p className="text-[11px] text-text-secondary/80 font-medium line-clamp-2 leading-relaxed">
                                  {tool.description}
                                </p>
                              )}

                              <div className="flex items-center gap-1.5 flex-wrap pt-1 border-t border-border/30">
                                {/* Source Badge */}
                                {tool.serverName && (
                                  <span className={`text-[9px] font-black uppercase px-2 py-0.5 rounded border ${
                                    tool.serverName === 'Native'
                                      ? 'bg-slate-100 text-slate-700 border-slate-200'
                                      : 'bg-blue-50 text-blue-700 border-blue-200'
                                  }`}>
                                    Source: {tool.serverName}
                                  </span>
                                )}

                                {/* Risk Level Badge */}
                                {tool.riskLevel && (
                                  <span className={`text-[9px] font-black uppercase px-2 py-0.5 rounded border ${
                                    tool.riskLevel === 'READ' ? 'bg-emerald-50 text-emerald-700 border-emerald-200' :
                                    tool.riskLevel === 'WRITE' ? 'bg-amber-50 text-amber-700 border-amber-200' :
                                    'bg-rose-50 text-rose-700 border-rose-200'
                                  }`}>
                                    {tool.riskLevel}
                                  </span>
                                )}

                                {/* Approval Required Badge */}
                                {tool.requiresApproval && (
                                  <span className="text-[9px] font-black uppercase px-2 py-0.5 rounded bg-purple-50 text-purple-700 border border-purple-200 flex items-center gap-1">
                                    <ShieldAlert size={9} /> Approval Required
                                  </span>
                                )}

                                {/* Category */}
                                {tool.category && (
                                  <span className="text-[9px] font-bold text-text-secondary/50 uppercase ml-auto">
                                    {tool.category}
                                  </span>
                                )}
                              </div>
                            </div>
                          );
                        })}
                      </div>
                    )}
                  </div>
                )}
              </div>
            </div>

            {/* CORE MISSION */}
            <div className="space-y-4">
              <label className="text-[10px] font-black text-text-primary uppercase tracking-[0.2em] border-l-4 border-primary pl-3">Core Mission (System Prompt)</label>
              <textarea 
                value={config.system_prompt || ""}
                onChange={(e) => updateConfig({ system_prompt: e.target.value })}
                className="w-full bg-white border border-border rounded-2xl p-4 text-sm font-medium text-text-primary focus:ring-4 focus:ring-primary/5 focus:border-primary/40 outline-none transition-all shadow-sm min-h-[120px]"
                placeholder="Define the core persona and overarching rules for this agent..."
              />
            </div>

            {/* WORKFORCE MANAGEMENT */}
            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <label className="text-[10px] font-black text-text-primary uppercase tracking-[0.2em] border-l-4 border-primary pl-3">Workforce Composition (Sub-Agents)</label>
                <button 
                  onClick={() => {
                    const next = [...(config.crew_roles || [])];
                    next.push({ role: "New Agent", goal: "Complete sub-tasks", backstory: "Persona prompt...", assigned_tools: [] });
                    updateConfig({ crew_roles: next });
                  }}
                  className="flex items-center gap-1.5 px-3 py-1.5 bg-primary/5 border border-primary/10 rounded-xl text-[9px] font-black uppercase text-primary hover:bg-white transition-all shadow-sm"
                >
                  <Plus size={12} /> Recruit
                </button>
              </div>
              <div className="space-y-4">
                {(config.crew_roles || []).map((sub, idx) => (
                  <div key={idx} className="bg-white border border-border/60 rounded-2xl p-6 space-y-4 shadow-sm hover:shadow-md transition-all">
                    <div className="flex items-center justify-between">
                      <input 
                        value={sub.role}
                        onChange={(e) => {
                          const next = [...config.crew_roles];
                          next[idx] = { ...next[idx], role: e.target.value };
                          updateConfig({ crew_roles: next });
                        }}
                        className="bg-transparent border-none text-sm font-black text-primary p-0 focus:ring-0 w-full"
                        placeholder="Agent Role"
                      />
                      <button onClick={() => {
                        const next = config.crew_roles.filter((_, i) => i !== idx);
                        updateConfig({ crew_roles: next });
                      }} className="text-text-secondary hover:text-red-500 transition-colors p-1"><X size={14} /></button>
                    </div>
                    <div className="space-y-2">
                      <label className="text-[9px] font-black text-text-secondary/40 uppercase tracking-widest">Primary Goal</label>
                      <input 
                        value={sub.goal}
                        onChange={(e) => {
                          const next = [...config.crew_roles];
                          next[idx] = { ...next[idx], goal: e.target.value };
                          updateConfig({ crew_roles: next });
                        }}
                        className="w-full bg-section-bg/50 border border-border/40 rounded-xl px-3 py-2 text-xs font-bold text-text-primary focus:ring-2 focus:ring-primary/10 outline-none"
                      />
                    </div>
                    <div className="space-y-2">
                      <label className="text-[9px] font-black text-text-secondary/40 uppercase tracking-widest">Backstory & Instructions</label>
                      <textarea 
                        value={sub.backstory}
                        onChange={(e) => {
                          const next = [...config.crew_roles];
                          next[idx] = { ...next[idx], backstory: e.target.value };
                          updateConfig({ crew_roles: next });
                        }}
                        className="w-full bg-section-bg/50 border border-border/40 rounded-xl px-3 py-2 text-xs font-medium text-text-primary focus:ring-2 focus:ring-primary/10 outline-none min-h-[80px]"
                      />
                    </div>
                    
                    {(sub.assigned_tools || []).includes('send_email') && (
                      <div className="space-y-2 p-4 bg-primary/5 rounded-xl border border-primary/10">
                        <label className="text-[9px] font-black text-primary uppercase tracking-widest flex items-center gap-2">
                          <Send size={10} /> Role Communication Protocol
                        </label>
                        <textarea 
                          placeholder="Email drafting instructions..."
                          value={sub.communication_protocol || ""}
                          onChange={(e) => {
                            const next = [...config.crew_roles];
                            next[idx] = { ...next[idx], communication_protocol: e.target.value };
                            updateConfig({ crew_roles: next });
                          }}
                          className="w-full bg-white border border-primary/20 rounded-xl px-3 py-2 text-xs font-medium text-text-primary focus:ring-2 focus:ring-primary/10 outline-none min-h-[60px]"
                        />
                      </div>
                    )}

                    <div className="space-y-2">
                      <label className="text-[9px] font-black text-text-secondary/40 uppercase tracking-widest">Assigned Permissions</label>
                      <div className="flex flex-wrap gap-1.5">
                        {(config.tools || []).map(toolItem => {
                          const toolId = canonicalizeToolId(toolItem);
                          const isAssigned = (sub.assigned_tools || []).map(canonicalizeToolId).includes(toolId);
                          const meta = toolLookupMap.get(toolId) || extractToolMeta(toolId);
                          return (
                            <button 
                              key={toolId}
                              type="button"
                              onClick={() => {
                                const nextRoles = [...(config.crew_roles || [])];
                                const currentAssigned = (sub.assigned_tools || []).map(canonicalizeToolId);
                                const isAssignedNow = currentAssigned.includes(toolId);
                                const nextAssigned = isAssignedNow 
                                  ? currentAssigned.filter(t => t !== toolId) 
                                  : [...currentAssigned, toolId];
                                
                                nextRoles[idx] = { ...sub, assigned_tools: nextAssigned };

                                const currentTools = Array.from(new Set((config.tools || []).map(canonicalizeToolId).filter(Boolean)));
                                const nextTools = isAssignedNow 
                                  ? currentTools 
                                  : Array.from(new Set([...currentTools, toolId]));

                                const nextToolRefs = buildToolRefs(nextTools);

                                updateConfig({ 
                                  crew_roles: nextRoles,
                                  tools: nextTools,
                                  tool_refs: nextToolRefs,
                                });
                              }}
                              className={`px-2.5 py-1.5 rounded-xl text-[9px] font-black uppercase border transition-all duration-300 hover:scale-105 active:scale-95 ${
                                isAssigned 
                                  ? 'bg-primary/10 text-primary border-primary/20 shadow-sm' 
                                  : 'bg-section-bg text-text-secondary/30 border-transparent hover:border-primary/20'
                              }`}
                              title={meta.displayName || toolId}
                            >
                              {meta.displayName || toolId.split('_')[0]}
                            </button>
                          );
                        })}
                      </div>
                    </div>
                  </div>
                ))}
                <button onClick={() => {
                  const next = [...(config.crew_roles || [])];
                  next.push({ role: "New Agent", goal: "Complete sub-tasks", backstory: "Persona prompt...", assigned_tools: [] });
                  updateConfig({ crew_roles: next });
                }} className="w-full py-4 border-2 border-dashed border-border/60 rounded-2xl text-[11px] font-black uppercase text-primary hover:bg-white transition-all flex items-center justify-center gap-3">
                  <Plus size={16} /> Recruit New Sub-Agent
                </button>
              </div>
            </div>

            {/* COMPLIANCE AUDIT */}
            <div className="space-y-4">
              <label className="text-[10px] font-black text-text-primary uppercase tracking-[0.2em] border-l-4 border-primary pl-3">Compliance Audit Rules</label>
              <div className="space-y-3">
                {(config.validator_config?.checklist || []).map((item, i) => (
                  <div key={i} className="flex items-center gap-4 bg-white border border-border/40 p-4 rounded-2xl text-[13px] font-bold text-text-primary shadow-sm">
                    <CheckCircle2 size={16} className="text-primary" />
                    <span className="flex-1">{item}</span>
                    <button onClick={() => {
                      const next = config.validator_config.checklist.filter((_, idx) => idx !== i);
                      updateConfig({ validator_config: { ...config.validator_config, checklist: next } });
                    }} className="text-text-secondary hover:text-red-500"><X size={14} /></button>
                  </div>
                ))}
                <button onClick={() => {
                  const newItem = prompt('New audit rule:');
                  if (newItem) {
                    const current = config.validator_config.checklist || [];
                    updateConfig({ validator_config: { ...config.validator_config, checklist: [...current, newItem] } });
                  }
                }} className="w-full py-4 border-2 border-dashed border-border/60 rounded-2xl text-[11px] font-black uppercase text-primary hover:bg-white transition-all flex items-center justify-center gap-3 shadow-sm">
                  <Plus size={16} /> Add Compliance Rule
                </button>
              </div>

              {/* VALIDATOR THRESHOLD */}
              <div className="mt-8 p-6 bg-section-bg/50 rounded-2xl border border-border/40 space-y-4">
                <div className="flex items-center justify-between">
                  <label className="text-[10px] font-black text-text-primary uppercase tracking-widest">Validator Precision</label>
                  <Badge variant="primary" className="text-[12px] px-3 py-1 font-black shadow-lg shadow-primary/20">
                    {(config.validator_config?.min_score * 100).toFixed(0)}%
                  </Badge>
                </div>
                <input 
                  type="range"
                  min="0.1"
                  max="1.0"
                  step="0.05"
                  value={config.validator_config?.min_score || 0.5}
                  onChange={(e) => {
                    updateConfig({
                      validator_config: {
                        ...config.validator_config,
                        min_score: parseFloat(e.target.value)
                      }
                    });
                  }}
                  className="w-full h-1.5 bg-border/60 rounded-lg appearance-none cursor-pointer accent-primary"
                />
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Footer */}
      <div className="px-10 py-8 bg-white border-t border-border/60 flex items-center justify-between shrink-0">
        {onCancel && (
          <button onClick={onCancel} className="text-[11px] font-black uppercase tracking-widest text-text-secondary hover:text-text-primary transition-colors">
            Discard
          </button>
        )}
        <button 
          onClick={onConfirm}
          className="bg-primary hover:bg-primary-hover text-white rounded-2xl px-12 py-4 font-black uppercase tracking-widest text-[11px] shadow-xl shadow-primary/20 transition-all hover:scale-105 active:scale-95"
        >
          {isNew ? 'Confirm & Deploy Agent' : 'Save Changes'}
        </button>
      </div>
    </div>
  );
}
