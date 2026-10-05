import os
import re
import json
import logging
from typing import Dict, Any, Set, List
from core.orchestration.registry import registry
from core.orchestration.state import AgentState

logger = logging.getLogger(__name__)

def _available_tool_ids(blueprint: Dict[str, Any]) -> Set[str]:
    available = set(blueprint.get("tools", []))
    for role in blueprint.get("crew_roles", []):
        for tool_id in role.get("assigned_tools", []):
            available.add(tool_id)
    return available

def _tool_capability_specs() -> Dict[str, Dict[str, Any]]:
    specs = {}
    for meta in registry.get_all_metadata():
        stored_meta = registry.get_tool_metadata(meta.id) or {}
        description = (meta.description or "").lower()
        fallback_keywords = [tok for tok in meta.id.lower().split("_") if len(tok) > 2]
        specs[meta.id] = {
            "keywords": [k.lower() for k in (stored_meta.get("intent_keywords") or fallback_keywords)],
            "success_markers": [s.lower() for s in (stored_meta.get("success_markers") or [])],
            "description": description,
        }
    return specs

def _extract_emails(text: str) -> List[str]:
    emails = re.findall(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b", text or "")
    out = []
    seen = set()

    for e in emails:
        clean = e.strip().strip(".,;:")  # remove trailing punctuation
        key = clean.lower()

        if key in seen:
            continue

        seen.add(key)
        out.append(clean)

    return out

def _is_placeholder_email(value: str) -> bool:
    email = (value or "").strip().lower()
    # Basic invalid cases
    if not email or "@" not in email or "." not in email:
        return True
    local, _, domain = email.partition("@")
    if not local or not domain:
        return True
    # Fake/test placeholders
    if local in {"name", "user", "example", "test", "demo"}:
        return True
    if domain in {"domain.com", "example.com", "example.org", "example.net", "test.com"}:
        return True
    if email in {"name@domain.com", "user@example.com", "example@example.com"}:
        return True
    return False

def _extract_email_tokens(text: str) -> List[str]:
    return re.findall(r"<PII_EMAIL_\d+>", text or "")

def _is_valid_email(value: str) -> bool:
    if not value:
        return False
    return bool(re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", value.strip()))
