// ─── MCP & Governed Capabilities API ─────────────────────────
// Frontend service layer for Model Context Protocol (MCP) server templates,
// user connections, remote inspection, dynamic tool selection, OAuth flows,
// Agent Builder capability catalog, and Human-In-The-Loop (HITL) tool executions.
//
// Router prefixes in backend:
//   • /api/mcp            (mcp_connections.py)
//   • /api/capabilities   (capabilities.py)
//   • /api/tool-executions (tool_executions.py)
//
// All requests flow through the Meridian backend via `apiFetch`. The browser
// NEVER connects directly to external MCP servers.
import { apiFetch, parseApiErrorDetail } from './http';

/** 204 No Content safe JSON reader */
async function jsonOrEmpty(res) {
  if (res.status === 204) return { success: true };
  return res.json();
}

// ─── MCP Templates ───────────────────────────────────────────
/**
 * Get pre-seeded MCP server templates (e.g. GitHub, Notion, Atlassian, Google Drive).
 * GET /api/mcp/templates
 */
export async function apiGetMcpTemplates() {
  const res = await apiFetch('/api/mcp/templates');
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(parseApiErrorDetail(err) || `Failed to fetch MCP templates (${res.status})`);
  }
  return res.json();
}

// ─── User Connections ────────────────────────────────────────
/**
 * List all MCP server connections established by the current user.
 * GET /api/mcp/connections
 */
export async function apiGetMcpConnections() {
  const res = await apiFetch('/api/mcp/connections');
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(parseApiErrorDetail(err) || `Failed to fetch MCP connections (${res.status})`);
  }
  return res.json();
}

// ─── MCP Server Inspection ───────────────────────────────────
/**
 * Inspect a remote streamable HTTP MCP server authentication requirements.
 * POST /api/mcp/inspect
 * @param {Object|string} payload { endpoint } or endpoint string
 */
