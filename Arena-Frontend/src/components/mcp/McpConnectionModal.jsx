import React, { useState, useEffect } from 'react';
import {
  X, Plug, Blocks, ShieldCheck, Key, Globe, Eye, EyeOff,
  AlertTriangle, ArrowRight, ArrowLeft, Loader2, CheckCircle2,
  Lock, Sparkles, ExternalLink
} from 'lucide-react';
import Button from '../Button';
import Badge from '../Badge';
import { useMcp } from '../../context/McpContext';
import { apiInspectMcpServer } from '../../services/api';

export default function McpConnectionModal({
  isOpen,
  onClose,
  template = null,
  onSuccess = null,
}) {
  const { createConnection } = useMcp();

  // ─── Local State ─────────────────────────────────────────────
  const [step, setStep] = useState('config'); // 'config' | 'discovered'
  const [name, setName] = useState('');
  const [endpoint, setEndpoint] = useState('');
  const [authMode, setAuthMode] = useState('none');
  const [authPayload, setAuthPayload] = useState({});
  const [showSecrets, setShowSecrets] = useState({});
  const [discoveredTools, setDiscoveredTools] = useState([]);
  const [isInspecting, setIsInspecting] = useState(false);
  const [isConnecting, setIsConnecting] = useState(false);
  const [error, setError] = useState('');

  // ─── Initialize from Template ────────────────────────────────
  useEffect(() => {
    if (!isOpen) return;

    setError('');
    setStep('config');
    setDiscoveredTools([]);

    if (template) {
      setName(template.name || 'MCP Integration');
      setEndpoint(template.default_endpoint || template.spec?.endpoint_ref || '');
      const mode =
        template.auth_type ||
        template.spec?.authentication?.mode ||
        (template.setup_fields && template.setup_fields.length > 0 ? 'bearer' : 'none');
      setAuthMode(mode);

      // Initialize setup field values
      const initialPayload = {};
      if (Array.isArray(template.setup_fields)) {
        template.setup_fields.forEach((f) => {
          initialPayload[f.name] = '';
        });
      }
      setAuthPayload(initialPayload);
    } else {
      setName('Custom MCP Server');
      setEndpoint('');
      setAuthMode('none');
      setAuthPayload({});
    }
  }, [isOpen, template]);

  if (!isOpen) return null;

  // ─── Setup Fields Resolver ───────────────────────────────────
  const setupFields = Array.isArray(template?.setup_fields)
    ? template.setup_fields
    : [];

  const handleFieldChange = (fieldName, value) => {
    setAuthPayload((prev) => ({ ...prev, [fieldName]: value }));
  };

  const toggleSecretVisibility = (fieldName) => {
    setShowSecrets((prev) => ({ ...prev, [fieldName]: !prev[fieldName] }));
  };

  // ─── Construct Connection Payload ────────────────────────────
  const buildPayload = () => {
    // Primary credential extraction
    let credential = null;
    if (setupFields.length > 0) {
      const primaryKey = setupFields[0].name;
      credential = authPayload[primaryKey] || null;
    } else if (authPayload.token || authPayload.api_key || authPayload.credential) {
      credential = authPayload.token || authPayload.api_key || authPayload.credential;
    }

    const payload = {
      name: name.trim() || template?.name || 'MCP Server',
      endpoint: endpoint.trim() || undefined,
      authentication_mode: authMode,
      credential: credential || undefined,
    };

    if (template?.id || template?.capability_id) {
      payload.template_ref = {
        capability_id: template.id || template.capability_id,
        version: template.version || '1.0.0',
      };
    }

    // Include full auth_payload map for custom inspection compatibility
    payload.auth_payload = authPayload;
    return payload;
  };

  // ─── Handle Inspect & Discover ───────────────────────────────
  const handleInspect = async () => {
    if (!endpoint.trim()) {
      setError('Please provide an endpoint URL to inspect.');
      return;
    }

    setError('');
    setIsInspecting(true);

    try {
      const inspectBody = {
        endpoint: endpoint.trim(),
        template_id: template?.id || template?.capability_id,
        auth_type: authMode,
        auth_payload: authPayload,
      };

      const result = await apiInspectMcpServer(inspectBody);

      // Extract discovered tools if returned
      const tools =
        result?.tools ||
        result?.discovered_tools ||
        result?.items ||
        (Array.isArray(result) ? result : []);

      setDiscoveredTools(tools);
      setStep('discovered');
    } catch (err) {
      console.warn('Direct inspection failed or returned metadata:', err);
      // If inspect endpoint returns auth metadata or 404, surface helpful guidance
      setError(
        err?.message ||
          'Server inspection could not complete. You can proceed directly to Connect.'
      );
    } finally {
      setIsInspecting(false);
    }
  };

  // ─── Handle Final Connection ─────────────────────────────────
  const handleConnect = async () => {
    if (!name.trim()) {
      setError('Please provide a connection name.');
      return;
    }
    if (!endpoint.trim() && !template?.default_endpoint) {
      setError('Please provide a valid streamable HTTP endpoint.');
      return;
    }

    setError('');
    setIsConnecting(true);

    try {
      const payload = buildPayload();
      const result = await createConnection(payload);

      if (onSuccess) {
        onSuccess(result?.connection || { name });
      }
      onClose();
    } catch (err) {
      console.error('Failed to create MCP connection:', err);
      setError(err?.message || 'Failed to establish connection to MCP server.');
    } finally {
      setIsConnecting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/40 backdrop-blur-xs animate-in fade-in duration-200">
      <div className="bg-white rounded-3xl max-w-xl w-full border border-border shadow-2xl overflow-hidden flex flex-col max-h-[90vh]">
        {/* ─── Modal Header ───────────────────────────────────────── */}
        <div className="px-8 py-6 border-b border-border/80 flex items-center justify-between bg-section-bg/40">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 bg-primary/10 rounded-xl flex items-center justify-center text-primary font-black">
              {template ? <Plug size={20} /> : <Blocks size={20} />}
            </div>
            <div>
              <h3 className="text-base font-black text-text-primary tracking-tight">
                {template ? `Connect ${template.name}` : 'Connect Custom MCP Server'}
              </h3>
              <p className="text-xs text-text-secondary font-medium">
                {step === 'config'
                  ? 'Step 1 of 2: Configure credentials & endpoint'
                  : 'Step 2 of 2: Review discovered tools & confirm'}
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

          {/* ─── STEP 1: CONFIGURATION FORM ─────────────────────── */}
          {step === 'config' && (
            <div className="space-y-5">
              {/* Connection Name */}
              <div className="space-y-2">
                <label className="text-xs font-bold text-text-primary uppercase tracking-wider block">
                  Connection Name
                </label>
                <input
                  type="text"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="e.g. Production GitHub Integration"
                  className="w-full px-4 py-3 bg-white border border-border/80 rounded-xl text-sm font-medium focus:ring-2 focus:ring-primary/10 focus:border-primary outline-none transition-all"
                />
              </div>

              {/* Endpoint URL */}
              <div className="space-y-2">
                <div className="flex items-center justify-between">
                  <label className="text-xs font-bold text-text-primary uppercase tracking-wider">
                    MCP Server Endpoint (Streamable HTTP)
                  </label>
                  {template?.documentation_url && (
                    <a
                      href={template.documentation_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-[11px] font-bold text-primary hover:underline flex items-center gap-1"
                    >
                      <span>Setup Docs</span>
                      <ExternalLink size={10} />
                    </a>
                  )}
                </div>
                <div className="relative">
                  <Globe
                    size={16}
                    className="absolute left-4 top-1/2 -translate-y-1/2 text-text-secondary"
                  />
                  <input
                    type="url"
                    value={endpoint}
                    onChange={(e) => setEndpoint(e.target.value)}
                    placeholder="https://mcp-server.example.com/v1"
                    className="w-full pl-11 pr-4 py-3 bg-white border border-border/80 rounded-xl text-sm font-mono focus:ring-2 focus:ring-primary/10 focus:border-primary outline-none transition-all"
                  />
                </div>
                <p className="text-[11px] text-text-secondary font-medium">
                  Meridian connects securely via Streamable HTTP (HTTPS).
                </p>
              </div>

              {/* Auth Mode Selector (If Custom) */}
              {!template && (
                <div className="space-y-2">
                  <label className="text-xs font-bold text-text-primary uppercase tracking-wider block">
                    Authentication Scheme
                  </label>
                  <select
                    value={authMode}
                    onChange={(e) => setAuthMode(e.target.value)}
                    className="w-full px-4 py-3 bg-white border border-border/80 rounded-xl text-sm font-bold text-text-primary focus:ring-2 focus:ring-primary/10 focus:border-primary outline-none transition-all"
                  >
                    <option value="none">Anonymous / Public (None)</option>
                    <option value="bearer">Bearer Token / Personal Access Token</option>
                    <option value="api_key">API Key Header</option>
                    <option value="oauth2">OAuth 2.0 (Dynamic Authorization)</option>
                  </select>
                </div>
              )}

              {/* Dynamic Setup Fields from Template */}
              {setupFields.length > 0 ? (
                <div className="space-y-4 pt-2 border-t border-border/60">
                  <h4 className="text-xs font-black text-text-primary uppercase tracking-wider">
                    Authentication & Credentials
                  </h4>
                  {setupFields.map((field) => {
                    const isSecret =
                      field.secret === true ||
                      field.type === 'secret' ||
                      field.type === 'password';
                    const isVisible = showSecrets[field.name];

                    return (
                      <div key={field.name} className="space-y-1.5">
                        <label className="text-xs font-bold text-text-primary flex items-center justify-between">
                          <span>
                            {field.label || field.name}
                            {field.required && (
                              <span className="text-red-500 ml-1">*</span>
                            )}
                          </span>
                          {isSecret && (
                            <span className="text-[10px] text-text-secondary font-medium flex items-center gap-1">
                              <Lock size={10} /> Encrypted at rest
                            </span>
                          )}
                        </label>

                        <div className="relative">
                          <input
                            type={isSecret && !isVisible ? 'password' : 'text'}
                            value={authPayload[field.name] || ''}
                            onChange={(e) =>
                              handleFieldChange(field.name, e.target.value)
                            }
                            placeholder={field.placeholder || `Enter ${field.label || field.name}`}
                            className="w-full px-4 py-3 bg-white border border-border/80 rounded-xl text-sm font-medium focus:ring-2 focus:ring-primary/10 focus:border-primary outline-none transition-all pr-10"
                          />
                          {isSecret && (
                            <button
                              type="button"
                              onClick={() => toggleSecretVisibility(field.name)}
                              className="absolute right-3 top-1/2 -translate-y-1/2 text-text-secondary hover:text-text-primary p-1"
                            >
                              {isVisible ? <EyeOff size={16} /> : <Eye size={16} />}
                            </button>
                          )}
                        </div>

                        {field.help_text && (
                          <p className="text-[11px] text-text-secondary leading-relaxed">
                            {field.help_text}
                          </p>
                        )}
                      </div>
                    );
                  })}
                </div>
              ) : (
                /* Fallback credential input for non-template custom auth */
                (authMode === 'bearer' || authMode === 'api_key') && (
                  <div className="space-y-2 pt-2 border-t border-border/60">
                    <label className="text-xs font-bold text-text-primary uppercase tracking-wider block">
                      {authMode === 'bearer' ? 'Bearer Token / PAT' : 'API Key'}
                    </label>
                    <div className="relative">
                      <Key
                        size={16}
                        className="absolute left-4 top-1/2 -translate-y-1/2 text-text-secondary"
                      />
                      <input
                        type={showSecrets.custom ? 'text' : 'password'}
                        value={authPayload.credential || ''}
                        onChange={(e) => handleFieldChange('credential', e.target.value)}
                        placeholder="Enter secret token..."
                        className="w-full pl-11 pr-10 py-3 bg-white border border-border/80 rounded-xl text-sm font-medium focus:ring-2 focus:ring-primary/10 focus:border-primary outline-none transition-all"
                      />
                      <button
                        type="button"
                        onClick={() => toggleSecretVisibility('custom')}
                        className="absolute right-3 top-1/2 -translate-y-1/2 text-text-secondary hover:text-text-primary p-1"
                      >
                        {showSecrets.custom ? <EyeOff size={16} /> : <Eye size={16} />}
                      </button>
                    </div>
                  </div>
                )
              )}

              {authMode === 'oauth2' && (
                <div className="p-4 bg-blue-50/80 border border-blue-200 rounded-2xl text-blue-900 text-xs space-y-1">
                  <div className="font-bold flex items-center gap-1.5">
                    <Sparkles size={14} className="text-blue-600" />
                    <span>OAuth 2.0 Dynamic Authorization</span>
                  </div>
                  <p className="text-blue-800/90 leading-relaxed text-[11px]">
                    Clicking connect will initialize the OAuth handshake with the MCP server to obtain delegated access tokens securely.
                  </p>
                </div>
              )}
            </div>
          )}

          {/* ─── STEP 2: DISCOVERED TOOLS REVIEW ────────────────── */}
          {step === 'discovered' && (
            <div className="space-y-4">
              <div className="p-4 bg-green-50/80 border border-green-200 rounded-2xl text-green-900 text-xs flex items-center gap-3">
                <CheckCircle2 size={18} className="text-green-600 shrink-0" />
                <div>
                  <h4 className="font-bold">Inspection Successful</h4>
                  <p className="text-[11px] opacity-90">
                    The server responded successfully. Review the discovered tools below before connecting.
                  </p>
                </div>
              </div>

              <div className="space-y-2">
                <div className="flex items-center justify-between">
                  <h4 className="text-xs font-black text-text-primary uppercase tracking-wider">
                    Discovered Tools ({discoveredTools.length})
                  </h4>
                  <span className="text-[10px] font-bold text-text-secondary">
                    All tools will be staged for your agents
                  </span>
                </div>

                {discoveredTools.length === 0 ? (
                  <div className="p-6 bg-section-bg rounded-2xl text-center border border-border/60">
                    <p className="text-xs font-medium text-text-secondary">
                      No tools were directly discovered during the inspection probe. Tools will be synchronized when connection is established.
                    </p>
                  </div>
                ) : (
                  <div className="space-y-2.5 max-h-64 overflow-y-auto pr-1 custom-scrollbar">
                    {discoveredTools.map((tool, idx) => (
                      <div
                        key={tool.name || idx}
                        className="p-3.5 bg-white border border-border/80 rounded-xl space-y-1.5 shadow-xs"
                      >
                        <div className="flex items-start justify-between gap-2">
                          <span className="text-xs font-mono font-bold text-text-primary">
                            {tool.name}
                          </span>
                          <div className="flex items-center gap-1.5">
                            {tool.risk_level && (
                              <Badge
                                variant={
                                  tool.risk_level === 'write' ||
                                  tool.risk_level === 'destructive'
                                    ? 'warning'
                                    : 'default'
                                }
                                className="text-[9px] uppercase font-black"
                              >
                                {tool.risk_level}
                              </Badge>
                            )}
                            {tool.requires_approval && (
                              <Badge
                                variant="danger"
                                className="text-[9px] uppercase font-black"
                              >
                                Approval Req.
                              </Badge>
                            )}
                          </div>
                        </div>
                        {tool.description && (
                          <p className="text-[11px] text-text-secondary leading-relaxed line-clamp-2">
                            {tool.description}
                          </p>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          )}
        </div>

        {/* ─── Modal Footer ───────────────────────────────────────── */}
        <div className="px-8 py-5 border-t border-border/80 bg-section-bg/40 flex items-center justify-between gap-3">
          {step === 'discovered' ? (
            <Button
              variant="ghost"
              onClick={() => setStep('config')}
              disabled={isConnecting}
              className="text-xs font-bold rounded-xl flex items-center gap-1.5"
            >
              <ArrowLeft size={14} />
              <span>Back to Config</span>
            </Button>
          ) : (
            <Button
              variant="secondary"
              onClick={onClose}
              disabled={isInspecting || isConnecting}
              className="text-xs font-bold rounded-xl bg-white"
            >
              Cancel
            </Button>
          )}

          <div className="flex items-center gap-2">
            {step === 'config' && (
              <Button
                variant="secondary"
                onClick={handleInspect}
                disabled={isInspecting || isConnecting || !endpoint.trim()}
                className="text-xs font-bold rounded-xl bg-white flex items-center gap-1.5"
              >
                {isInspecting ? (
                  <>
                    <Loader2 size={14} className="animate-spin text-primary" />
                    <span>Inspecting...</span>
                  </>
                ) : (
                  <>
                    <ShieldCheck size={14} />
                    <span>Inspect & Discover</span>
                  </>
                )}
              </Button>
            )}

            <Button
              variant="primary"
              onClick={handleConnect}
              disabled={isInspecting || isConnecting}
              className="text-xs font-bold rounded-xl flex items-center gap-1.5 shadow-md shadow-primary/10"
            >
              {isConnecting ? (
                <>
                  <Loader2 size={14} className="animate-spin" />
                  <span>Connecting...</span>
                </>
              ) : (
                <>
                  <span>Connect Server</span>
                  <ArrowRight size={14} />
                </>
              )}
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
