import { formatDataCollectorPayloadForMarkdown } from './dataCollectorArtifacts';

/**
 * Turns structured tool outputs (often JSON strings from extract/search tools)
 * into readable Markdown for ReactMarkdown. Plain prose is returned unchanged.
 */

function escapeCell(val) {
  return String(val ?? '')
    .replace(/\|/g, '\\|')
    .replace(/\n/g, ' ')
    .slice(0, 400);
}

function previewRowsToMarkdown(structure) {
  const rows = structure?.preview_rows;
  if (!Array.isArray(rows) || rows.length === 0) return '';
  const cols = structure.columns?.length
    ? structure.columns
    : Object.keys(rows[0]);
  const header = `| ${cols.map(escapeCell).join(' | ')} |`;
  const sep = `| ${cols.map(() => '---').join(' | ')} |`;
  const body = rows
    .slice(0, 80)
    .map((r) => `| ${cols.map((c) => escapeCell(r[c])).join(' | ')} |`)
    .join('\n');
  const trunc =
    structure.truncated || rows.length > 80
      ? `\n\n_*Showing a subset of rows._*\n`
      : '';
  return `${header}\n${sep}\n${body}${trunc}`;
}

/**
 * @param {string} text
 * @returns {string} Markdown-safe string for display
 */
export function formatAgentToolOutputForMarkdown(text) {
  if (text == null || typeof text !== 'string') return text ?? '';
  const trimmed = text.trim();
  if (!trimmed.startsWith('{') && !trimmed.startsWith('[')) return text;

  let data;
  try {
    data = JSON.parse(trimmed);
  } catch {
    return text;
  }

  if (data == null || typeof data !== 'object') return text;

  // ── Data collector visualizer: answer + generated output links ─────────
  if (data.artifacts && (data.answer_markdown || data.answer_preview)) {
    const formatted = formatDataCollectorPayloadForMarkdown(text);
    if (formatted) return formatted;
  }

  // ── File extractor: PDF / TXT / MD ─────────────────────────────
  if (typeof data.text_preview === 'string') {
    const bits = [];
    if (data.file_type) bits.push(`**File type:** \`${data.file_type}\``);
    if (typeof data.text_length === 'number')
      bits.push(`**Extracted length:** ${data.text_length.toLocaleString()} characters`);
    if (data.extraction_quality)
      bits.push(`**Extraction quality:** ${data.extraction_quality}`);
    const meta = bits.length ? `${bits.join(' · ')}\n\n` : '';
    let body = data.text_preview;
    if (data.ocr_metadata?.ocr_used) {
      body += `\n\n---\n\n_OCR used (${data.ocr_metadata.ocr_engine || 'engine unknown'})_`;
    }
    return `${meta}### Extracted content\n\n${body}`;
  }

  // ── CSV / tabular via structure ────────────────────────────────
  if (data.structure?.preview_rows) {
    const name = data.structure.name || 'data';
    const rowsMd = previewRowsToMarkdown(data.structure);
    const header = `**File type:** \`${data.file_type || 'tabular'}\` · **Rows (sample):** ${data.structure.row_count ?? '—'}\n\n`;
    return `${header}### ${name}\n\n${rowsMd || '_No rows._'}`;
  }

  // ── Excel: multiple sheets ─────────────────────────────────────
  if (data.sheets && typeof data.sheets === 'object') {
    const parts = [];
    if (data.file_type) parts.push(`**File type:** \`${data.file_type}\``);
    if (data.sheet_count != null)
      parts.push(`**Sheets:** ${data.sheet_count}`);
    let md = parts.length ? `${parts.join(' · ')}\n\n` : '';
    for (const [sheetName, sheet] of Object.entries(data.sheets)) {
      const sub = previewRowsToMarkdown(sheet);
      md += `### ${sheetName}\n\n${sub || '_Empty._'}\n\n`;
    }
    return md.trimEnd();
  }

  // ── Plain JSON file preview ─────────────────────────────────────
  if (data.file_type === '.json' && (data.preview != null || data.keys != null)) {
    let md = '### JSON file\n\n';
    if (Array.isArray(data.keys)) md += `**Keys:** ${data.keys.join(', ')}\n\n`;
    if (typeof data.preview === 'string') md += data.preview;
    return md;
  }

  // ── Explicit error payloads ────────────────────────────────────
  if (typeof data.error === 'string') {
    return `### Error\n\n${data.error}`;
  }

  // ── Generic fields used by various tools ───────────────────────
  if (typeof data.preview === 'string') return data.preview;
  if (typeof data.response === 'string') return data.response;
  if (typeof data.summary === 'string') return data.summary;
  if (typeof data.answer === 'string') return data.answer;

  // Unknown JSON: show readable indented block instead of a single-line blob
  try {
    return (
      '_Structured result_\n\n```json\n' +
      JSON.stringify(data, null, 2).slice(0, 12000) +
      (JSON.stringify(data).length > 12000 ? '\n…' : '') +
      '\n```'
    );
  } catch {
    return text;
  }
}
