"""
Per-modality extraction helpers for the ingestion layer.

Every extractor takes raw bytes and returns a plain result dict:
    {"text", "engine", "status", "truncated", "error", "metadata"}

Extractors never raise on bad content. A file that cannot be read comes back
with status "failed" and an error string, so one unreadable attachment can
never abort an agent run.
"""
import asyncio
import io
import logging
import os
import tempfile
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# ─── Extraction status values ───
STATUS_OK = "ok"
STATUS_PARTIAL = "partial"    # text recovered but degraded (OCR, truncation, neutralised content)
STATUS_EMPTY = "empty"        # extractor ran, found nothing (silent audio, blank scan)
STATUS_FAILED = "failed"      # extractor errored; file unusable as context

_SERVICES_PKG = "services"


def _load_service(module_name: str, attr: str):
    """Lazily import a modality service. Returns None if unavailable."""
    try:
        module = __import__(f"{_SERVICES_PKG}.{module_name}", fromlist=[attr])
        return getattr(module, attr, None)
    except Exception as e:
        logger.warning(f"[INGEST] Service {module_name}.{attr} unavailable: {e}")
        return None


async def _resolve_credentials(user_id: Optional[str], keys: list, per_user: bool = False) -> Dict[str, Any]:
    """
    Credentials for a provider call.

    Agent traffic defaults to platform credentials (an empty dict makes the
    services fall through to settings.*), because a user who built a custom
    agent has not necessarily configured their own Azure keys. Arena traffic
    passes per_user=True to keep using the encrypted per-user credentials.
    """
    if not per_user or not user_id:
        return {}

    get_user_credentials = _load_service("keyvault_service", "get_user_credentials")
    if get_user_credentials is None:
        return {}
    try:
        return await get_user_credentials(user_id, keys) or {}
    except Exception as e:
        logger.warning(f"[INGEST] Per-user credential lookup failed for {user_id}: {e}")
        return {}


