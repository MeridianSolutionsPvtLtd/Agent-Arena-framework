// ─── Backend Services API ──────────────────────────────
// Azure/OpenAI-backed services and credential management. Router prefixes
// VERIFIED against Agent-Integration/routers/*.py — every service is mounted at
// `/api/<service>` (openai, translator, image, content_safety, search, speech,
// document, vision, video, language) and credentials at `/api/credentials`.
// There is NO `/arena` segment (the docs were wrong). Most services require
// Azure credentials configured via the credentials endpoints; absent those, the
// backend falls back to env.
//
// SCOPE (Phase 1): generic transport helpers + credentials + the service calls
// the ported multimodal chat needs (Phase 5). Fixed specialist-agent endpoints
// (call-audit, recruitment, legal, …) are added in Phase 6 next to their UIs,
// so each stays co-located with the component that owns its request shape.
//
// Historical name note: the exported `arena*` identifiers are kept so future
// call sites don't churn; they no longer imply an `/arena` route.
import { apiFetch, parseApiErrorDetail } from './http';

// ─── Generic Transport ─────────────────────────────────
async function unwrap(res, fallback) {
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(parseApiErrorDetail(err) || fallback);
  }
  return res.json();
}

/** GET a JSON resource under /api (e.g. '/credentials'). `path` starts with '/'. */
export async function arenaGet(path, fallback = 'Request failed') {
  return unwrap(await apiFetch(`/api${path}`), fallback);
}

/** POST JSON to an /api route and parse the JSON response. */
export async function arenaPostJson(path, body, fallback = 'Request failed') {
  return unwrap(
    await apiFetch(`/api${path}`, { method: 'POST', body: JSON.stringify(body) }),
    fallback
  );
}

/** POST multipart/form-data to an /api route (headers:{} lets the browser set the boundary). */
export async function arenaPostForm(path, formData, fallback = 'Upload failed') {
  return unwrap(
    await apiFetch(`/api${path}`, { method: 'POST', headers: {}, body: formData }),
    fallback
  );
}

/** POST JSON to an /api route that returns a binary Blob (e.g. speech synthesis). */
export async function arenaPostBlob(path, body, fallback = 'Request failed') {
  const res = await apiFetch(`/api${path}`, { method: 'POST', body: JSON.stringify(body) });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(parseApiErrorDetail(err) || fallback);
  }
  return res.blob();
}

// ─── Credentials ───────────────────────────────────────
// SECURITY: the API returns credential NAMES only, never secret values. Nothing
// in the UI should attempt to read or display a saved secret after it is stored.
export function getCredentialSchema() {
  return arenaGet('/credentials/schema', 'Failed to load credential schema');
}

export function listCredentialNames() {
  return arenaGet('/credentials', 'Failed to load credentials');
}

export function saveCredential(payload) {
  return arenaPostJson('/credentials', payload, 'Failed to save credential');
}

export async function deleteCredential(keyName) {
  return unwrap(
    await apiFetch(`/api/credentials/${encodeURIComponent(keyName)}`, { method: 'DELETE' }),
    'Failed to delete credential'
  );
}

// ─── Azure / OpenAI Services ───────────────────────────
export const arenaOpenAIChat = (payload) => arenaPostJson('/openai/chat', payload, 'Chat request failed');
export const arenaTranslate = (payload) => arenaPostJson('/translator/translate', payload, 'Translation failed');
export const arenaGenerateImage = (payload) => arenaPostJson('/image/generate', payload, 'Image generation failed');
export const arenaContentSafety = (payload) => arenaPostJson('/content_safety/analyze', payload, 'Safety check failed');
export const arenaSearchQuery = (payload) => arenaPostJson('/search/query', payload, 'Search failed');

/** Text-to-speech → audio Blob. */
export const arenaTTS = (payload) => arenaPostBlob('/speech/tts', payload, 'Speech synthesis failed');

/** Speech-to-text (multipart audio). */
export const arenaSTT = (formData) => arenaPostForm('/speech/stt', formData, 'Transcription failed');

/** Document Intelligence extraction (multipart file). */
export const arenaAnalyzeDocument = (formData) => arenaPostForm('/document/analyze', formData, 'Document analysis failed');

/** Vision analysis (multipart image, or JSON with a URL — caller decides). */
export const arenaAnalyzeVision = (formData) => arenaPostForm('/vision/analyze', formData, 'Vision analysis failed');

/** Video upload (multipart). */
export const arenaUploadVideo = (formData) => arenaPostForm('/video/upload', formData, 'Video upload failed');

/**
 * Language service. `op` is one of:
 *   analyze | key_phrases | entities | pii | detect_language | summarize
 */
export const arenaLanguage = (op, payload) => arenaPostJson(`/language/${op}`, payload, 'Language analysis failed');

/** Call Audit: accept an audio file upload and return/stream analysis results. */
export async function apiAnalyzeCallAudit(fileOrFormData) {
  const formData = fileOrFormData instanceof FormData ? fileOrFormData : (() => {
    const fd = new FormData();
    fd.append('file', fileOrFormData);
    return fd;
  })();
  return arenaPostForm('/call-audit/analyze', formData, 'Call audit analysis failed');
}

export const arenaCallAudit = apiAnalyzeCallAudit;
