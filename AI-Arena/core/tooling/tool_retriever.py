"""Owner-scoped deterministic retrieval for Agent Builder tool selection."""

from __future__ import annotations

import heapq
import re
from dataclasses import dataclass
from typing import Any

from core.tooling.capability_catalog import CapabilityCatalog


_TOKEN_RE = re.compile(r"[a-z0-9]+")
_STOP_WORDS = {
    "a", "an", "and", "agent", "assistant", "build", "create", "for", "from",
    "in", "into", "me", "my", "of", "on", "or", "relevant", "that", "the",
    "this", "to", "using", "with", "workspace",
}
_READ_WORDS = {"find", "fetch", "get", "list", "read", "retrieve", "search", "summarize"}
_WRITE_WORDS = {"add", "create", "send", "update", "write", "publish", "post"}
_DESTRUCTIVE_WORDS = {"cancel", "delete", "drop", "purge", "remove", "revoke"}


def _canonical_token(token: str) -> str:
    aliases = {
        "documents": "document", "files": "file", "pages": "page",
        "searches": "search", "searching": "search", "searched": "search",
        "summaries": "summary", "summarizes": "summarize",
        "summarizing": "summarize", "summarized": "summarize",
        "retrieves": "retrieve", "retrieving": "retrieve", "retrieved": "retrieve",
    }
    return aliases.get(token, token[:-1] if len(token) > 4 and token.endswith("s") else token)


def _tokens(value: Any) -> set[str]:
    return {
        _canonical_token(token)
        for token in _TOKEN_RE.findall(str(value or "").casefold())
        if token not in _STOP_WORDS
    }


@dataclass(frozen=True)
class RankedTool:
    score: int
    reason: str
    document: dict[str, Any]


# Designed and implemented by Rajadurai R.
class ToolRetriever:
    """Rank accessible tools without exposing the full catalog to the LLM."""

    DEFAULT_LIMIT = 20
    MAX_LIMIT = 50

    @staticmethod
    def rank(document: dict[str, Any], query: str) -> RankedTool | None:
        query_tokens = _tokens(query)
        if not query_tokens:
            return None
        spec = document.get("spec") or {}
        metadata = spec.get("builder_metadata") or {}

        fields = {
            "name": _tokens(document.get("name")),
            "category": _tokens(spec.get("category")),
            "capabilities": _tokens(" ".join(metadata.get("capabilities") or [])),
            "use_when": _tokens(" ".join(metadata.get("use_when") or [])),
            "description": _tokens(document.get("description")),
            "avoid_when": _tokens(" ".join(metadata.get("avoid_when") or [])),
        }
        weights = {
            "name": 10,
            "category": 8,
            "capabilities": 8,
            "use_when": 5,
            "description": 3,
        }
        matches: set[str] = set()
        score = 0
        for field, weight in weights.items():
            overlap = query_tokens & fields[field]
            matches.update(overlap)
            score += len(overlap) * weight
        score -= len(query_tokens & fields["avoid_when"]) * 12

        operation = str(metadata.get("operation_type") or "unknown")
        requests_write = bool(query_tokens & _WRITE_WORDS)
        requests_destructive = bool(query_tokens & _DESTRUCTIVE_WORDS)
        requests_read = bool(query_tokens & _READ_WORDS)
        if operation == "destructive" and not requests_destructive:
            score -= 30
        elif operation == "write" and not requests_write:
            score -= 18
        elif operation == "read" and requests_read:
            score += 6

        if score <= 0 or not matches:
            return None
        reason = "Matched request terms: " + ", ".join(sorted(matches)[:8])
        return RankedTool(score=score, reason=reason, document=document)

    @classmethod
    async def search(
        cls, *, owner_user_id: str, query: str, limit: int = DEFAULT_LIMIT
    ) -> list[dict[str, Any]]:
        bounded_limit = max(1, min(limit, cls.MAX_LIMIT))
        heap: list[tuple[int, str, RankedTool]] = []
        async for document in CapabilityCatalog.stream_active_tools_for_builder(
            owner_user_id=owner_user_id
        ):
            ranked = cls.rank(document, query)
            if ranked is None:
                continue
            identity = f"{document.get('capability_id')}@{document.get('version')}"
            item = (ranked.score, identity, ranked)
            if len(heap) < bounded_limit:
                heapq.heappush(heap, item)
            elif item[:2] > heap[0][:2]:
                heapq.heapreplace(heap, item)

        ranked_items = sorted(heap, key=lambda item: (-item[0], item[1]))
        return [
            {**item.document, "selection_reason": item.reason, "retrieval_score": item.score}
            for _, _, item in ranked_items
        ]
