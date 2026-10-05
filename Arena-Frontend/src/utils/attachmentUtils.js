/**
 * Normalizes messages that contain raw attachment manifests.
 *
 * Backend ingestion creates manifest blocks in user turn text:
 *   [Attachments]
 *   - filename.pdf [document, ok] id=file_xxx
 *
 * This function extracts the attachment metadata into attachment objects
 * (if not already present) and strips the raw manifest block from user text
 * so the raw metadata is never displayed inside user chat bubbles.
 */
export function normalizeMessageAttachments(text, existingAttachments = null) {
  if (!text || typeof text !== 'string') {
    return { cleanText: text || '', attachments: existingAttachments || null };
  }

  const match = text.match(/(?:^|\n\n?)\[Attachments\]\n?([\s\S]*)$/);
  if (!match) {
    return { cleanText: text, attachments: existingAttachments || null };
  }

  const cleanText = text.replace(/(?:^|\n\n?)\[Attachments\]\n?[\s\S]*$/, '').trim();
  let attachments = Array.isArray(existingAttachments) && existingAttachments.length > 0 ? existingAttachments : [];

  if (attachments.length === 0 && match[1]) {
    const lines = match[1].trim().split('\n');
    const parsed = [];
    for (const rawLine of lines) {
      const line = rawLine.trim();
      if (!line) continue;
      const m1 = line.match(/^[•\-*]\s+(.+?)\s+\[([^,]+),\s*([^\]]+)\]\s+id=([^\s]+)/);
      if (m1) {
        parsed.push({
          filename: m1[1].trim(),
          kind: m1[2].trim(),
          extraction_status: m1[3].trim(),
          file_id: m1[4].trim(),
        });
      } else {
        const m2 = line.match(/^[•\-*]\s+(.+?)\s+id=([^\s]+)/);
        if (m2) {
          parsed.push({
            filename: m2[1].trim(),
            file_id: m2[2].trim(),
          });
        } else {
          const m3 = line.match(/^[•\-*]\s+(.+)/);
          if (m3) {
            parsed.push({
              filename: m3[1].trim(),
            });
          }
        }
      }
    }
    if (parsed.length > 0) {
      attachments = parsed;
    }
  }

  return {
    cleanText,
    attachments: attachments.length > 0 ? attachments : null,
  };
}