def _result(
    text: str = "",
    engine: str = "none",
    status: str = STATUS_OK,
    truncated: bool = False,
    error: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    return {
        "text": text,
        "engine": engine,
        "status": status,
        "truncated": truncated,
        "error": error,
        "metadata": metadata or {},
    }


def _truncate(text: str, limit: int) -> tuple:
    """Returns (text, was_truncated)."""
    body = text or ""
    if len(body) <= limit:
        return body, False
    return body[:limit], True


# ─────────────────────────── TEXT ───────────────────────────
async def extract_text(data: bytes, filename: str, user_id: str = None,
                       max_chars: int = 60000, per_user_credentials: bool = False) -> Dict[str, Any]:
    for encoding in ("utf-8", "utf-16", "latin-1"):
        try:
            decoded = data.decode(encoding)
            body, truncated = _truncate(decoded, max_chars)
            return _result(
                text=body,
                engine=f"decode:{encoding}",
                status=STATUS_OK if body.strip() else STATUS_EMPTY,
                truncated=truncated,
                metadata={"encoding": encoding, "raw_chars": len(decoded)},
            )
        except UnicodeDecodeError:
            continue

    decoded = data.decode("utf-8", errors="replace")
    body, truncated = _truncate(decoded, max_chars)
    return _result(
        text=body,
        engine="decode:replace",
        status=STATUS_PARTIAL,
        truncated=truncated,
        error="File contained bytes that are not valid text; undecodable characters were replaced.",
    )


# ─────────────────────────── AUDIO ───────────────────────────
async def extract_audio(data: bytes, filename: str, user_id: str = None,
                        max_chars: int = 60000, per_user_credentials: bool = False) -> Dict[str, Any]:
    speech_to_text = _load_service("speech_service", "speech_to_text")
    if speech_to_text is None:
        return _result(status=STATUS_FAILED, error="Speech service is unavailable on this deployment.")

    creds = await _resolve_credentials(
        user_id, ["AZURE_SPEECH_KEY", "AZURE_SPEECH_REGION"], per_user_credentials
    )

    try:
        result = await speech_to_text(data, credentials=creds, auto_detect_language=False)
    except Exception as e:
        logger.error(f"[INGEST] STT failed for {filename}: {e}", exc_info=True)
        return _result(engine="azure_speech", status=STATUS_FAILED, error=f"Transcription failed: {e}")

    transcript = (result or {}).get("text", "") or ""
    segments = (result or {}).get("segments", []) or []

    if not transcript.strip():
        return _result(
            engine="azure_speech",
            status=STATUS_EMPTY,
            error="No speech was detected in the audio.",
            metadata={"segment_count": 0},
        )

    body, truncated = _truncate(transcript, max_chars)
    logger.info(f"[INGEST] Transcribed {filename}: {len(segments)} segments, {len(transcript)} chars")
    return _result(
        text=body,
        engine="azure_speech",
        status=STATUS_PARTIAL if truncated else STATUS_OK,
        truncated=truncated,
        metadata={"segment_count": len(segments), "transcript_chars": len(transcript)},
    )


# ─────────────────────────── DOCUMENTS ───────────────────────────
def _pymupdf_extract(data: bytes, max_chars: int) -> Optional[Dict[str, Any]]:
    """Local PDF text-layer extraction. No network, no per-page billing."""
    try:
        import fitz
    except Exception:
        return None

    try:
        with fitz.open(stream=data, filetype="pdf") as doc:
            pages = []
            total = 0
            for i, page in enumerate(doc):
                page_text = page.get_text() or ""
                if not page_text.strip():
                    continue
                block = f"[page {i + 1}]\n{page_text.strip()}"
                pages.append(block)
                total += len(block)
                if total >= max_chars:
                    break
            joined = "\n\n".join(pages)
            page_count = doc.page_count
    except Exception as e:
        logger.warning(f"[INGEST] PyMuPDF extraction failed: {e}")
        return None

    if not joined.strip():
        return None

    body, truncated = _truncate(joined, max_chars)
    return _result(
        text=body,
        engine="pymupdf",
        status=STATUS_PARTIAL if truncated else STATUS_OK,
        truncated=truncated,
        metadata={"page_count": page_count},
    )


def _ocr_extract(data: bytes, max_chars: int) -> Optional[Dict[str, Any]]:
    """Last-resort OCR for scanned PDFs. Reuses the existing tool engine."""
    tmp_path = None
    try:
        from core.tools.extract_data_from_file import _ocr_fallback

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp.write(data)
            tmp_path = tmp.name

        ocr = _ocr_fallback(tmp_path) or {}
        text = (ocr.get("ocr_text") or "").strip()
        if not text:
            return None

        body, truncated = _truncate(text, max_chars)
        return _result(
            text=body,
            engine=f"ocr:{ocr.get('ocr_engine') or 'unknown'}",
            status=STATUS_PARTIAL,    # OCR output is always lower confidence
            truncated=truncated,
            metadata={"ocr_used": True},
        )
    except Exception as e:
        logger.warning(f"[INGEST] OCR fallback failed: {e}")
        return None
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


def _flatten_document_result(result: Any, max_chars: int) -> Dict[str, Any]:
    """Flatten an Azure Document Intelligence payload into prompt-ready text."""
    data = result if isinstance(result, dict) else {}
    sections = []

    content = (data.get("content") or "").strip()
    if content:
        sections.append(content)

    kv_pairs = data.get("key_value_pairs") or []
    if kv_pairs:
        lines = []
        for pair in kv_pairs[:120]:
            key = ((pair.get("key") or {}).get("content") or "").strip()
            value = ((pair.get("value") or {}) or {}).get("content") if pair.get("value") else ""
            if key:
                lines.append(f"{key}: {(value or '').strip()}")
        if lines:
            sections.append("[Detected fields]\n" + "\n".join(lines))

    tables = data.get("tables") or []
    for t_index, table in enumerate(tables[:10]):
        grid = {}
        for cell in table.get("cells") or []:
            grid.setdefault(cell.get("row_index", 0), {})[cell.get("column_index", 0)] = (
                cell.get("content") or ""
            ).strip()
        if not grid:
            continue
        rows = []
        for row_index in sorted(grid)[:60]:
            row = grid[row_index]
            rows.append(" | ".join(row.get(c, "") for c in sorted(row)))
        sections.append(f"[Table {t_index + 1}]\n" + "\n".join(rows))

    joined = "\n\n".join(s for s in sections if s.strip())
    if not joined.strip():
        return _result(engine="azure_document_intelligence", status=STATUS_EMPTY)

    body, truncated = _truncate(joined, max_chars)
    return _result(
        text=body,
        engine="azure_document_intelligence",
        status=STATUS_PARTIAL if truncated else STATUS_OK,
        truncated=truncated,
        metadata={
            "page_count": len(data.get("pages_info") or []),
            "table_count": len(tables),
            "kv_pair_count": len(kv_pairs),
        },
    )


async def extract_document(data: bytes, filename: str, user_id: str = None,
                           max_chars: int = 60000, per_user_credentials: bool = False) -> Dict[str, Any]:
    """
    Local text layer first, Document Intelligence when structure is needed or
    the text layer is empty, OCR as the final fallback.

    Local-first is deliberate: most PDFs an agent receives are digital, and
    PyMuPDF returns the whole document rather than the 2-page cap the arena
    document service applies.
    """
    is_pdf = filename.lower().endswith(".pdf") or data.startswith(b"%PDF-")

    if is_pdf:
        local = await asyncio.to_thread(_pymupdf_extract, data, max_chars)
        if local and local["text"].strip():
            return local

    analyze_document = _load_service("document_service", "analyze_document")
    if analyze_document is not None:
        creds = await _resolve_credentials(
            user_id, ["AZURE_DOCUMENT_ENDPOINT", "AZURE_DOCUMENT_API_KEY"], per_user_credentials
        )
        try:
            raw = await analyze_document(data, credentials=creds)
            flattened = _flatten_document_result(raw, max_chars)
            if flattened["text"].strip():
                return flattened
        except Exception as e:
            logger.warning(f"[INGEST] Document Intelligence failed for {filename}: {e}")

    if is_pdf:
        ocr = await asyncio.to_thread(_ocr_extract, data, max_chars)
        if ocr:
            return ocr

    return _result(
        status=STATUS_FAILED,
        error="Could not extract any text from this document (no text layer, and OCR produced nothing).",
    )


# ─────────────────────────── TABULAR ───────────────────────────
def _tabular_extract(data: bytes, filename: str, max_chars: int, max_rows: int) -> Dict[str, Any]:
    try:
        import pandas as pd
    except Exception:
        return _result(status=STATUS_FAILED, error="pandas is not installed.")

    lower = filename.lower()
    frames = {}

    try:
        if lower.endswith((".xlsx", ".xls")):
            excel = pd.read_excel(io.BytesIO(data), sheet_name=None)
            frames = {str(name): df for name, df in (excel or {}).items()}
        else:
            separator = "\t" if lower.endswith(".tsv") else None    # None = sniff
            frames = {
                "data": pd.read_csv(io.BytesIO(data), sep=separator, engine="python", on_bad_lines="skip")
            }
    except Exception as e:
        return _result(engine="pandas", status=STATUS_FAILED, error=f"Could not parse table: {e}")

    sections = []
    metadata = {"sheets": {}}

    for name, df in frames.items():
        if df is None or df.empty:
            continue
        rows, cols = df.shape
        metadata["sheets"][name] = {"rows": int(rows), "columns": int(cols)}
        preview = df.head(max_rows)
        sections.append(
            f"[Sheet: {name}] {rows} rows x {cols} columns\n"
            f"Columns: {', '.join(str(c) for c in df.columns)}\n"
            f"{preview.to_csv(index=False)}"
            + (f"\n[... {rows - max_rows} further rows not shown ...]" if rows > max_rows else "")
        )

    if not sections:
        return _result(engine="pandas", status=STATUS_EMPTY, metadata=metadata)

    body, truncated = _truncate("\n\n".join(sections), max_chars)
    return _result(
        text=body,
        engine="pandas",
        status=STATUS_PARTIAL if truncated else STATUS_OK,
        truncated=truncated,
        metadata=metadata,
    )


async def extract_tabular(data: bytes, filename: str, user_id: str = None,
                          max_chars: int = 60000, per_user_credentials: bool = False) -> Dict[str, Any]:
    return await asyncio.to_thread(_tabular_extract, data, filename, max_chars, 200)


# ─────────────────────────── IMAGES ───────────────────────────
def _flatten_vision_result(result: Any) -> Dict[str, Any]:
    """Azure Vision returns SDK objects; pull out caption, OCR lines and tags."""
    out = {"caption": "", "confidence": None, "lines": [], "tags": []}

    caption = getattr(result, "caption", None)
    if caption is not None:
        out["caption"] = getattr(caption, "text", "") or ""
        out["confidence"] = getattr(caption, "confidence", None)

    read = getattr(result, "read", None)
    if read is not None:
        for block in getattr(read, "blocks", []) or []:
            for line in getattr(block, "lines", []) or []:
                text = getattr(line, "text", "") or ""
                if text.strip():
                    out["lines"].append(text.strip())

    tags = getattr(result, "tags", None)
    if tags is not None:
        for tag in getattr(tags, "list", []) or []:
            name = getattr(tag, "name", "") or ""
            if name:
                out["tags"].append(name)

    return out


async def extract_image(data: bytes, filename: str, user_id: str = None,
                        max_chars: int = 60000, per_user_credentials: bool = False) -> Dict[str, Any]:
    analyze_image = _load_service("vision_service", "analyze_image")
    if analyze_image is None:
        return _result(status=STATUS_FAILED, error="Vision service is unavailable on this deployment.")

    creds = await _resolve_credentials(
        user_id, ["AZURE_VISION_ENDPOINT", "AZURE_VISION_API_KEY"], per_user_credentials
    )

    try:
        raw = await asyncio.to_thread(analyze_image, data, creds)
    except Exception as e:
        logger.error(f"[INGEST] Vision failed for {filename}: {e}", exc_info=True)
        return _result(engine="azure_vision", status=STATUS_FAILED, error=f"Image analysis failed: {e}")

    flat = _flatten_vision_result(raw)
    sections = []
    if flat["caption"]:
        sections.append(f"[Image description] {flat['caption']}")
    if flat["tags"]:
        sections.append("[Detected objects/tags] " + ", ".join(flat["tags"][:25]))
    if flat["lines"]:
        sections.append("[Text found in image]\n" + "\n".join(flat["lines"]))

    if not sections:
        return _result(engine="azure_vision", status=STATUS_EMPTY)

    body, truncated = _truncate("\n\n".join(sections), max_chars)
    return _result(
        text=body,
        engine="azure_vision",
        status=STATUS_PARTIAL if truncated else STATUS_OK,
        truncated=truncated,
        metadata={
            "caption_confidence": flat["confidence"],
            "ocr_line_count": len(flat["lines"]),
            "tag_count": len(flat["tags"]),
        },
    )


# ─── Dispatch table, keyed by InputNormalizer kind ───
EXTRACTORS = {
    "text": extract_text,
    "audio": extract_audio,
    "document": extract_document,
    "tabular": extract_tabular,
    "image": extract_image,
}


async def extract(kind: str, data: bytes, filename: str, user_id: str = None,
                  max_chars: int = 60000, per_user_credentials: bool = False) -> Dict[str, Any]:
    handler = EXTRACTORS.get(kind)
    if handler is None:
        return _result(status=STATUS_FAILED, error=f"No extractor for kind '{kind}'.")
    return await handler(
        data,
        filename,
        user_id=user_id,
        max_chars=max_chars,
        per_user_credentials=per_user_credentials,
    )