export async function apiInspectMcpServer(payload) {
  const endpoint = typeof payload === 'string' ? payload : payload?.endpoint;
  const res = await apiFetch('/api/mcp/inspect', {
    method: 'POST',
    body: JSON.stringify({ endpoint: String(endpoint || '').trim() }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(parseApiErrorDetail(err) || `MCP server inspection failed (${res.status})`);
  }
  return res.json();
}

// ─── Create MCP Connection ───────────────────────────────────
/**
 * Connect a new MCP server or template instance with credentials and auto-discover tools.
 * POST /api/mcp/connections
 * @param {Object} payload { name, template_ref?, endpoint?, authentication_mode?, credential? }
 */
export async function apiCreateMcpConnection(payload) {
  const body = {
    name: payload?.name,
  };
  if (payload?.template_ref) {
    body.template_ref = payload.template_ref;
  }
  if (payload?.endpoint) {
    body.endpoint = payload.endpoint;
  }
  if (payload?.authentication_mode) {
    body.authentication_mode = payload.authentication_mode;
  }
  if (payload?.credential) {
    body.credential = payload.credential;
  }

  const res = await apiFetch('/api/mcp/connections', {
    method: 'POST',
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(parseApiErrorDetail(err) || `Failed to create MCP connection (${res.status})`);
  }
  return res.json();
}

// ─── Select Active Tools ─────────────────────────────────────
/**
 * Enable or disable specific discovered tools for a connection.
 * POST /api/mcp/connections/{capability_id}/{version}/tools
 * @param {string} capabilityId
 * @param {string} version
 * @param {string[]} toolNames
 */
export async function apiSelectMcpTools(capabilityId, version = '1.0.0', toolNames = []) {
  const path = `/api/mcp/connections/${encodeURIComponent(capabilityId)}/${encodeURIComponent(version)}/tools`;
  const res = await apiFetch(path, {
    method: 'POST',
    body: JSON.stringify({ selected_tool_names: toolNames }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(parseApiErrorDetail(err) || `Failed to update tool selection (${res.status})`);
  }
  return res.json();
}

// ─── Validate Connection ─────────────────────────────────────
/**
 * Test connectivity and credentials against the live MCP server.
 * POST /api/mcp/connections/{capability_id}/{version}/validate
 * @param {string} capabilityId
 * @param {string} version
 */
export async function apiValidateMcpConnection(capabilityId, version = '1.0.0') {
  const path = `/api/mcp/connections/${encodeURIComponent(capabilityId)}/${encodeURIComponent(version)}/validate`;
  const res = await apiFetch(path, {
    method: 'POST',
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(parseApiErrorDetail(err) || `Connection validation failed (${res.status})`);
  }
  return res.json();
}

// ─── Reconnect Connection ────────────────────────────────────
/**
 * Update credentials or re-authenticate an existing MCP server connection.
 * POST /api/mcp/connections/{capability_id}/{version}/reconnect
 * @param {string} capabilityId
 * @param {string} version
 * @param {Object|string} payload { credential } or credential string
 */
export async function apiReconnectMcpConnection(capabilityId, version = '1.0.0', payload = {}) {
  const path = `/api/mcp/connections/${encodeURIComponent(capabilityId)}/${encodeURIComponent(version)}/reconnect`;
  const credential = typeof payload === 'string' ? payload : (payload?.credential || '');
  const res = await apiFetch(path, {
    method: 'POST',
    body: JSON.stringify({ credential }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(parseApiErrorDetail(err) || `Failed to reconnect MCP server (${res.status})`);
  }
  return res.json();
}

// ─── Delete Connection ───────────────────────────────────────
/**
 * Disconnect an MCP server, delete stored credentials, and archive associated tools.
 * DELETE /api/mcp/connections/{capability_id}/{version}
 * @param {string} capabilityId
 * @param {string} version
 */
export async function apiDeleteMcpConnection(capabilityId, version = '1.0.0') {
  const path = `/api/mcp/connections/${encodeURIComponent(capabilityId)}/${encodeURIComponent(version)}`;
  const res = await apiFetch(path, {
    method: 'DELETE',
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(parseApiErrorDetail(err) || `Failed to delete MCP connection (${res.status})`);
  }
  return jsonOrEmpty(res);
}

// ─── OAuth Flow ──────────────────────────────────────────────
/**
 * Initiate dynamic OAuth flow for an MCP server to get authorization URL.
 * POST /api/mcp/oauth/start
 * @param {Object} payload
 */
export async function apiStartMcpOAuth(payload) {
  const res = await apiFetch('/api/mcp/oauth/start', {
    method: 'POST',
    body: JSON.stringify(payload || {}),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(parseApiErrorDetail(err) || `Failed to start MCP OAuth flow (${res.status})`);
  }
  return res.json();
}

/**
 * Exchange OAuth callback code and state for tokens and complete registration.
 * POST /api/mcp/oauth/callback
 * @param {Object} payload { code, state, session_id?, ... }
 */
export async function apiCompleteMcpOAuth(payload) {
  const res = await apiFetch('/api/mcp/oauth/callback', {
    method: 'POST',
    body: JSON.stringify(payload || {}),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(parseApiErrorDetail(err) || `Failed to complete MCP OAuth flow (${res.status})`);
  }
  return res.json();
}

// ─── Builder Tool Catalog ────────────────────────────────────
/**
 * Retrieve all active native and connected MCP tools formatted for Agent Builder.
 * GET /api/capabilities/builder/tools
 */
export async function apiGetBuilderTools() {
  const res = await apiFetch('/api/capabilities/builder/tools');
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(parseApiErrorDetail(err) || `Failed to fetch builder tools (${res.status})`);
  }
  return res.json();
}

// ─── Tool Execution & Human-In-The-Loop (HITL) ───────────────
/**
 * Get execution record and parameters for a tool execution.
 * GET /api/tool-executions/{execution_id}
 * @param {string} executionId
 */
export async function apiGetToolExecution(executionId) {
  const path = `/api/tool-executions/${encodeURIComponent(executionId)}`;
  const res = await apiFetch(path);
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(parseApiErrorDetail(err) || `Failed to fetch tool execution (${res.status})`);
  }
  return res.json();
}

/**
 * Submit Human-In-The-Loop approval decision (approved / rejected).
 * POST /api/tool-executions/{execution_id}/approval
 * @param {string} executionId
 * @param {'approved' | 'rejected'} decision
 * @param {string} reason
 */
export async function apiSubmitToolApproval(executionId, decision, reason = '') {
  const path = `/api/tool-executions/${encodeURIComponent(executionId)}/approval`;
  const body = { decision };
  if (reason && typeof reason === 'string' && reason.trim()) {
    body.reason = reason.trim();
  }
  const res = await apiFetch(path, {
    method: 'POST',
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(parseApiErrorDetail(err) || `Failed to submit tool approval (${res.status})`);
  }
  return res.json();
}

/**
 * Resume a previously approved tool execution to produce the final output.
 * POST /api/tool-executions/{execution_id}/resume
 * @param {string} executionId
 */
export async function apiResumeToolExecution(executionId) {
  const path = `/api/tool-executions/${encodeURIComponent(executionId)}/resume`;
  const res = await apiFetch(path, {
    method: 'POST',
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(parseApiErrorDetail(err) || `Failed to resume tool execution (${res.status})`);
  }
  return res.json();
}
