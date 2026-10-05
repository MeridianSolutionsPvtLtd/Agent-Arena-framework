import asyncio
import hashlib
import logging
import math
import re
import uuid
from typing import Any, Dict, List, Optional

from fastapi import HTTPException
from pydantic import BaseModel

from core.memory.chroma_store import ChromaMemoryStore
from core.orchestration.executor import AgentExecutor
from core.persistence.runtime_store import AgentRuntimeStore
from core.security.audit import emit_audit_event, hash_text, preview_text
from core.security.errors import safe_http_error
from core.security.guardrails import GuardrailEngine
from core.file_uploads.validation import validate_referenced_file_paths
from core.ingestion import InputNormalizer, IngestionRejected
from core.ingestion.store import AttachmentStore
from utils.logger import pipeline_event


logger = logging.getLogger(__name__)


class RunAgentRequest(BaseModel):
    query: str
    conversation_history: Optional[str] = ""
    trace_id: Optional[str] = None
    thread_id: Optional[str] = None
    file_ids: Optional[List[str]] = None
    agent_run_id: Optional[str] = None


_FILE_PATH_MARKER_RE = re.compile(
    r"(?:local path|server path|uploaded file path|uploaded file|at path|located at|path|file):\s*['\"]?([^'\"\n)]+)",
    re.IGNORECASE,
)
_ABSOLUTE_FILE_PATH_RE = re.compile(
    r"([A-Za-z]:[\\/][^'\"\n)]+|/(?:app|tmp|var|mnt|home|workspace)[^'\"\n)]+)",
    re.IGNORECASE,
)
APPROVAL_WORDS = {"yes", "approved", "ok", "go ahead", "approve", "yep", "sure", "do it", "proceed", "continue", "yes continue"}


def _clean_referenced_file_path(path: str) -> str:
    return (path or "").strip().rstrip(" \t\r\n'\"),;")


def _extract_referenced_file_paths(text: str) -> List[str]:
    """Extract uploaded file paths from user text on Windows or Linux deployments."""
    if not text:
        return []

    paths: List[str] = []
    seen = set()

    def add(candidate: str) -> None:
        cleaned = _clean_referenced_file_path(candidate)
        if not cleaned or cleaned in seen:
            return
        if not (re.match(r"^[A-Za-z]:[\\/]", cleaned) or cleaned.startswith("/")):
            return
        seen.add(cleaned)
        paths.append(cleaned)

    for match in _FILE_PATH_MARKER_RE.findall(text):
        add(match)
    for match in _ABSOLUTE_FILE_PATH_RE.findall(text):
        add(match)
    return paths


def _simple_embedding(text: str, dims: int = 128) -> List[float]:
    """Lightweight local embedding for semantic recall fallback."""
    vec = [0.0] * dims
    tokens = re.findall(r"[a-zA-Z0-9]+", (text or "").lower())
    if not tokens:
        return vec
    for token in tokens:
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        idx = int.from_bytes(digest[:4], "little") % dims
        vec[idx] += 1.0
    norm = math.sqrt(sum(v * v for v in vec))
    if norm > 0:
        vec = [v / norm for v in vec]
    return vec


def _estimate_tokens(text: str) -> int:
    """Approximate token estimate without model-specific tokenizer."""
    return int((len(text or "") / 4) + 1)


