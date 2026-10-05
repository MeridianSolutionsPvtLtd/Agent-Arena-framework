// ─── Dynamic Agent API ─────────────────────────────────
// CRUD, config (DNA), run, context/history, file upload, and exports for the
// dynamic-agent platform. Router prefix VERIFIED as `/api/agents`
// (Agent-Integration/routers/agents.py + agent_files.py), so every path carries
// `/api` — see config/env.js for the convention.
//
// Confirmed routes: POST /preview, POST /blueprint, GET "" (list), GET/PATCH/
// DELETE /{id}, POST /{id}/run, GET /{id}/threads[/{tid}/messages],
// POST /{id}/run-file, GET/PATCH /{id}/config, DELETE /{id}/history,
// GET /{id}/context, GET /{id}/blackboard, GET /{id}/sub-agent-histories,
// GET /{id}/export; and POST /files (agent_files.py).
//
// TODO(agent-integration): endpoints marked below reach the real route but their
// request/response SHAPE differs from what Playground historically sent (this
// app was built against a different agent API). These are reconciled in the
// agent-integration phase against the live backend with a session token; the
// paths here are already correct.
import { API_BASE } from '../config/env';
import {
  apiFetch,
  getAccessToken,
  getRefreshToken,
  refreshAccessToken,
  downloadAuthenticatedFile,
  parseApiErrorDetail,
} from './http';

/** DELETE/204-safe JSON reader: 204 (No Content) has no body to parse. */
async function jsonOrEmpty(res) {
  if (res.status === 204) return { success: true };
  return res.json();
}

