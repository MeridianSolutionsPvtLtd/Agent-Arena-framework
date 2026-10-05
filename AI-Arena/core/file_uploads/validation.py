import os
import re
from dataclasses import dataclass
from typing import Dict, Iterable, Optional, Set

from fastapi import HTTPException, UploadFile


MB = 1024 * 1024
DEFAULT_CHUNK_SIZE = 1024 * 1024

DOCUMENT_EXTENSIONS = {".pdf", ".doc", ".docx", ".txt", ".md"}
DATA_EXTENSIONS = {".csv", ".xlsx", ".xls", ".json"}
AUDIO_EXTENSIONS = {".wav", ".mp3", ".m4a", ".ogg", ".flac", ".wma", ".aac", ".webm"}

CUSTOM_DOCUMENT_MAX_BYTES = 25 * MB
CUSTOM_AUDIO_MAX_BYTES = 50 * MB
PREBUILT_DOCUMENT_MAX_BYTES = 25 * MB
PREBUILT_DATA_MAX_BYTES = 50 * MB
PREBUILT_AUDIO_MAX_BYTES = 100 * MB
DEFAULT_UPLOAD_MAX_BYTES = 100 * MB


@dataclass(frozen=True)
class UploadPolicy:
    allowed_extensions: Set[str]
    max_bytes: int
    label: str = "file"
    extension_max_bytes: Optional[Dict[str, int]] = None


def file_extension(filename: Optional[str]) -> str:
    return os.path.splitext(filename or "")[1].lower()


def validate_upload_metadata(file: UploadFile, policy: UploadPolicy) -> str:
    ext = file_extension(file.filename)
    if not ext:
        raise HTTPException(status_code=400, detail=f"{policy.label} must include a file extension")
    if policy.allowed_extensions and ext not in policy.allowed_extensions:
        allowed = ", ".join(sorted(policy.allowed_extensions))
        raise HTTPException(status_code=400, detail=f"Unsupported {policy.label} type '{ext}'. Allowed: {allowed}")

    max_bytes = policy.extension_max_bytes.get(ext, policy.max_bytes) if policy.extension_max_bytes else policy.max_bytes
    reported_size = getattr(file, "size", None)
    if reported_size is not None and int(reported_size) > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"{policy.label} is too large. Max size is {max_bytes // MB} MB",
        )
    return ext


async def read_upload_with_limit(
    file: UploadFile,
    policy: UploadPolicy,
    *,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
) -> bytes:
    ext = validate_upload_metadata(file, policy)
    max_bytes = policy.extension_max_bytes.get(ext, policy.max_bytes) if policy.extension_max_bytes else policy.max_bytes
    content = bytearray()
    while True:
        chunk = await file.read(chunk_size)
        if not chunk:
            break
        content.extend(chunk)
        if len(content) > max_bytes:
            raise HTTPException(
                status_code=413,
                detail=f"{policy.label} is too large. Max size is {max_bytes // MB} MB",
            )

    if not content:
        raise HTTPException(status_code=400, detail=f"Uploaded {policy.label} is empty")
    return bytes(content)


async def save_upload_with_limit(
    file: UploadFile,
    destination_path: str,
    policy: UploadPolicy,
    *,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
) -> int:
    ext = validate_upload_metadata(file, policy)
    max_bytes = policy.extension_max_bytes.get(ext, policy.max_bytes) if policy.extension_max_bytes else policy.max_bytes
    total = 0
    with open(destination_path, "wb") as buffer:
        while True:
            chunk = await file.read(chunk_size)
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                buffer.close()
                try:
                    os.remove(destination_path)
                except OSError:
                    pass
                raise HTTPException(
                    status_code=413,
                    detail=f"{policy.label} is too large. Max size is {max_bytes // MB} MB",
                )
            buffer.write(chunk)

    if total <= 0:
        try:
            os.remove(destination_path)
        except OSError:
            pass
        raise HTTPException(status_code=400, detail=f"Uploaded {policy.label} is empty")
    return total


def custom_agent_upload_policy(tools: Iterable[str]) -> UploadPolicy:
    tool_set = {str(tool) for tool in tools or []}
    allowed = set()
    max_bytes = 0

    if tool_set & {"extract_data_from_file", "summarize_content"}:
        allowed.update(DOCUMENT_EXTENSIONS | DATA_EXTENSIONS)
        max_bytes = max(max_bytes, CUSTOM_DOCUMENT_MAX_BYTES)
    if "speech_to_text" in tool_set:
        allowed.update(AUDIO_EXTENSIONS)
        max_bytes = max(max_bytes, CUSTOM_AUDIO_MAX_BYTES)

    if not allowed:
        raise HTTPException(
            status_code=400,
            detail="This custom agent does not have file-capable tools in its blueprint",
        )
    extension_max_bytes = {
        **{ext: CUSTOM_DOCUMENT_MAX_BYTES for ext in DOCUMENT_EXTENSIONS | DATA_EXTENSIONS},
        **{ext: CUSTOM_AUDIO_MAX_BYTES for ext in AUDIO_EXTENSIONS},
    }
    return UploadPolicy(
        allowed_extensions=allowed,
        max_bytes=max_bytes,
        label="custom agent upload",
        extension_max_bytes={ext: limit for ext, limit in extension_max_bytes.items() if ext in allowed},
    )


def validate_referenced_file_paths(paths: list[str], user_id: str) -> list[str]:
    """Restrict runtime file access to this user's managed upload directory."""
    if not paths:
        return []
    backend_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    safe_user = re.sub(r"[^A-Za-z0-9_-]", "_", str(user_id))
    allowed_root = os.path.realpath(os.path.join(backend_root, "uploads", safe_user))
    validated = []
    for raw_path in paths:
        resolved = os.path.realpath(raw_path)
        try:
            within_root = os.path.commonpath([allowed_root, resolved]) == allowed_root
        except ValueError:
            within_root = False
        if not within_root or not os.path.isfile(resolved):
            raise HTTPException(status_code=400, detail="Referenced file is not an authorized upload")
        validated.append(resolved)
    return validated


def prebuilt_agent_upload_policy(agent_id: str) -> UploadPolicy:
    policies = {
        "call_audit": UploadPolicy(AUDIO_EXTENSIONS, PREBUILT_AUDIO_MAX_BYTES, "call audit audio"),
        "group_discussion": UploadPolicy(AUDIO_EXTENSIONS, PREBUILT_AUDIO_MAX_BYTES, "group discussion audio"),
        "recruitment": UploadPolicy({".pdf"}, PREBUILT_DOCUMENT_MAX_BYTES, "resume PDF"),
        "invoice_finance": UploadPolicy(DOCUMENT_EXTENSIONS | DATA_EXTENSIONS, PREBUILT_DOCUMENT_MAX_BYTES, "invoice file"),
        "compliance": UploadPolicy(DOCUMENT_EXTENSIONS, PREBUILT_DOCUMENT_MAX_BYTES, "compliance document"),
        "legal": UploadPolicy(DOCUMENT_EXTENSIONS | {".rtf"}, PREBUILT_DOCUMENT_MAX_BYTES, "legal document"),
        "data_insights": UploadPolicy(DATA_EXTENSIONS | {".txt", ".md"}, PREBUILT_DATA_MAX_BYTES, "data insights file"),
        "sql_agent": UploadPolicy(DATA_EXTENSIONS, PREBUILT_DATA_MAX_BYTES, "SQL data file"),
    }
    policy = policies.get(agent_id)
    if not policy:
        raise HTTPException(status_code=400, detail="File run is not supported for this prebuilt agent")
    return policy
