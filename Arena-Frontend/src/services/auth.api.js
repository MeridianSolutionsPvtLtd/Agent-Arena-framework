// ─── Auth API ──────────────────────────────────────────
// Canonical auth against the common Agent-Integration backend.
// Contract VERIFIED against Agent-Integration/routers/auth.py + models/user.py:
//   POST /api/auth/login     JSON {email, password}        -> {access_token, refresh_token, token_type}
//   POST /api/auth/register  JSON {name, email, password}  -> {message}  (NO tokens — log in afterwards)
//   POST /api/auth/refresh   JSON {refresh_token}          -> new tokens (see http.js)
//   GET  /api/auth/me                                      -> user profile
// NOTE: login is JSON + email (NOT an OAuth2 form with `username`), and
// /api/auth/me DOES exist. Login/signup use raw fetch (no auth header / no
// refresh-retry needed pre-session); apiGetMe goes through apiFetch.
import { API_BASE } from '../config/env';
import { apiFetch, setTokens, clearTokens, parseApiErrorDetail } from './http';

/** Log in with email + password. Stores the returned token pair. */
export async function apiLogin(email, password) {
  const res = await fetch(`${API_BASE}/api/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password }),
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(parseApiErrorDetail(err) || 'Login failed');
  }

  const data = await res.json();
  setTokens(data.access_token, data.refresh_token);
  return data;
}

/**
 * Register a new account. The backend returns a confirmation message, NOT
 * tokens, so callers must log in afterwards to obtain a session (see Login.jsx).
 */
export async function apiSignup(name, email, password) {
  const res = await fetch(`${API_BASE}/api/auth/register`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, email, password }),
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(parseApiErrorDetail(err) || 'Signup failed');
  }

  return res.json();
}

/** GET the authenticated user's profile (id, name, email, usage, …). */
export async function apiGetMe() {
  const res = await apiFetch('/api/auth/me');
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(parseApiErrorDetail(err) || 'Failed to load profile');
  }
  return res.json();
}

/**
 * Change the signed-in user's password.
 * POST /api/auth/change-password {current_password, new_password} -> {message}
 * VERIFIED against Agent-Integration/routers/auth.py (AuthChangePasswordRequest).
 * A wrong current password comes back as 400 "Current password is incorrect",
 * which parseApiErrorDetail surfaces verbatim for the form to display.
 */
export async function apiChangePassword(currentPassword, newPassword) {
  const res = await apiFetch('/api/auth/change-password', {
    method: 'POST',
    body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(parseApiErrorDetail(err) || 'Failed to change password');
  }
  return res.json();
}

export function apiLogout() {
  clearTokens();
}
