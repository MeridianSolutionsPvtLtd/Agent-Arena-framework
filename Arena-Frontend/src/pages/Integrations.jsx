import React, { useState, useMemo } from 'react';
import {
  Blocks, Plug, Search, Filter, RefreshCw, CheckCircle2, AlertTriangle,
  ExternalLink, Trash2, Wrench, ShieldCheck, Key, Globe, ArrowRight,
  Info, Loader2, X, Check
} from 'lucide-react';
import { useMcp } from '../context/McpContext';
import Card from '../components/Card';
import Button from '../components/Button';
import Badge from '../components/Badge';
import Skeleton from '../components/skeleton/Skeleton';
import McpConnectionModal from '../components/mcp/McpConnectionModal';
import McpToolSelectorModal from '../components/mcp/McpToolSelectorModal';

export default function Integrations() {
  const {
    templates,
    connections,
    loading,
    error,
    fetchTemplates,
    fetchConnections,
    deleteConnection,
    validateConnection,
  } = useMcp();

  const [search, setSearch] = useState('');
  const [selectedCategory, setSelectedCategory] = useState('All');
  const [isCategoryDropdownOpen, setIsCategoryDropdownOpen] = useState(false);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [validatingId, setValidatingId] = useState(null);
  const [connectionToDelete, setConnectionToDelete] = useState(null);
  const [actionNotice, setActionNotice] = useState(null);
  const [selectedTemplateForConnection, setSelectedTemplateForConnection] = useState(null);
  const [isCustomModalOpen, setIsCustomModalOpen] = useState(false);
  const [selectedConnectionForTools, setSelectedConnectionForTools] = useState(null);

  // ─── Manual Refresh Handler ──────────────────────────────────
  const handleRefresh = async () => {
    setIsRefreshing(true);
    try {
      await Promise.allSettled([fetchTemplates(), fetchConnections()]);
    } finally {
      setIsRefreshing(false);
    }
  };

  // ─── Categories Computation ──────────────────────────────────
  const categories = useMemo(() => {
    const cats = new Set();
    templates.forEach((t) => {
      if (t.category) cats.add(t.category);
    });
    return ['All', ...Array.from(cats)];
  }, [templates]);

  // ─── Filtered Templates ──────────────────────────────────────
  const filteredTemplates = useMemo(() => {
    return templates.filter((t) => {
      const matchSearch =
        (t.name || '').toLowerCase().includes(search.toLowerCase()) ||
        (t.description || '').toLowerCase().includes(search.toLowerCase()) ||
        (t.id || '').toLowerCase().includes(search.toLowerCase());
      const matchCat =
        selectedCategory === 'All' || t.category === selectedCategory;
      return matchSearch && matchCat;
    });
  }, [templates, search, selectedCategory]);

  // ─── Filtered Connections ────────────────────────────────────
  const filteredConnections = useMemo(() => {
    return connections.filter((c) => {
      return (
        (c.name || '').toLowerCase().includes(search.toLowerCase()) ||
        (c.endpoint || '').toLowerCase().includes(search.toLowerCase()) ||
        (c.capability_id || '').toLowerCase().includes(search.toLowerCase())
      );
    });
  }, [connections, search]);

  // ─── Connection Validation ───────────────────────────────────
  const handleValidate = async (conn) => {
    const id = conn.capability_id;
    const version = conn.version || '1.0.0';
    setValidatingId(id);
    try {
      const res = await validateConnection(id, version);
      setActionNotice({
        type: 'success',
        title: 'Validation Successful',
        message: `Connection "${conn.name}" is healthy and reachable.`,
      });
    } catch (err) {
      setActionNotice({
        type: 'error',
        title: 'Validation Failed',
        message: err?.message || 'Server did not respond to validation probe.',
      });
    } finally {
      setValidatingId(null);
    }
  };

  // ─── Connection Deletion ─────────────────────────────────────
  const handleDeleteConfirm = async () => {
    if (!connectionToDelete) return;
    const { capability_id, version = '1.0.0', name } = connectionToDelete;
    try {
      await deleteConnection(capability_id, version);
      setActionNotice({
        type: 'success',
        title: 'Connection Removed',
        message: `Connection "${name}" has been disconnected.`,
      });
    } catch (err) {
      setActionNotice({
        type: 'error',
        title: 'Deletion Failed',
        message: err?.message || 'Could not delete the connection.',
      });
    } finally {
      setConnectionToDelete(null);
    }
  };

  const formatDate = (isoString) => {
    if (!isoString) return 'Never';
    const d = new Date(isoString);
    return Number.isNaN(d.getTime())
      ? 'Never'
      : d.toLocaleDateString('en-US', {
          month: 'short',
          day: 'numeric',
          year: 'numeric',
          hour: '2-digit',
          minute: '2-digit',
        });
  };

  return (
    <div className="min-h-screen bg-section-bg">
      {/* ─── Page Header ────────────────────────────────────────── */}
      <div className="bg-white border-b border-border">
        <div className="section-container py-8">
          <div className="flex flex-col md:flex-row md:items-end justify-between gap-4">
            <div>
              <div className="flex items-center gap-2 mb-2">
                <span className="text-[10px] font-black text-primary uppercase tracking-[0.2em] px-2.5 py-0.5 bg-primary/5 border border-primary/10 rounded-full">
                  Model Context Protocol
                </span>
              </div>
              <h1 className="text-3xl font-black text-text-primary tracking-tight mb-2">
                Integrations Hub
              </h1>
              <p className="text-text-secondary font-medium max-w-2xl text-sm">
                Connect external enterprise services, data sources, and tools via Model Context Protocol (MCP) to power your AI workforce.
              </p>
            </div>

            {/* Header Right / Status Counter */}
            <div className="flex flex-wrap items-center gap-2.5 sm:gap-3">
              <button
                type="button"
                onClick={() => {
                  setSelectedTemplateForConnection(null);
                  setIsCustomModalOpen(true);
                }}
                className="px-4 py-2.5 bg-primary hover:bg-primary-hover text-white rounded-2xl text-xs font-bold transition-all shadow-sm flex items-center gap-2 hover:scale-[1.02] active:scale-[0.98]"
              >
                <Plug size={15} />
                <span className="hidden sm:inline">Connect Custom Server</span>
                <span className="sm:hidden">Custom Server</span>
              </button>

              <button
                type="button"
                onClick={handleRefresh}
                disabled={isRefreshing || loading}
                className="px-4 py-2.5 bg-white border border-border/80 hover:border-primary/40 rounded-2xl text-text-secondary hover:text-primary transition-all shadow-sm flex items-center gap-2 text-xs font-bold hover:scale-[1.02] active:scale-[0.98] disabled:opacity-50"
                title="Refresh integrations"
              >
                <RefreshCw
                  size={15}
                  className={isRefreshing ? 'animate-spin text-primary' : ''}
                />
                <span className="hidden sm:inline">Refresh</span>
              </button>

              <div className="px-4 py-2.5 bg-primary/5 border border-primary/10 rounded-2xl flex items-center gap-2.5">
                <span className="text-[10px] font-black text-primary uppercase tracking-widest">
                  Active
                </span>
                <div className="w-1.5 h-1.5 bg-primary rounded-full animate-pulse"></div>
                <span className="text-xs font-black text-text-primary">
                  {connections.length} Connected
                </span>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* ─── Main Content Container ─────────────────────────────── */}
      <div className="section-container py-8 min-h-[calc(100vh-220px)] space-y-10">
        {/* Notice / Toast Banner */}
        {actionNotice && (
          <div
            className={`p-4 rounded-2xl border flex items-start justify-between gap-4 animate-in fade-in duration-200 ${
              actionNotice.type === 'success'
                ? 'bg-green-50/80 border-green-200 text-green-800'
                : 'bg-red-50/80 border-red-200 text-red-800'
            }`}
          >
            <div className="flex items-start gap-3">
              {actionNotice.type === 'success' ? (
                <CheckCircle2 size={18} className="text-green-600 shrink-0 mt-0.5" />
              ) : (
                <AlertTriangle size={18} className="text-red-600 shrink-0 mt-0.5" />
              )}
              <div>
                <h4 className="text-sm font-bold">{actionNotice.title}</h4>
                <p className="text-xs font-medium opacity-90">{actionNotice.message}</p>
              </div>
            </div>
            <button
              onClick={() => setActionNotice(null)}
              className="p-1 text-text-secondary/60 hover:text-text-primary rounded-lg"
            >
              <X size={16} />
            </button>
          </div>
        )}

        {/* Global Error Banner */}
        {error && (
          <div className="p-5 rounded-2xl bg-amber-50/80 border border-amber-200 text-amber-900 flex items-start gap-4">
            <AlertTriangle size={20} className="text-amber-600 shrink-0 mt-0.5" />
            <div className="flex-1">
              <h4 className="text-sm font-bold mb-1">MCP Service Notice</h4>
              <p className="text-xs font-medium text-amber-800/90 leading-relaxed">
                {error}
              </p>
            </div>
            <Button
              size="sm"
              variant="secondary"
              onClick={handleRefresh}
              className="shrink-0 bg-white"
            >
              Retry
            </Button>
          </div>
        )}

        {/* ─── Controls: Search & Category Filter ─────────── */}
        <div className="flex flex-col sm:flex-row gap-3 items-stretch sm:items-center justify-between">
          <div className="relative flex-1 max-w-md">
            <Search
              size={16}
              className="absolute left-4 top-1/2 -translate-y-1/2 text-text-secondary"
            />
            <input
              type="text"
              placeholder="Search templates or connections..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="w-full pl-11 pr-4 py-2.5 bg-white border border-border/80 rounded-xl text-xs font-medium focus:ring-2 focus:ring-primary/10 focus:border-primary outline-none transition-all shadow-sm"
            />
          </div>

          {/* Category Dropdown */}
          {categories.length > 1 && (
            <div className="relative w-full sm:w-auto">
              <button
                onClick={() => setIsCategoryDropdownOpen(!isCategoryDropdownOpen)}
                className="w-full sm:w-auto flex items-center justify-between gap-2 px-4 py-2.5 bg-white border border-border/80 rounded-xl text-xs font-bold text-text-primary shadow-sm hover:border-primary/40 transition-all"
              >
                <div className="flex items-center gap-2">
                  <Filter size={14} className="text-primary" />
                  <span className="truncate max-w-[130px]">{selectedCategory}</span>
                </div>
              </button>

              {isCategoryDropdownOpen && (
                <>
                  <div
                    className="fixed inset-0 z-20"
                    onClick={() => setIsCategoryDropdownOpen(false)}
                  ></div>
                  <div className="absolute right-0 mt-2 w-48 bg-white border border-border rounded-xl shadow-xl z-30 py-1.5">
                    {categories.map((cat) => (
                      <button
                        key={cat}
                        onClick={() => {
                          setSelectedCategory(cat);
                          setIsCategoryDropdownOpen(false);
                        }}
                        className={`w-full text-left px-3.5 py-2 text-xs font-bold flex items-center justify-between hover:bg-gray-50 transition-colors ${
                          selectedCategory === cat ? 'text-primary bg-primary/5' : 'text-text-primary'
                        }`}
                      >
                        <span>{cat}</span>
                        {selectedCategory === cat && <Check size={14} className="text-primary" />}
                      </button>
                    ))}
                  </div>
                </>
              )}
            </div>
          )}
        </div>

        {/* ─── SECTION 1: AVAILABLE INTEGRATIONS ───────────────────── */}
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-lg font-black text-text-primary tracking-tight">
                Available Integrations
              </h2>
              <p className="text-xs text-text-secondary font-medium">
                Catalog templates pre-configured for instant connection.
              </p>
            </div>
            <Badge variant="primary" className="text-[10px] font-black uppercase">
              {templates.length} Available
            </Badge>
          </div>

          {loading && templates.length === 0 ? (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
              {[1, 2, 3].map((i) => (
                <div
                  key={i}
                  className="p-6 bg-white rounded-2xl border border-border/80 space-y-4 shadow-sm"
                >
                  <div className="flex items-center gap-3">
                    <Skeleton variant="rounded" className="w-12 h-12" />
                    <div className="space-y-2 flex-1">
                      <Skeleton variant="text" className="w-3/4 h-4" />
                      <Skeleton variant="text" className="w-1/2 h-3" />
                    </div>
                  </div>
                  <Skeleton variant="text" className="w-full h-12" />
                </div>
              ))}
            </div>
          ) : filteredTemplates.length === 0 ? (
            <Card className="text-center py-12 px-6 border-dashed border-2 border-border/80 bg-white/50">
              <div className="w-14 h-14 bg-primary/5 rounded-2xl flex items-center justify-center mx-auto mb-4 text-primary border border-primary/10">
                <Blocks size={24} />
              </div>
              <h3 className="text-base font-bold text-text-primary mb-1">
                No integration templates available
              </h3>
              <p className="text-xs text-text-secondary max-w-md mx-auto font-medium">
                Integrations returned by the server catalog will appear dynamically here.
              </p>
            </Card>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
              {filteredTemplates.map((template) => {
                return (
                  <Card
                    key={template.id}
                    className="p-6 flex flex-col justify-between border-border/80 hover:border-primary/30 transition-all shadow-sm group"
                  >
                    <div className="space-y-4">
                      {/* Header: Icon & Category */}
                      <div className="flex items-start justify-between gap-3">
                        <div className="w-12 h-12 bg-primary/5 rounded-2xl flex items-center justify-center text-primary font-black text-lg border border-primary/10 group-hover:scale-105 transition-transform">
                          <Plug size={22} />
                        </div>
                        {template.category && (
                          <Badge variant="default" className="text-[10px] font-black uppercase tracking-wider">
                            {template.category}
                          </Badge>
                        )}
                      </div>

                      {/* Title & Description */}
                      <div>
                        <h3 className="text-base font-black text-text-primary tracking-tight mb-1">
                          {template.name}
                        </h3>
                        <p className="text-xs text-text-secondary leading-relaxed line-clamp-3">
                          {template.description || 'Streamable HTTP Model Context Protocol integration connector.'}
                        </p>
                      </div>

                      {/* Badges */}
                      <div className="flex flex-wrap gap-2 pt-2 border-t border-border/40">
                        {template.auth_type && (
                          <span className="text-[10px] font-bold text-text-secondary/80 bg-gray-100 px-2 py-0.5 rounded-md uppercase">
                            Auth: {template.auth_type}
                          </span>
                        )}
                        {template.default_endpoint && (
                          <span className="text-[10px] font-bold text-text-secondary/80 bg-gray-100 px-2 py-0.5 rounded-md truncate max-w-[180px]">
                            {template.default_endpoint}
                          </span>
                        )}
                      </div>
                    </div>

                    {/* Connect Button */}
                    <div className="pt-5 mt-4 border-t border-border/40 flex items-center justify-between gap-2">
                      {template.documentation_url ? (
                        <a
                          href={template.documentation_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-xs font-bold text-text-secondary hover:text-primary flex items-center gap-1"
                        >
                          <span>Docs</span>
                          <ExternalLink size={12} />
                        </a>
                      ) : (
                        <span className="text-[10px] font-bold text-text-secondary/40">MCP v1.0</span>
                      )}

                      <Button
                        size="sm"
                        onClick={() => setSelectedTemplateForConnection(template)}
                        className="text-xs px-4 py-2 rounded-xl font-bold flex items-center gap-1.5"
                      >
                        <span>Connect</span>
                        <ArrowRight size={12} />
                      </Button>
                    </div>
                  </Card>
                );
              })}
            </div>
          )}
        </div>

        {/* ─── SECTION 2: MY CONNECTIONS ─────────────────────────── */}
        <div className="space-y-4 pt-4">
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-lg font-black text-text-primary tracking-tight">
                My Connections
              </h2>
              <p className="text-xs text-text-secondary font-medium">
                Active Model Context Protocol servers available to your agents.
              </p>
            </div>
            <Badge variant="primary" className="text-[10px] font-black uppercase">
              {connections.length} Active
            </Badge>
          </div>

          {loading && connections.length === 0 ? (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
              {[1, 2].map((i) => (
                <div
                  key={i}
                  className="p-6 bg-white rounded-2xl border border-border/80 space-y-4 shadow-sm"
                >
                  <div className="flex items-center gap-3">
                    <Skeleton variant="rounded" className="w-12 h-12" />
                    <div className="space-y-2 flex-1">
                      <Skeleton variant="text" className="w-3/4 h-4" />
                      <Skeleton variant="text" className="w-1/2 h-3" />
                    </div>
                  </div>
                  <Skeleton variant="text" className="w-full h-10" />
                </div>
              ))}
            </div>
          ) : filteredConnections.length === 0 ? (
            <Card className="text-center py-12 px-6 border-dashed border-2 border-border/80 bg-white/50">
              <div className="w-14 h-14 bg-primary/5 rounded-2xl flex items-center justify-center mx-auto mb-4 text-primary border border-primary/10">
                <Plug size={24} />
              </div>
              <h3 className="text-base font-bold text-text-primary mb-1">
                No MCP integrations connected yet
              </h3>
              <p className="text-xs text-text-secondary max-w-md mx-auto mb-6 font-medium">
                Connect an integration template above or add a custom server to expose live external tools and resources to your workforce.
              </p>
              <Button
                size="sm"
                onClick={() => {
                  setSelectedTemplateForConnection(null);
                  setIsCustomModalOpen(true);
                }}
                className="rounded-xl font-bold"
              >
                Connect Custom Server
              </Button>
            </Card>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
              {filteredConnections.map((conn) => {
                const connId = conn.capability_id || conn.connection_id;
                const isValidating = validatingId === connId;
                const totalTools =
                  conn.total_tools ||
                  (conn.selected_tool_names ? conn.selected_tool_names.length : 0);
                const endpointUrl = conn.endpoint || conn.spec?.endpoint_ref || 'streamable_http';
                const transportType = conn.transport || conn.spec?.transport || 'streamable_http';

                return (
                  <Card
                    key={`${connId}-${conn.version || '1.0.0'}`}
                    className="p-6 flex flex-col justify-between border-border/80 hover:border-primary/30 transition-all shadow-sm group"
                  >
                    <div className="space-y-4">
                      {/* Card Header: Icon & Status */}
                      <div className="flex items-start justify-between gap-3">
                        <div className="w-12 h-12 bg-primary/5 rounded-2xl flex items-center justify-center text-primary font-black text-lg border border-primary/10 group-hover:scale-105 transition-transform">
                          <Blocks size={24} />
                        </div>
                        <div className="flex items-center gap-1.5">
                          <Badge
                            variant={
                              conn.status === 'connected'
                                ? 'success'
                                : conn.status === 'error'
                                ? 'danger'
                                : 'default'
                            }
                            className="text-[10px] font-black uppercase tracking-wider"
                          >
                            {conn.status || 'Connected'}
                          </Badge>
                        </div>
                      </div>

                      {/* Title & Endpoint */}
                      <div>
                        <h3 className="text-base font-black text-text-primary tracking-tight mb-1 truncate">
                          {conn.name}
                        </h3>
                        <p className="text-xs text-text-secondary/70 font-mono truncate">
                          {endpointUrl}
                        </p>
                      </div>

                      {/* Metadata Grid */}
                      <div className="grid grid-cols-2 gap-2 pt-2 border-t border-border/40 text-[11px]">
                        <div>
                          <span className="text-text-secondary/60 font-bold block uppercase tracking-wider text-[9px]">
                            Active Tools
                          </span>
                          <span className="font-bold text-text-primary">
                            {totalTools} {totalTools === 1 ? 'Tool' : 'Tools'}
                          </span>
                        </div>
                        <div>
                          <span className="text-text-secondary/60 font-bold block uppercase tracking-wider text-[9px]">
                            Transport
                          </span>
                          <span className="font-bold text-text-primary capitalize">
                            {transportType}
                          </span>
                        </div>
                        <div className="col-span-2 pt-1">
                          <span className="text-text-secondary/60 font-bold block uppercase tracking-wider text-[9px]">
                            Last Validated
                          </span>
                          <span className="font-medium text-text-secondary">
                            {formatDate(conn.last_validated_at || conn.health?.checked_at)}
                          </span>
                        </div>
                      </div>
                    </div>

                    {/* Card Footer Actions */}
                    <div className="pt-5 mt-4 border-t border-border/40 flex items-center justify-between gap-2">
                      <div className="flex items-center gap-1.5">
                        <Button
                          size="sm"
                          variant="secondary"
                          onClick={() => handleValidate({ ...conn, capability_id: connId })}
                          disabled={isValidating}
                          className="text-xs px-3 py-1.5 rounded-xl font-bold bg-white"
                        >
                          {isValidating ? (
                            <>
                              <Loader2 size={12} className="animate-spin" />
                              <span>Testing...</span>
                            </>
                          ) : (
                            <>
                              <ShieldCheck size={12} />
                              <span>Validate</span>
                            </>
                          )}
                        </Button>

                        <button
                          onClick={() => setSelectedConnectionForTools({ ...conn, capability_id: connId })}
                          className="p-2 text-text-secondary hover:text-primary hover:bg-gray-100 rounded-xl transition-colors"
                          title="Manage Tools"
                        >
                          <Wrench size={14} />
                        </button>

                        <button
                          onClick={() =>
                            setActionNotice({
                              type: 'success',
                              title: 'Reconnect Flow (Phase 3)',
                              message: `Credential updates for "${conn.name}" will be configurable in Phase 3.`,
                            })
                          }
                          className="p-2 text-text-secondary hover:text-primary hover:bg-gray-100 rounded-xl transition-colors"
                          title="Reconnect Credentials"
                        >
                          <Key size={14} />
                        </button>
                      </div>

                      <button
                        onClick={() => setConnectionToDelete({ ...conn, capability_id: connId })}
                        className="p-2 text-text-secondary hover:text-red-600 hover:bg-red-50 rounded-xl transition-colors"
                        title="Delete Connection"
                      >
                        <Trash2 size={14} />
                      </button>
                    </div>
                  </Card>
                );
              })}
            </div>
          )}
        </div>
      </div>

      {/* ─── MCP Connection Wizard Modal ─────────────────────────── */}
      <McpConnectionModal
        isOpen={Boolean(selectedTemplateForConnection || isCustomModalOpen)}
        template={selectedTemplateForConnection}
        onClose={() => {
          setSelectedTemplateForConnection(null);
          setIsCustomModalOpen(false);
        }}
        onSuccess={(newConn) => {
          setActionNotice({
            type: 'success',
            title: 'Connection Established',
            message: `Successfully connected to "${newConn.name}". Discovered tools are now active.`,
          });
        }}
      />

      {/* ─── MCP Tool Permissions Modal ─────────────────────────── */}
      <McpToolSelectorModal
        isOpen={Boolean(selectedConnectionForTools)}
        connection={selectedConnectionForTools}
        onClose={() => setSelectedConnectionForTools(null)}
        onSuccess={(selectedToolNames) => {
          setActionNotice({
            type: 'success',
            title: 'Tool Permissions Saved',
            message: `Updated tool permissions for "${selectedConnectionForTools?.name}". ${selectedToolNames.length} active tools permitted.`,
          });
        }}
      />

      {/* ─── Delete Confirmation Modal ──────────────────────────── */}
      {connectionToDelete && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/40 backdrop-blur-xs animate-in fade-in duration-200">
          <div className="bg-white rounded-3xl p-6 sm:p-8 max-w-md w-full border border-border shadow-2xl space-y-6">
            <div className="w-12 h-12 rounded-2xl bg-red-50 text-red-600 flex items-center justify-center mx-auto">
              <AlertTriangle size={24} />
            </div>

            <div className="text-center space-y-2">
              <h3 className="text-lg font-black text-text-primary">
                Disconnect Integration?
              </h3>
              <p className="text-xs text-text-secondary font-medium leading-relaxed">
                Are you sure you want to disconnect <strong className="text-text-primary">"{connectionToDelete.name}"</strong>? Stored credentials will be deleted and associated tools will no longer be available to your agents.
              </p>
            </div>

            <div className="flex items-center gap-3">
              <Button
                variant="secondary"
                onClick={() => setConnectionToDelete(null)}
                className="flex-1 rounded-xl text-xs font-bold bg-white"
              >
                Cancel
              </Button>
              <Button
                variant="danger"
                onClick={handleDeleteConfirm}
                className="flex-1 rounded-xl text-xs font-bold"
              >
                Disconnect
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