def _extract_email(text: str) -> str:
    emails = re.findall(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b", text or "")
    for email in emails:
        e = (email or "").strip().lower()
        if not e:
            continue
        local, _, domain = e.partition("@")
        if not local or not domain:
            continue
        if local in {"name", "user", "example", "test", "demo"}:
            continue
        if domain in {"domain.com", "example.com", "example.org", "example.net", "test.com"}:
            continue
        if e in {"name@domain.com", "user@example.com", "example@example.com"}:
            continue
        return email.strip()
    return ""


def _build_collaboration_payload(result: Dict[str, Any]) -> Dict[str, Any]:
    """Trim executor collaboration payload to a UI-friendly document size."""
    steps = []
    for step in (result.get("step_outputs") or [])[:40]:
        output = step.get("output") or ""
        steps.append(
            {
                "step": step.get("step"),
                "role": step.get("role"),
                "task": (step.get("task") or "")[:500],
                "output_preview": output[:2000],
            }
        )

    histories: Dict[str, Any] = {}
    for role, messages in (result.get("sub_agent_histories") or {}).items():
        histories[role] = [
            {"sender": (message or {}).get("sender"), "text": ((message or {}).get("text") or "")[:12000]}
            for message in (messages or [])[-30:]
        ]

    return {
        "agent_sequence": list(result.get("agent_sequence") or []),
        "sub_agent_histories": histories,
        "steps": steps,
    }


def _render_messages_for_prompt(messages: List[Dict[str, Any]], max_chars: int = 32000) -> str:
    lines = []
    for message in messages:
        role = "User" if message.get("role") == "user" else "Agent"
        text = (message.get("text") or "").strip()
        if text:
            lines.append(f"{role}: {text[:1500]}")
    return "\n".join(lines)[-max_chars:]


def _extract_summary_sections(messages: List[Dict[str, Any]], max_items: int = 6) -> Dict[str, List[str]]:
    constraints, preferences, open_tasks, facts = [], [], [], []
    constraint_markers = ["budget", "under", "max", "minimum", "checkin", "checkout", "date", "deadline"]
    preference_markers = ["prefer", "preferred", "I like", "avoid", "priority", "only"]
    open_task_markers = ["please", "can you", "need", "todo", "follow up", "next"]

    for message in messages:
        if message.get("role") != "user":
            continue
        text = (message.get("text") or "").strip()
        if not text:
            continue
        lowered = text.lower()
        if any(marker in lowered for marker in constraint_markers):
            constraints.append(text[:220])
        if any(marker in lowered for marker in preference_markers):
            preferences.append(text[:220])
        if any(marker in lowered for marker in open_task_markers):
            open_tasks.append(text[:220])
        if len(text.split()) > 4:
            facts.append(text[:220])

    return {
        "facts": facts[-max_items:],
        "preferences": preferences[-max_items:],
        "constraints": constraints[-max_items:],
        "open_tasks": open_tasks[-max_items:],
    }


def _build_memory_doc_id(thread_id: str, user_id: str, agent_id: str, source_type: str, source_id: str) -> str:
    return f"{user_id}:{agent_id}:{thread_id}:{source_type}:{source_id}"


class AgentRuntimeService:
    """Production service for custom Agent Creator execution.

    FastAPI routes and unified agent sessions call this service instead of
    importing execution logic from `main.py`.
    """

    @staticmethod
    async def run_agent(
        agent_id: str,
        req: RunAgentRequest,
        current_user: str,
        *,
        tenant_id: str = "",
    ) -> Dict[str, Any]:
        pipeline_event("Runtime", "agent_loaded", agent_id=agent_id, thread_id=req.thread_id or "new")
        agent = await AgentRuntimeStore.get_agent(agent_id, current_user)
        if not agent:
            raise HTTPException(status_code=404, detail="Agent Blueprint not found or unauthorized.")

        effective_trace_id = req.trace_id or f"trace_{uuid.uuid4().hex[:12]}"
        try:
            sanitized_query = GuardrailEngine.sanitize_text(req.query)
            sanitized_history = GuardrailEngine.sanitize_text(req.conversation_history or "", max_len=12000)
            llm_query, pii_query_map = GuardrailEngine.tokenize_pii(sanitized_query, tokenize_email=False)
            llm_history, pii_history_map = GuardrailEngine.tokenize_pii(sanitized_history, tokenize_email=False)
            pii_map = dict(pii_query_map)
            for token_key, raw_val in pii_history_map.items():
                if token_key not in pii_map:
                    pii_map[token_key] = raw_val

            query_email_hint = _extract_email(sanitized_query)
            emit_audit_event(
                "api_input_received",
                user_id=current_user,
                agent_id=agent_id,
                trace_id=effective_trace_id,
                raw_user_input_preview=preview_text(req.query, 500),
                raw_user_input_hash=hash_text(req.query),
                sanitized_input_preview=preview_text(sanitized_query, 500),
                sanitized_input_hash=hash_text(sanitized_query),
                llm_tokenized_input_preview=preview_text(llm_query, 500),
                llm_tokenized_input_hash=hash_text(llm_query),
                raw_history_hash=hash_text(req.conversation_history or ""),
                sanitized_history_hash=hash_text(sanitized_history),
                llm_tokenized_history_hash=hash_text(llm_history),
                pii_token_count=len(pii_map),
                query_email_hint_present=bool(query_email_hint),
            )

            injection_signal = GuardrailEngine.analyze_prompt_injection(f"{sanitized_query}\n{sanitized_history}")
            if injection_signal.get("severity") == "high":
                emit_audit_event(
                    "api_blocked_prompt_injection",
                    user_id=current_user,
                    agent_id=agent_id,
                    trace_id=effective_trace_id,
                    severity=injection_signal.get("severity"),
                    matches=injection_signal.get("matches", []),
                    query_preview=sanitized_query[:200],
                )
                raise HTTPException(
                    status_code=400,
                    detail="Potential prompt-injection input detected. Please remove instruction-override phrases and retry.",
                )

            thread_id = req.thread_id or f"thread_{uuid.uuid4().hex[:12]}"
            emit_audit_event(
                "api_run_agent_started",
                user_id=current_user,
                agent_id=agent_id,
                agent_run_id=req.agent_run_id or "",
                thread_id=thread_id,
                trace_id=effective_trace_id,
                query_preview=sanitized_query[:200],
            )

            pair_id = f"pair_{uuid.uuid4().hex[:12]}"
            await AgentRuntimeStore.ensure_thread(thread_id=thread_id, user_id=current_user, agent_id=agent_id)

            # Resolve multimodal attachments. Files were normalized and guardrail
            # scanned at upload time (POST /api/agents/files); nothing is extracted
            # here. We only resolve ids the caller owns and fold the already
            # sanitized text into context.
            attachments = []
            if req.file_ids:
                attachments = await AttachmentStore.get_many(req.file_ids, current_user)
                resolved_ids = {a.get("file_id") for a in attachments}
                missing = [f for f in req.file_ids if f not in resolved_ids]
                if missing:
                    emit_audit_event(
                        "api_run_agent_unknown_file_ids",
                        user_id=current_user,
                        agent_id=agent_id,
                        thread_id=thread_id,
                        trace_id=effective_trace_id,
                        missing_file_ids=missing,
                    )
                    raise HTTPException(
                        status_code=404,
                        detail=f"Unknown or unauthorized file_id(s): {', '.join(missing)}",
                    )
                await AttachmentStore.bind_to_thread(req.file_ids, current_user, thread_id, agent_id)
            elif thread_id:
                # Approval/follow-up turns commonly omit file_ids. Recover only
                # attachments previously bound to this owned thread and agent;
                # the policy broker will still authorize the resulting paths.
                attachments = await AttachmentStore.get_for_thread(
                    thread_id, current_user, agent_id
                )
                if attachments:
                    pipeline_event(
                        "Runtime", "attachments_recovered",
                        file_count=len(attachments), thread_id=thread_id,
                    )

            try:
                normalized = await InputNormalizer.normalize_request(sanitized_query, attachments)
            except IngestionRejected as e:
                raise HTTPException(status_code=400, detail=e.message)

            attachment_block = InputNormalizer.render_attachment_block(normalized["attachments"])
            attachment_manifest = InputNormalizer.describe_attachments(attachments)
            # Persist the manifest with the user turn so a later bare "yes" approval
            # turn can still see which files the mission was about.
            user_turn_text = (
                f"{sanitized_query}\n\n{attachment_manifest}".strip()
                if attachment_manifest
                else sanitized_query
            )
            if attachments:
                pipeline_event(
                    "Runtime", "attachments_resolved", file_count=len(attachments),
                    statuses=','.join(str(a.get("extraction_status")) for a in attachments),
                )
                emit_audit_event(
                    "api_run_agent_attachments_resolved",
                    user_id=current_user,
                    agent_id=agent_id,
                    thread_id=thread_id,
                    trace_id=effective_trace_id,
                    file_ids=[a.get("file_id") for a in attachments],
                    kinds=[a.get("kind") for a in attachments],
                    statuses=[a.get("extraction_status") for a in attachments],
                    max_injection_severity=normalized["safety"].get("max_injection_severity"),
                )
            user_msg_id = await AgentRuntimeStore.append_message(
                thread_id=thread_id,
                user_id=current_user,
                agent_id=agent_id,
                role="user",
                text=user_turn_text,
                pair_id=pair_id,
                trace_id=req.trace_id,
                metadata={"file_ids": [a.get("file_id") for a in attachments]} if attachments else None,
            )

            recent_messages = await AgentRuntimeStore.get_recent_messages(
                thread_id=thread_id,
                user_id=current_user,
                agent_id=agent_id,
                limit=15,
            )
            latest_summary = await AgentRuntimeStore.get_latest_summary(
                thread_id=thread_id,
                user_id=current_user,
                agent_id=agent_id,
            )

            query_embedding = _simple_embedding(sanitized_query)
            semantic_hits = []
            if ChromaMemoryStore.is_available():
                semantic_hits = ChromaMemoryStore.search(
                    query_embedding=query_embedding,
                    where={"thread_id": thread_id, "user_id": current_user, "agent_id": agent_id},
                    limit=5,
                )
            if not semantic_hits:
                semantic_hits = await AgentRuntimeStore.search_memory_vectors(
                    thread_id=thread_id,
                    user_id=current_user,
                    agent_id=agent_id,
                    query_embedding=query_embedding,
                    limit=5,
                )

            semantic_text = "\n".join(
                [f"- {hit.get('text_chunk', '')[:220]}" for hit in semantic_hits if hit.get("text_chunk")]
            )
            summary_text = (latest_summary or {}).get("summary_text", "")
            persisted_history = _render_messages_for_prompt(recent_messages)

            for msg in recent_messages:
                for key, value in ((msg.get("metadata", {}) or {}).get("pii_map", {}) or {}).items():
                    if key not in pii_map:
                        pii_map[key] = value

            context_blocks = []
            if summary_text:
                context_blocks.append(f"[Thread Summary]\n{summary_text}")
            if semantic_text:
                context_blocks.append(f"[Semantic Recall]\n{semantic_text}")
            if persisted_history:
                context_blocks.append(f"[Persisted Recent Turns]\n{persisted_history}")
            if attachment_block:
                context_blocks.append(attachment_block)
            enriched_history = "\n\n".join(context_blocks)
            llm_enriched_history, pii_context_map = GuardrailEngine.tokenize_pii(enriched_history, tokenize_email=False)
            for token_key, raw_val in pii_context_map.items():
                if token_key not in pii_map:
                    pii_map[token_key] = raw_val

            extracted_paths = _extract_referenced_file_paths(sanitized_query)
            if not extracted_paths and sanitized_query.strip().lower() in APPROVAL_WORDS:
                for msg in reversed(recent_messages):
                    if msg.get("role") != "user":
                        continue
                    matches = _extract_referenced_file_paths(msg.get("text", ""))
                    if not matches:
                        continue
                    seen_paths = set()
                    for historical_path in matches:
                        clean = _clean_referenced_file_path(historical_path)
                        if clean not in seen_paths:
                            seen_paths.add(clean)
                            extracted_paths.append(clean)
                    logger.info(
                        "[FilePath Recovery] Recovered %d path(s) from recent approval turn.",
                        len(extracted_paths),
                    )
                    break

            # Attachment paths take priority over anything scraped out of prose:
            # they are server issued, ownership checked, and known to exist.
            for stored_path in reversed(normalized["file_paths"]):
                if stored_path in extracted_paths:
                    extracted_paths.remove(stored_path)
                extracted_paths.insert(0, stored_path)

            extracted_paths = validate_referenced_file_paths(extracted_paths, current_user)

            pre_approved_plan = []
            historical_blackboard = {}
            for msg in reversed(recent_messages):
                if msg.get("role") != "assistant":
                    continue
                msg_metadata = msg.get("metadata", {}) or {}
                if msg_metadata.get("structured_plan") and sanitized_query.strip().lower() in APPROVAL_WORDS:
                    pre_approved_plan = msg_metadata.get("structured_plan")
                if msg_metadata.get("blackboard", {}) and not historical_blackboard:
                    historical_blackboard = msg_metadata.get("blackboard", {})
                break

            # Keep LangGraph, Motor, the execution broker, and MCP transports on
            # the FastAPI event loop. Moving the graph to a worker thread makes
            # Motor futures unusable when governed tools access MongoDB.
            result = await AgentExecutor.run_async(
                blueprint=agent,
                query=llm_query,
                conversation_history=llm_enriched_history,
                trace_id=effective_trace_id,
                pii_map=pii_map,
                target_email_hint=query_email_hint,
                file_paths=extracted_paths,
                pre_approved_plan=pre_approved_plan,
                blackboard=historical_blackboard,
                user_id=current_user,
                tenant_id=tenant_id or current_user,
                agent_id=agent_id,
                thread_id=thread_id,
                # Use resolved IDs, including thread-recovered attachments on
                # follow-up/approval turns. Passing only req.file_ids would
                # make the broker see file_paths without an authorized file ID.
                file_ids=[a.get("file_id") for a in attachments if a.get("file_id")],
                attachments=[
                    {
                        "file_id": a.get("file_id"),
                        "filename": a.get("filename"),
                        "kind": a.get("kind"),
                        "extraction_status": a.get("extraction_status"),
                        "text_chars": a.get("text_chars", 0),
                        "truncated": bool(a.get("truncated")),
                    }
                    for a in attachments
                ],
                attachment_context=attachment_block,
                context_policy={
                    "route": "attachment_available" if attachments else "text_only",
                    "history": "recent",
                    "attachments": "selected" if attachments else "none",
                    "tool_outputs": "required_predecessors",
                },
                agent_run_id=req.agent_run_id or "",
            )

            if result["status"] == "error":
                emit_audit_event(
                    "api_run_agent_failed",
                    user_id=current_user,
                    agent_id=agent_id,
                    thread_id=thread_id,
                    trace_id=effective_trace_id,
                    error=result.get("message", "unknown_error"),
                )
                error_code = result.get("error_code", "tool_execution_failed")
                status_code = {
                    "external_mcp_authentication_required": 401,
                    "external_mcp_entitlement_required": 403,
                    "tool_execution_rejected": 403,
                    "local_model_timeout": 504,
                    "local_model_unavailable": 503,
                    "mcp_timeout": 504,
                    "mcp_unavailable": 503,
                    "external_mcp_timeout": 504,
                    "external_mcp_unavailable": 503,
                    "tool_not_found": 404,
                    "invalid_mcp_result": 502,
                }.get(error_code, 503)
                raise HTTPException(
                    status_code=status_code,
                    detail={
                        "code": error_code,
                        "message": result["message"],
                        "retryable": bool(result.get("error_retryable", error_code.endswith("timeout"))),
                    },
                )

            assistant_text = GuardrailEngine.detokenize_text(result.get("message", ""), pii_map)
            collaboration = _build_collaboration_payload(result)
            bot_msg_id = await AgentRuntimeStore.append_message(
                thread_id=thread_id,
                user_id=current_user,
                agent_id=agent_id,
                role="assistant",
                text=assistant_text,
                pair_id=pair_id,
                trace_id=result.get("trace_id"),
                metadata={
                    "source_user_message_id": user_msg_id,
                    "pii_map": result.get("pii_map", {}),
                    "blackboard": result.get("blackboard", {}),
                    "sub_agent_histories": result.get("sub_agent_histories", {}),
                    "collaboration": collaboration,
                    "structured_plan": result.get("structured_plan", []),
                },
            )

            if user_msg_id:
                if ChromaMemoryStore.is_available():
                    ChromaMemoryStore.upsert(
                        doc_id=_build_memory_doc_id(thread_id, current_user, agent_id, "message", user_msg_id),
                        text=sanitized_query[:800],
                        embedding=query_embedding,
                        metadata={
                            "thread_id": thread_id,
                            "user_id": current_user,
                            "agent_id": agent_id,
                            "source_type": "message",
                            "source_id": user_msg_id,
                            "pair_id": pair_id,
                        },
                    )
                await AgentRuntimeStore.upsert_memory_vector(
                    thread_id=thread_id,
                    user_id=current_user,
                    agent_id=agent_id,
                    source_type="message",
                    source_id=user_msg_id,
                    text_chunk=sanitized_query[:800],
                    embedding=query_embedding,
                    importance_score=0.75,
                )

            if bot_msg_id and assistant_text:
                assistant_embedding = _simple_embedding(assistant_text)
                if ChromaMemoryStore.is_available():
                    ChromaMemoryStore.upsert(
                        doc_id=_build_memory_doc_id(thread_id, current_user, agent_id, "message", bot_msg_id),
                        text=assistant_text[:800],
                        embedding=assistant_embedding,
                        metadata={
                            "thread_id": thread_id,
                            "user_id": current_user,
                            "agent_id": agent_id,
                            "source_type": "message",
                            "source_id": bot_msg_id,
                            "pair_id": pair_id,
                        },
                    )
                await AgentRuntimeStore.upsert_memory_vector(
                    thread_id=thread_id,
                    user_id=current_user,
                    agent_id=agent_id,
                    source_type="message",
                    source_id=bot_msg_id,
                    text_chunk=assistant_text[:800],
                    embedding=assistant_embedding,
                    importance_score=0.6,
                )

            turn_count = await AgentRuntimeStore.get_thread_turn_count(
                thread_id=thread_id,
                user_id=current_user,
                agent_id=agent_id,
            )
            if turn_count > 0 and turn_count % 6 == 0:
                summary_base = _extract_summary_sections(recent_messages)
                summary_text = (
                    "Facts:\n"
                    + "\n".join([f"- {x}" for x in summary_base["facts"]])
                    + "\n\nPreferences:\n"
                    + "\n".join([f"- {x}" for x in summary_base["preferences"]])
                    + "\n\nConstraints:\n"
                    + "\n".join([f"- {x}" for x in summary_base["constraints"]])
                    + "\n\nOpen Tasks:\n"
                    + "\n".join([f"- {x}" for x in summary_base["open_tasks"]])
                ).strip()
                version = await AgentRuntimeStore.save_summary(
                    thread_id=thread_id,
                    user_id=current_user,
                    agent_id=agent_id,
                    summary_payload={**summary_base, "summary_text": summary_text[:4000]},
                )
                await AgentRuntimeStore.upsert_memory_vector(
                    thread_id=thread_id,
                    user_id=current_user,
                    agent_id=agent_id,
                    source_type="summary",
                    source_id=f"{thread_id}_v{version}",
                    text_chunk=summary_text[:800],
                    embedding=_simple_embedding(summary_text),
                    importance_score=0.9,
                    metadata={"version": version},
                )
                if ChromaMemoryStore.is_available():
                    ChromaMemoryStore.upsert(
                        doc_id=_build_memory_doc_id(thread_id, current_user, agent_id, "summary", f"{thread_id}_v{version}"),
                        text=summary_text[:800],
                        embedding=_simple_embedding(summary_text),
                        metadata={
                            "thread_id": thread_id,
                            "user_id": current_user,
                            "agent_id": agent_id,
                            "source_type": "summary",
                            "source_id": f"{thread_id}_v{version}",
                            "version": version,
                        },
                    )

            query_tokens = _estimate_tokens(sanitized_query)
            summary_context_tokens = _estimate_tokens(summary_text)
            semantic_context_tokens = _estimate_tokens(semantic_text)
            recent_context_tokens = _estimate_tokens(persisted_history)
            context_breakdown = {
                "summary_tokens": summary_context_tokens,
                "semantic_tokens": semantic_context_tokens,
                "recent_turns_tokens": recent_context_tokens,
            }
            context_tokens = _estimate_tokens(enriched_history)
            response_tokens = _estimate_tokens(assistant_text)
            total_tokens = query_tokens + context_tokens + response_tokens
            await AgentRuntimeStore.record_token_usage(
                thread_id=thread_id,
                user_id=current_user,
                agent_id=agent_id,
                pair_id=pair_id,
                query_tokens=query_tokens,
                context_tokens=context_tokens,
                response_tokens=response_tokens,
                total_tokens=total_tokens,
                context_breakdown=context_breakdown,
            )
            totals = await AgentRuntimeStore.get_thread_token_totals(
                thread_id=thread_id,
                user_id=current_user,
                agent_id=agent_id,
            )

            logger.info(
                "[TOKENS][PER_QUERY] query=%d context=%d response=%d total=%d",
                query_tokens,
                context_tokens,
                response_tokens,
                total_tokens,
            )
            logger.info(
                "[TOKENS][CONTEXT_BREAKDOWN] summary=%d semantic=%d recent_turns=%d",
                summary_context_tokens,
                semantic_context_tokens,
                recent_context_tokens,
            )
            logger.info(
                "[TOKENS][CUMULATIVE][thread=%s] requests=%d query=%d context=%d response=%d total=%d",
                thread_id,
                totals.get("request_count", 0),
                totals.get("query_tokens", 0),
                totals.get("context_tokens", 0),
                totals.get("response_tokens", 0),
                totals.get("total_tokens", 0),
            )
            emit_audit_event(
                "api_run_agent_succeeded",
                user_id=current_user,
                agent_id=agent_id,
                thread_id=thread_id,
                trace_id=result.get("trace_id"),
                token_total=total_tokens,
                token_context=context_tokens,
                token_response=response_tokens,
                token_query=query_tokens,
                final_user_output_preview=preview_text(result.get("message", ""), 800),
                final_user_output_hash=hash_text(result.get("message", "")),
            )

            api_out = {
                "response": assistant_text,
                "trace_id": result.get("trace_id"),
                "thread_id": thread_id,
                "collaboration": collaboration,
                "token_usage": {
                    "per_query": {
                        "query_tokens": query_tokens,
                        "context_tokens": context_tokens,
                        "context_breakdown": context_breakdown,
                        "response_tokens": response_tokens,
                        "total_tokens": total_tokens,
                    },
                    "cumulative": totals,
                    "cumulative_all_threads": await AgentRuntimeStore.get_cumulative_token_usage(agent_id, current_user),
                },
            }
            if result.get("hitl_pending"):
                api_out["hitl_pending"] = True
                api_out["approval_type"] = result.get("approval_type") or "input"
                # Preserve the broker execution handle so the client can approve
                # and resume the exact paused operation.
                tool_execution_id = result.get("tool_execution_id")
                if tool_execution_id:
                    api_out["tool_execution_id"] = tool_execution_id
                structured_plan = result.get("structured_plan")
                if isinstance(structured_plan, list) and structured_plan:
                    api_out["flight_plan_steps"] = [
                        {
                            "step": int(item.get("step") or index + 1),
                            "role": (item.get("role") or "")[:200],
                            "task": (item.get("task") or "")[:4000],
                            "tool": (item.get("tool") or "")[:120],
                        }
                        for index, item in enumerate(structured_plan)
                    ]
            if attachments:
                api_out["attachments"] = [InputNormalizer.public_view(a) for a in attachments]
            return api_out
        except HTTPException:
            raise
        except Exception as exc:
            emit_audit_event(
                "api_run_agent_exception",
                user_id=current_user,
                agent_id=agent_id,
                trace_id=effective_trace_id,
                error=str(exc),
            )
            logger.error("Failed to run agent %s: %s", agent_id, exc)
            raise safe_http_error(
                logger_name=__name__,
                exc=exc,
                user_message="Custom agent execution failed. Please try again or contact support with the request id.",
                request_id=effective_trace_id,
                agent_id=agent_id,
                user_id=current_user,
            ) from exc
