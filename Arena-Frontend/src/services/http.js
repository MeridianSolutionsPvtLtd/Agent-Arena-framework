// ─── HTTP Core ─────────────────────────────────────────
// The one authenticated transport for the whole app: token storage, the
// fetch wrapper with 401→refresh retry, WebSocket/asset URL helpers, blob
// downloads, and FastAPI error parsing. Feature modules (auth.api, agents.api,
// arena.api, chats.api) build on these primitives — no other file should talk
// to fetch() or localStorage tokens directly.
import { API_BASE, STORAGE_KEYS } from '../config/env';

export { API_BASE };

// ─── URL Helpers ───────────────────────────────────────
/** Resolve backend-relative URLs such as /outputs/... for UI assets. */
export function resolveApiUrl(pathOrUrl) {
  if (!pathOrUrl) return '';
  if (/^https?:\/\//i.test(pathOrUrl)) return pathOrUrl;
  const base = API_BASE.replace(/\/$/, '');
  const path = String(pathOrUrl).startsWith('/') ? pathOrUrl : `/${pathOrUrl}`;
  return `${base}${path}`;
}

/** WebSocket URL for live execution traces (same host as API_BASE). */
export function getTraceWebSocketUrl(traceId) {
  if (!traceId) return '';

  let wsBase;
  if (/^https?:\/\//i.test(API_BASE)) {
    wsBase = API_BASE.replace(/^http/i, (m) => (m.toLowerCase() === 'https' ? 'wss' : 'ws'));
  } else if (typeof window !== 'undefined') {
    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const path = String(API_BASE || '/api').replace(/\/$/, '');
    wsBase = `${proto}//${window.location.host}${path.startsWith('/') ? path : `/${path}`}`;
  } else {
    wsBase = String(API_BASE || '/api').replace(/\/$/, '');
  }

  return `${wsBase.replace(/\/$/, '')}/ws/trace/${encodeURIComponent(traceId)}`;
}

// ─── Token Management ──────────────────────────────────
export function getAccessToken() {
  return localStorage.getItem(STORAGE_KEYS.accessToken);
}

export function getRefreshToken() {
  return localStorage.getItem(STORAGE_KEYS.refreshToken);
}

export function setTokens(access, refresh) {
  localStorage.setItem(STORAGE_KEYS.accessToken, access);
  localStorage.setItem(STORAGE_KEYS.refreshToken, refresh);
}

export function clearTokens() {
  localStorage.removeItem(STORAGE_KEYS.accessToken);
  localStorage.removeItem(STORAGE_KEYS.refreshToken);
}

// ─── Error Parsing ─────────────────────────────────────
/** Parse FastAPI `detail` (string or validation array) from error JSON. */
export function parseApiErrorDetail(err) {
  if (!err || typeof err !== 'object') return null;
  const d = err.detail;
  if (typeof d === 'string') return d;
  if (Array.isArray(d)) {
    return d
      .map((item) => (item && typeof item === 'object' && item.msg ? item.msg : String(item)))
      .filter(Boolean)
      .join(', ');
  }
  return null;
}

// ─── Authenticated Fetch Wrapper ───────────────────────
export async function apiFetch(path, options = {}) {
  const token = getAccessToken();
  const headers = {
    'Content-Type': 'application/json',
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...options.headers,
  };

  let res = await fetch(`${API_BASE}${path}`, { ...options, headers });

  // If 401, try refreshing the token
  if (res.status === 401 && getRefreshToken()) {
    const refreshed = await refreshAccessToken();
    if (refreshed) {
      headers.Authorization = `Bearer ${getAccessToken()}`;
      res = await fetch(`${API_BASE}${path}`, { ...options, headers });
    }
  }

  return res;
}

export async function refreshAccessToken() {
  try {
    const res = await fetch(`${API_BASE}/api/auth/refresh`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh_token: getRefreshToken() }),
    });
    if (!res.ok) return false;
    const data = await res.json();
    // /api/auth/refresh returns only a new access_token (the refresh token is
    // long-lived and NOT re-issued). Preserve the existing refresh token — passing
    // data.refresh_token (undefined) would clobber it with the string "undefined"
    // and break every session after the first access-token expiry.
    setTokens(data.access_token, data.refresh_token || getRefreshToken());
    return true;
  } catch {
    return false;
  }
}

// ─── Authenticated File Download ───────────────────────
/** Trigger browser download from an authenticated GET that returns a file/blob. */
export async function downloadAuthenticatedFile(path, fallbackFilename) {
  const token = getAccessToken();
  let res = await fetch(`${API_BASE}${path}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });

  if (res.status === 401 && getRefreshToken()) {
    const refreshed = await refreshAccessToken();
    if (refreshed) {
      res = await fetch(`${API_BASE}${path}`, {
        headers: { Authorization: `Bearer ${getAccessToken()}` },
      });
    }
  }

  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(
      typeof err.detail === 'string' ? err.detail : err.detail || `Download failed (${res.status})`
    );
  }

  const blob = await res.blob();
  const disposition = res.headers.get('Content-Disposition') || '';
  const match = disposition.match(/filename="?([^";\n]+)"?/i);
  const filename = match ? match[1] : fallbackFilename;

  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}
