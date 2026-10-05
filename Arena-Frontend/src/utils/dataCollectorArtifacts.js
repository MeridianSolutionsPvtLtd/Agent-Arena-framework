import { resolveApiUrl } from '../services/api';

const ARTIFACT_LABELS = {
  chart: 'Chart',
  csv: 'CSV Dataset',
  json: 'JSON Data',
  log: 'Workflow Log',
  answer: 'Answer Markdown',
};

function inferKindFromUrl(url = '') {
  const clean = url.split('?')[0].toLowerCase();
  if (/\.(png|jpg|jpeg|webp|gif)$/.test(clean)) return 'chart';
  if (clean.endsWith('.csv')) return 'csv';
  if (clean.endsWith('.json')) return 'json';
  if (clean.endsWith('.log') || clean.endsWith('.txt')) return 'log';
  if (clean.endsWith('.md') || clean.endsWith('.markdown')) return 'answer';
  return 'file';
}

function filenameFromUrl(url = '') {
  const clean = url.split('?')[0].split('#')[0];
  const part = clean.split('/').filter(Boolean).pop();
  return part ? decodeURIComponent(part) : 'artifact';
}

function normalizeArtifact(key, value) {
  if (!value) return null;
  const item = typeof value === 'string' ? { url: value } : value;
  const rawUrl = item.url || item.download_url || item.path || '';
  if (!rawUrl) return null;
  const kind = item.kind || key || inferKindFromUrl(rawUrl);
  return {
    kind,
    label: ARTIFACT_LABELS[kind] || item.filename || 'Generated Output',
    filename: item.filename || filenameFromUrl(rawUrl),
    mime: item.mime || '',
    url: resolveApiUrl(rawUrl),
    downloadUrl: resolveApiUrl(item.download_url || rawUrl),
  };
}

export function normalizeDataCollectorArtifacts(artifacts) {
  if (!artifacts || typeof artifacts !== 'object') return [];
  return Object.entries(artifacts)
    .map(([key, value]) => normalizeArtifact(key, value))
    .filter(Boolean);
}

export function parseDataCollectorPayload(text) {
  if (!text || typeof text !== 'string') return null;
  const trimmed = text.trim();
  if (!trimmed.startsWith('{')) return null;
  try {
    const data = JSON.parse(trimmed);
    if (!data || typeof data !== 'object' || !data.artifacts) return null;
    return data;
  } catch {
    return null;
  }
}

export function extractDataCollectorArtifacts(textOrArtifacts, explicitArtifacts = null) {
  const direct = normalizeDataCollectorArtifacts(explicitArtifacts || textOrArtifacts);
  if (direct.length > 0) return direct;

  const payload = parseDataCollectorPayload(textOrArtifacts);
  if (payload?.artifacts) {
    return normalizeDataCollectorArtifacts(payload.artifacts);
  }

  if (!textOrArtifacts || typeof textOrArtifacts !== 'string') return [];
  const seen = new Set();
  const artifacts = [];
  const markdownLink = /\[([^\]]+)\]\((\/outputs\/[^)\s]+|https?:\/\/[^)\s]+\/outputs\/[^)\s]+)\)/gi;
  let match;
  while ((match = markdownLink.exec(textOrArtifacts)) !== null) {
    const label = match[1] || '';
    const rawUrl = match[2] || '';
    const kind = inferKindFromUrl(rawUrl);
    if (!rawUrl || seen.has(rawUrl) || kind === 'file') continue;
    seen.add(rawUrl);
    artifacts.push({
      kind,
      label: ARTIFACT_LABELS[kind] || label || 'Generated Output',
      filename: filenameFromUrl(rawUrl),
      url: resolveApiUrl(rawUrl),
      downloadUrl: resolveApiUrl(rawUrl),
    });
  }
  return artifacts;
}

export function formatDataCollectorPayloadForMarkdown(text) {
  const payload = parseDataCollectorPayload(text);
  if (!payload) return '';

  const sections = [];
  const answer = (payload.answer_markdown || payload.answer_preview || '').trim();
  if (answer) sections.push(answer);

  const links = normalizeDataCollectorArtifacts(payload.artifacts).map((artifact) => {
    return `- [${artifact.filename || artifact.label}](${artifact.url})`;
  });
  if (links.length > 0) {
    sections.push(`### Generated Outputs\n${links.join('\n')}`);
  }

  if (sections.length > 0) return sections.join('\n\n');
  if (payload.message) return `### Data Collector Visualizer\n\n${payload.message}`;
  return '';
}
