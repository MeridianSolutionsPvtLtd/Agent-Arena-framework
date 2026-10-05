import React, { useState, useEffect, useMemo } from 'react';
import {
  X, Wrench, ShieldCheck, AlertTriangle, CheckCircle2,
  Loader2, Search, Check, Square, CheckSquare, Info, ShieldAlert
} from 'lucide-react';
import Button from '../Button';
import Badge from '../Badge';
import { useMcp } from '../../context/McpContext';
import { apiValidateMcpConnection } from '../../services/api';

export default function McpToolSelectorModal({
  isOpen,
  onClose,
  connection,
  onSuccess = null,
}) {
  const { updateSelectedTools, builderTools } = useMcp();

  // ─── Local State ─────────────────────────────────────────────
  const [tools, setTools] = useState([]);
  const [selectedTools, setSelectedTools] = useState(new Set());
  const [search, setSearch] = useState('');
  const [isLoadingTools, setIsLoadingTools] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState('');

  const connectionId = connection?.connection_id || connection?.capability_id;
  const version = connection?.version || '1.0.0';

  // ─── Load Discovered Tools for Connection ─────────────────────
  useEffect(() => {
    if (!isOpen || !connection) return;

    setError('');
    setSearch('');
    setIsLoadingTools(true);

    async function loadTools() {
      // 1. Check if tools are already in connection record
      const directTools =
        connection.tools ||
        connection.discovered_tools ||
        connection.spec?.discovered_tools ||
        connection.health?.tools ||
        connection.validation?.tools ||
        [];

      // 2. Pre-selected tools
      const currentlySelected =
        connection.selected_tool_names ||
        connection.spec?.allowed_tools ||
        connection.spec?.selected_tool_names ||
        [];

      if (Array.isArray(directTools) && directTools.length > 0) {
        setTools(directTools);
        setSelectedTools(new Set(currentlySelected.length > 0 ? currentlySelected : directTools.map(t => t.name)));
        setIsLoadingTools(false);
        return;
      }

      // 3. Check matching tools from builderTools in context
      const matchingBuilderTools = (builderTools || []).filter(
        (t) =>
          t.server_id === connectionId ||
          t.server_name === connection.name ||
          t.source_id === connectionId
      );

      if (matchingBuilderTools.length > 0) {
        setTools(matchingBuilderTools);
        setSelectedTools(
          new Set(
            currentlySelected.length > 0
              ? currentlySelected
              : matchingBuilderTools.map((t) => t.name)
          )
        );
        setIsLoadingTools(false);
        return;
      }

      // 4. Live validate probe to retrieve live discovered tools
      try {
        const validation = await apiValidateMcpConnection(connectionId, version);
        const discovered = validation?.tools || validation?.discovered_tools || [];
        setTools(discovered);
        setSelectedTools(
          new Set(
            currentlySelected.length > 0
              ? currentlySelected
              : discovered.map((t) => t.name)
          )
        );
      } catch (err) {
        console.warn('Could not fetch tools via validation probe:', err);
        // Fallback to currently selected names if any
        if (currentlySelected.length > 0) {
          const fallbackList = currentlySelected.map((name) => ({
            name,
            description: 'Enabled connection tool',
            risk_level: 'read',
          }));
          setTools(fallbackList);
          setSelectedTools(new Set(currentlySelected));
        } else {
          setTools([]);
        }
      } finally {
        setIsLoadingTools(false);
      }
    }

    loadTools();
  }, [isOpen, connection, connectionId, version, builderTools]);

  if (!isOpen || !connection) return null;

  // ─── Filtered Tools ──────────────────────────────────────────
  const filteredTools = tools.filter((t) => {
    const term = search.toLowerCase();
    return (
      (t.name || '').toLowerCase().includes(term) ||
      (t.description || '').toLowerCase().includes(term)
    );
  });

  // ─── Toggle Tool ─────────────────────────────────────────────
  const toggleTool = (toolName) => {
    setSelectedTools((prev) => {
      const next = new Set(prev);
      if (next.has(toolName)) {
        next.delete(toolName);
      } else {
        next.add(toolName);
      }
      return next;
    });
  };

  const handleSelectAll = () => {
    setSelectedTools(new Set(tools.map((t) => t.name)));
  };

  const handleDeselectAll = () => {
    setSelectedTools(new Set());
  };

  // ─── Save Changes ────────────────────────────────────────────
  const handleSave = async () => {
    setError('');
    setIsSaving(true);

    try {
      const toolNamesArray = Array.from(selectedTools);
      await updateSelectedTools(connectionId, version, toolNamesArray);

      if (onSuccess) {
        onSuccess(toolNamesArray);
      }
      onClose();
    } catch (err) {
      console.error('Failed to update MCP tools:', err);
      setError(err?.message || 'Failed to save tool permissions.');
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/40 backdrop-blur-xs animate-in fade-in duration-200">
      <div className="bg-white rounded-3xl max-w-2xl w-full border border-border shadow-2xl overflow-hidden flex flex-col max-h-[85vh]">
        {/* ─── Modal Header ───────────────────────────────────────── */}
        <div className="px-8 py-6 border-b border-border/80 flex items-center justify-between bg-section-bg/40">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 bg-primary/10 rounded-xl flex items-center justify-center text-primary font-black">
              <Wrench size={20} />
            </div>
            <div>
              <h3 className="text-base font-black text-text-primary tracking-tight">
                Manage Tools — {connection.name}
              </h3>
              <p className="text-xs text-text-secondary font-medium">
                Select which remote operations are permitted for your AI agents.
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-2 text-text-secondary hover:text-text-primary hover:bg-white rounded-xl transition-colors"
          >
            <X size={18} />
          </button>
        </div>

        {/* ─── Modal Content ──────────────────────────────────────── */}
        <div className="p-8 overflow-y-auto space-y-6 flex-1">
          {/* Error Banner */}
          {error && (
            <div className="p-4 rounded-2xl bg-red-50 border border-red-200 text-red-800 text-xs font-medium flex items-start gap-3">
              <AlertTriangle size={16} className="text-red-600 shrink-0 mt-0.5" />
              <div className="flex-1 leading-relaxed">{error}</div>
              <button
                onClick={() => setError('')}
                className="text-red-500 hover:text-red-700"
              >
                <X size={14} />
              </button>
            </div>
          )}

          {/* Controls Bar: Search & Quick Selection */}
          <div className="flex flex-col sm:flex-row items-stretch sm:items-center justify-between gap-3">
            <div className="relative flex-1">
              <Search
                size={14}
                className="absolute left-3.5 top-1/2 -translate-y-1/2 text-text-secondary"
              />
              <input
                type="text"
                placeholder="Search tools by name or description..."
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                className="w-full pl-9 pr-3 py-2 bg-section-bg/50 border border-border/80 rounded-xl text-xs font-medium focus:ring-2 focus:ring-primary/10 focus:border-primary outline-none transition-all"
              />
            </div>

            <div className="flex items-center gap-2 self-end sm:self-auto">
              <button
                type="button"
                onClick={handleSelectAll}
                className="text-[11px] font-bold text-primary hover:underline px-2 py-1"
              >
                Select All
              </button>
              <span className="text-border">|</span>
              <button
                type="button"
                onClick={handleDeselectAll}
                className="text-[11px] font-bold text-text-secondary hover:underline px-2 py-1"
              >
                Deselect All
              </button>
            </div>
          </div>

          {/* Tools List */}
          {isLoadingTools ? (
            <div className="py-12 text-center space-y-3">
              <Loader2 size={24} className="animate-spin text-primary mx-auto" />
              <p className="text-xs font-medium text-text-secondary">
                Retrieving discovered tools from server...
              </p>
            </div>
          ) : tools.length === 0 ? (
            <div className="p-8 bg-section-bg rounded-2xl text-center border border-border/60 space-y-2">
              <Info size={24} className="text-text-secondary/60 mx-auto" />
              <h4 className="text-sm font-bold text-text-primary">
                No tools discovered for this connection
              </h4>
              <p className="text-xs text-text-secondary max-w-sm mx-auto font-medium">
                The MCP server did not expose any tools during inspection. You can test connectivity using the Validate action.
              </p>
            </div>
          ) : filteredTools.length === 0 ? (
            <div className="p-8 bg-section-bg rounded-2xl text-center border border-border/60">
              <p className="text-xs text-text-secondary font-medium">
                No tools match your search criteria.
              </p>
            </div>
          ) : (
            <div className="space-y-3 max-h-80 overflow-y-auto pr-1 custom-scrollbar">
              {filteredTools.map((tool) => {
                const isSelected = selectedTools.has(tool.name);
                const isHighRisk =
                  tool.risk_level === 'write' ||
                  tool.risk_level === 'destructive' ||
                  tool.requires_approval;

                return (
                  <div
                    key={tool.name}
                    onClick={() => toggleTool(tool.name)}
                    className={`p-4 rounded-2xl border transition-all cursor-pointer flex items-start gap-3.5 select-none ${
                      isSelected
                        ? 'bg-primary/5 border-primary/40 shadow-xs'
                        : 'bg-white border-border/70 hover:border-border hover:bg-gray-50/50 opacity-75'
                    }`}
                  >
                    {/* Checkbox Icon */}
                    <div className="mt-0.5 shrink-0 text-primary">
                      {isSelected ? (
                        <CheckSquare size={18} className="text-primary fill-primary/10" />
                      ) : (
                        <Square size={18} className="text-text-secondary/40" />
                      )}
                    </div>

                    {/* Tool Details */}
                    <div className="flex-1 min-w-0 space-y-1">
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <span className="text-xs font-mono font-bold text-text-primary truncate">
                          {tool.name}
                        </span>

                        <div className="flex items-center gap-1.5">
                          {tool.risk_level && (
                            <Badge
                              variant={
                                tool.risk_level === 'destructive'
                                  ? 'danger'
                                  : tool.risk_level === 'write'
                                  ? 'warning'
                                  : 'default'
                              }
                              className="text-[9px] uppercase font-black tracking-wider"
                            >
                              {tool.risk_level}
                            </Badge>
                          )}

                          {tool.requires_approval && (
                            <Badge
                              variant="danger"
                              className="text-[9px] uppercase font-black tracking-wider flex items-center gap-1"
                            >
                              <ShieldAlert size={10} />
                              <span>Approval Required</span>
                            </Badge>
                          )}
                        </div>
                      </div>

                      {tool.description && (
                        <p className="text-xs text-text-secondary leading-relaxed">
                          {tool.description}
                        </p>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* ─── Modal Footer ───────────────────────────────────────── */}
        <div className="px-8 py-5 border-t border-border/80 bg-section-bg/40 flex items-center justify-between gap-3">
          <div className="text-xs font-bold text-text-secondary">
            Selected: <span className="text-text-primary">{selectedTools.size}</span> of{' '}
            {tools.length} {tools.length === 1 ? 'tool' : 'tools'}
          </div>

          <div className="flex items-center gap-2">
            <Button
              variant="secondary"
              onClick={onClose}
              disabled={isSaving}
              className="text-xs font-bold rounded-xl bg-white"
            >
              Cancel
            </Button>

            <Button
              variant="primary"
              onClick={handleSave}
              disabled={isSaving || isLoadingTools}
              className="text-xs font-bold rounded-xl flex items-center gap-1.5 shadow-md shadow-primary/10"
            >
              {isSaving ? (
                <>
                  <Loader2 size={14} className="animate-spin" />
                  <span>Saving...</span>
                </>
              ) : (
                <>
                  <Check size={14} />
                  <span>Save Changes</span>
                </>
              )}
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
