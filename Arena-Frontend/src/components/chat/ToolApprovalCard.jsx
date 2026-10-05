import React, { useState, useEffect } from 'react';
import { 
  ShieldAlert, ShieldCheck, Check, X, AlertTriangle, 
  Loader2, Clock, Wrench, ChevronDown, ChevronUp 
} from 'lucide-react';
import { apiGetToolExecution } from '../../services/mcp.api';
import { useMcp } from '../../context/McpContext';

export default function ToolApprovalCard({
  executionId,
  initialToolName = '',
  initialRiskLevel = '',
  onApprove,
  onReject,
  disabled = false,
}) {
  const { builderTools = [] } = useMcp();
  const [execution, setExecution] = useState(null);
  const [loading, setLoading] = useState(false);
  const [actionState, setActionState] = useState(null); // 'approving' | 'rejecting' | 'done'
  const [error, setError] = useState(null);
  const [showReasonInput, setShowReasonInput] = useState(false);
  const [reason, setReason] = useState('');

  // Fetch execution metadata on mount
  useEffect(() => {
    let isMounted = true;
    if (!executionId) return;

    setLoading(true);
    setError(null);
    apiGetToolExecution(executionId)
      .then((data) => {
        if (isMounted) setExecution(data);
      })
      .catch((err) => {
        if (isMounted) {
          console.warn('Failed to load tool execution metadata:', err?.message);
          // Non-fatal if we already have initial props
        }
      })
      .finally(() => {
        if (isMounted) setLoading(false);
      });

    return () => {
      isMounted = false;
    };
  }, [executionId]);

  const toolId = execution?.tool_ref?.tool_id || initialToolName || 'Unknown Tool';
  const matchingCatalogTool = builderTools.find(
    (t) => (t.name === toolId || t.capability_id === toolId || t.id === toolId)
  );

  const displayName =
    matchingCatalogTool?.display_name ||
    matchingCatalogTool?.name ||
    toolId.replace(/_/g, ' ');

  const description =
    matchingCatalogTool?.description ||
    matchingCatalogTool?.spec?.description ||
    '';

  const rawRisk =
    matchingCatalogTool?.risk_level ||
    matchingCatalogTool?.spec?.risk_level ||
    initialRiskLevel ||
    'WRITE';

  const riskLevel = String(rawRisk).toUpperCase();

  const serverName =
    matchingCatalogTool?.server_name ||
    matchingCatalogTool?.spec?.builder_metadata?.server_name ||
    (matchingCatalogTool?.source_type === 'native' ? 'Native' : '');

  const expiresAt = execution?.approval?.expires_at;
  const isExpired = expiresAt ? new Date(expiresAt) < new Date() : false;

  const isBusy = actionState === 'approving' || actionState === 'rejecting' || disabled;

  const handleApprove = async () => {
    if (isBusy || isExpired) return;
    setActionState('approving');
    setError(null);
    try {
      if (onApprove) {
        await onApprove(executionId);
      }
      setActionState('done');
    } catch (err) {
      console.error('Approval failed:', err);
      setError(err?.message || 'Failed to submit approval.');
      setActionState(null);
    }
  };

  const handleReject = async () => {
    if (isBusy) return;
    if (!showReasonInput) {
      setShowReasonInput(true);
      return;
    }
    setActionState('rejecting');
    setError(null);
    try {
      if (onReject) {
        await onReject(executionId, reason.trim() || undefined);
      }
      setActionState('done');
    } catch (err) {
      console.error('Rejection failed:', err);
      setError(err?.message || 'Failed to submit rejection.');
      setActionState(null);
    }
  };

  if (actionState === 'done') {
    return (
      <div className="mt-3 p-4 rounded-2xl bg-slate-50 border border-slate-200 text-xs font-medium text-slate-600 flex items-center gap-2">
        <Check size={14} className="text-slate-500" />
        <span>Decision submitted for execution <code className="font-mono text-[10px]">{executionId}</code>.</span>
      </div>
    );
  }

  return (
    <div className="mt-3 w-full max-w-xl rounded-2xl border border-amber-200/90 bg-gradient-to-b from-amber-50/70 to-white p-5 shadow-sm space-y-4 animate-in fade-in zoom-in-95 duration-200 text-left">
      {/* Header */}
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-2.5">
          <div className="w-8 h-8 rounded-xl bg-amber-100 text-amber-700 flex items-center justify-center shrink-0 shadow-sm border border-amber-200">
            <ShieldAlert size={16} />
          </div>
          <div>
            <div className="text-[10px] font-black uppercase tracking-[0.15em] text-amber-800">
              Tool Approval Required
            </div>
            <h4 className="text-sm font-bold text-slate-900 leading-tight">
              The agent wants to execute: <span className="font-black text-primary">{displayName}</span>
            </h4>
          </div>
        </div>

        {/* Risk Badge */}
        <span
          className={`shrink-0 text-[9px] font-black uppercase px-2 py-0.5 rounded-md border ${
            riskLevel === 'DESTRUCTIVE'
              ? 'bg-rose-50 text-rose-700 border-rose-200'
              : riskLevel === 'WRITE'
              ? 'bg-amber-50 text-amber-800 border-amber-200'
              : 'bg-emerald-50 text-emerald-700 border-emerald-200'
          }`}
        >
          {riskLevel} Risk
        </span>
      </div>

      {/* Metadata Chips */}
      <div className="flex items-center gap-2 flex-wrap text-[10px] font-medium text-slate-600">
        <span className="font-mono bg-slate-100 px-2 py-0.5 rounded text-slate-700 border border-slate-200">
          {toolId}
        </span>
        {serverName && (
          <span className="bg-blue-50 text-blue-700 px-2 py-0.5 rounded border border-blue-200 font-bold">
            Source: {serverName}
          </span>
        )}
        {expiresAt && (
          <span className="flex items-center gap-1 text-slate-500">
            <Clock size={11} /> Expires in 15m
          </span>
        )}
      </div>

      {/* Description */}
      {description && (
        <p className="text-xs text-slate-600 leading-relaxed bg-white/70 p-3 rounded-xl border border-amber-100">
          {description}
        </p>
      )}

      {/* Optional Rejection Reason */}
      {showReasonInput && (
        <div className="space-y-1.5 pt-1">
          <label className="text-[10px] font-bold uppercase text-slate-600 tracking-wider">
            Rejection Reason (Optional)
          </label>
          <input
            type="text"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder="e.g. Operation not permitted at this time..."
            disabled={isBusy}
            className="w-full bg-white border border-slate-300 rounded-xl px-3 py-2 text-xs text-slate-900 focus:outline-none focus:ring-2 focus:ring-amber-500/20 transition-all placeholder:text-slate-400"
          />
        </div>
      )}

      {/* Error Banner */}
      {error && (
        <div className="p-3 bg-red-50 border border-red-200 rounded-xl text-xs text-red-700 font-medium flex items-center gap-2">
          <AlertTriangle size={14} className="shrink-0 text-red-600" />
          <span>{error}</span>
        </div>
      )}

      {/* Expired Banner */}
      {isExpired && (
        <div className="p-3 bg-slate-100 border border-slate-200 rounded-xl text-xs text-slate-600 font-medium flex items-center gap-2">
          <Clock size={14} className="shrink-0 text-slate-500" />
          <span>This approval request has expired. Please instruct the agent again.</span>
        </div>
      )}

      {/* Action Buttons */}
      {!isExpired && (
        <div className="flex items-center justify-end gap-2 pt-2 border-t border-amber-200/50">
          <button
            type="button"
            onClick={handleReject}
            disabled={isBusy}
            className="flex items-center gap-1.5 px-4 py-2 rounded-xl text-xs font-bold uppercase tracking-wider text-rose-700 bg-rose-50 hover:bg-rose-100 border border-rose-200 transition-all active:scale-95 disabled:opacity-50"
          >
            {actionState === 'rejecting' ? (
              <Loader2 size={13} className="animate-spin" />
            ) : (
              <X size={13} />
            )}
            {showReasonInput ? 'Confirm Reject' : 'Reject'}
          </button>

          <button
            type="button"
            onClick={handleApprove}
            disabled={isBusy}
            className="flex items-center gap-1.5 px-5 py-2 rounded-xl text-xs font-bold uppercase tracking-wider text-white bg-emerald-600 hover:bg-emerald-700 shadow-sm shadow-emerald-600/20 transition-all active:scale-95 disabled:opacity-50"
          >
            {actionState === 'approving' ? (
              <Loader2 size={13} className="animate-spin" />
            ) : (
              <Check size={13} />
            )}
            Approve & Execute
          </button>
        </div>
      )}
    </div>
  );
}