// ─── Agent CRUD ────────────────────────────────────────
export async function apiPreviewAgent(query, name) {
  const res = await apiFetch('/api/agents/preview', {
    method: 'POST',
    body: JSON.stringify({ query, name }),
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(parseApiErrorDetail(err) || 'Failed to generate preview');
  }

  return await res.json();
}

// TODO(agent-integration): backend create route is POST /api/agents/blueprint
// (201). Verify it accepts this {blueprint|query|name} body (vs. requiring a
// full previewed blueprint) and what it returns.
export async function apiCreateAgent(query = null, name = null, blueprint = null) {
  const body = {};
  if (blueprint) body.blueprint = blueprint;
  if (query) body.query = query;
  if (name) body.name = name;

  console.log("Creating agent with payload:", body);

  const res = await apiFetch('/api/agents/blueprint', {
    method: 'POST',
    body: JSON.stringify(body),
  });

  if (!res.ok) {
    const errData = await res.json().catch(() => ({}));
    console.error("Agent creation error detail:", errData);

    // Construct a readable error message from FastAPI's detail structure
    let errorMessage = "Failed to create agent";
    if (typeof errData.detail === 'string') {
      errorMessage = errData.detail;
    } else if (Array.isArray(errData.detail)) {
      // Handle FastAPI validation error list
      errorMessage = errData.detail.map(d => `${d.loc.join('.')}: ${d.msg}`).join('; ');
    } else if (errData.detail) {
      errorMessage = JSON.stringify(errData.detail);
    }

    throw new Error(errorMessage);
  }

  return await res.json();
}

export async function apiDeleteAgent(agentId) {
  const res = await apiFetch(`/api/agents/${agentId}`, {
    method: 'DELETE',
  });
  if (!res.ok) throw new Error('Failed to delete agent');
  return jsonOrEmpty(res); // backend returns 204 No Content
}

export async function apiClearAgentHistory(agentId) {
  const res = await apiFetch(`/api/agents/${agentId}/history`, {
    method: 'DELETE',
  });
  if (!res.ok) throw new Error('Failed to clear agent history');
  return jsonOrEmpty(res);
}

export async function apiListAgents() {
  // Backend: GET /api/agents returns a bare list[AgentResponse]. Tolerate both a
  // bare array and a legacy {agents: [...]} envelope.
  const res = await apiFetch('/api/agents');
  if (!res.ok) throw new Error('Failed to fetch agents');
  const data = await res.json();
  if (Array.isArray(data)) return data;
  return data.agents || [];
}

// TODO(agent-integration): no dedicated rename route; backend is PATCH
// /api/agents/{id} (general update → AgentResponse). Verify it accepts {name}.
export async function apiUpdateAgentName(agentId, name) {
  const res = await apiFetch(`/api/agents/${agentId}`, {
    method: 'PATCH',
    body: JSON.stringify({ name }),
  });
  if (!res.ok) throw new Error('Failed to update agent name');
  return await res.json();
}

// ─── Agent Config (Fine-Tuning DNA) ───────────────────
export async function apiGetAgentConfig(agentId) {
  const res = await apiFetch(`/api/agents/${agentId}/config`);
  if (!res.ok) throw new Error('Failed to fetch agent config');
  return await res.json();
}

export async function apiUpdateAgentConfig(agentId, config) {
  const res = await apiFetch(`/api/agents/${agentId}/config`, {
    method: 'PATCH',
    body: JSON.stringify(config),
  });
  if (!res.ok) throw new Error('Failed to update agent config');
  return await res.json();
}

// ─── Chat / Run Agent ──────────────────────────────────
export async function apiRunAgent(agentId, queryOrMessage, conversationHistory = '', threadId = null, traceId = null, fileIds = []) {
  const message = typeof queryOrMessage === 'object'
    ? (queryOrMessage.message || queryOrMessage.query || queryOrMessage.text || '')
    : (queryOrMessage || '');

  const effectiveThreadId = typeof queryOrMessage === 'object'
    ? (queryOrMessage.thread_id || threadId)
    : threadId;

  const effectiveFileIds = typeof queryOrMessage === 'object'
    ? (queryOrMessage.file_ids || fileIds)
    : fileIds;

  const body = {
    message: String(message).trim() || 'Execute default task',
    thread_id: effectiveThreadId || null,
  };

  if (effectiveFileIds && effectiveFileIds.length > 0) {
    body.file_ids = effectiveFileIds;
  }

  const payload = {};
  if (traceId) payload.trace_id = traceId;
  if (conversationHistory) payload.conversation_history = conversationHistory;
  if (typeof queryOrMessage === 'object' && queryOrMessage.payload) {
    Object.assign(payload, queryOrMessage.payload);
  }
  if (Object.keys(payload).length > 0) {
    body.payload = payload;
  }

  const res = await apiFetch(`/api/agents/${encodeURIComponent(agentId)}/run`, {
    method: 'POST',
    body: JSON.stringify(body),
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(parseApiErrorDetail(err) || `Agent execution failed (${res.status})`);
  }

  return await res.json();
}

// ─── Context / History ─────────────────────────────────
export async function apiGetAgentContext(agentId, limit = 60) {
  const res = await apiFetch(`/api/agents/${agentId}/context?limit=${limit}`);
  if (!res.ok) throw new Error('Failed to fetch agent context');
  return await res.json();
}

export async function apiGetSubAgentHistories(agentId) {
  // Backend path uses hyphens: /sub-agent-histories (not /sub_agent_histories).
  const res = await apiFetch(`/api/agents/${agentId}/sub-agent-histories`);
  if (!res.ok) throw new Error('Failed to fetch sub-agent histories');
  return await res.json();
}

// ─── Export ────────────────────────────────────────────
// TODO(agent-integration): backend exposes a single GET /api/agents/{id}/export
// (format via query). Confirm the supported `format` values and the exe
// download-token flow below against the live backend.
/** Fast: agent blueprint JSON — use with runner_stub.py + .env on the user's machine. */
export async function apiExportAgentBlueprint(agentId) {
  return downloadAuthenticatedFile(
    `/api/agents/${encodeURIComponent(agentId)}/export?format=blueprint`,
    `agent_${agentId}_blueprint.json`
  );
}

/**
 * Recommended: portable ZIP (agent.json + runner_stub.py + README). Fast, small file.
 */
export async function apiExportAgentZip(agentId) {
  return downloadAuthenticatedFile(
    `/api/agents/${encodeURIComponent(agentId)}/export?format=zip`,
    `agent_${agentId}_portable.zip`
  );
}

/**
 * Customer download: thin Windows .exe with agent id/name + API URL.
 * It logs in and calls the hosted backend, so framework code is not shipped.
 */
export async function apiExportAgentExe(agentId) {
  const token = getAccessToken();
  let res = await fetch(
    `${API_BASE}/api/agents/${encodeURIComponent(agentId)}/export?format=exe`,
    { headers: token ? { Authorization: `Bearer ${token}` } : {} }
  );

  if (res.status === 401 && getRefreshToken()) {
    const refreshed = await refreshAccessToken();
    if (refreshed) {
      res = await fetch(
        `${API_BASE}/api/agents/${encodeURIComponent(agentId)}/export?format=exe`,
        { headers: { Authorization: `Bearer ${getAccessToken()}` } }
      );
    }
  }

  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(parseApiErrorDetail(err) || `Export failed (${res.status})`);
  }

  const data = await res.json();
  if (!data.download_token) {
    throw new Error(data.message || 'Export did not return a download link.');
  }

  const fileUrl = `${API_BASE}${data.download_url || `/api/agents/export/file?token=${encodeURIComponent(data.download_token)}`}`;
  window.location.assign(fileUrl);
  return data;
}

// ─── File Upload ───────────────────────────────────────
// TODO(agent-integration): backend upload route is POST /api/agents/files
// (agent_files.py). Verify the multipart field name and the response shape
// (e.g. { file_id, ... }).
export async function apiUploadFile(fileOrFiles) {
  // Rebuild FormData on each attempt — body cannot be retried after a failed request in all cases.
  const postUpload = () => {
    const formData = new FormData();
    if (Array.isArray(fileOrFiles)) {
      for (const f of fileOrFiles) {
        formData.append('files', f);
      }
    } else if (fileOrFiles) {
      formData.append('files', fileOrFiles);
    }
    const token = getAccessToken();
    return fetch(`${API_BASE}/api/agents/files`, {
      method: 'POST',
      headers: token ? { Authorization: `Bearer ${token}` } : {},
      body: formData,
    });
  };

  let res = await postUpload();

  if (res.status === 401 && getRefreshToken()) {
    const refreshed = await refreshAccessToken();
    if (refreshed) {
      res = await postUpload();
    }
  }

  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    const detail = parseApiErrorDetail(err);
    throw new Error(detail || `Upload failed (${res.status})`);
  }

  return res.json();
}
