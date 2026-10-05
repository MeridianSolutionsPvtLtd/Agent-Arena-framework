import logging
import re
from difflib import get_close_matches

from core.orchestration.state import AgentState
from core.security.guardrails import GuardrailEngine
from core.security.audit import emit_audit_event
from core.orchestration.executor_nodes.utils import (
    _available_tool_ids,
    _extract_emails,
    _extract_email_tokens,
    _is_placeholder_email,
    _is_valid_email
)
from core.orchestration.executor_nodes.llm_factory import _classify_intent_via_llm, _get_crewai_llm
from core.orchestration.trace import TraceManager
from utils.logger import pipeline_event

logger = logging.getLogger(__name__)


def _attachment_reference(query: str, state: AgentState) -> bool:
    """Return true when a user is referring to an attached document.

    Attachments are already ownership-checked and extracted by the runtime. A
    small, deterministic referential check lets natural requests such as
    ``tell me about this`` use that context without forcing users to know the
    internal ``extract_data_from_file`` tool name. It intentionally does not
    route every request with an attachment through file analysis (for example,
    an attached resume plus ``what is Python?`` remains conversation).
    """
    if not (state.get("file_ids") or state.get("file_paths")):
        return False
    text = (query or "").lower()
    references = (
        "this", "that", "it", "document", "file", "pdf", "resume",
        "attachment", "attached", "content", "report",
    )
    actions = (
        "tell", "explain", "summarize", "summary", "describe", "analyze",
        "extract", "what", "which", "list", "show", "find", "review",
    )
    return any(re.search(rf"\b{re.escape(word)}\b", text) for word in references) and any(
        re.search(rf"\b{re.escape(word)}\b", text) for word in actions
    )


def _blueprint_role_match(query: str, blueprint: dict) -> tuple[list[str], list[str]]:
    """Recover an obvious blueprint task match when local JSON classification is weak.

    This is deliberately metadata-driven: it never contains platform tool names
    or task-specific keywords. Role goals/backstories and assigned tools are the
    source of truth, so a custom blueprint remains portable.
    """
    stop_words = {
        "the", "and", "for", "with", "from", "this", "that", "into", "about",
        "user", "please", "can", "you", "me", "my", "a", "an", "to", "of",
        "in", "on", "is", "it", "its", "latest", "important",
    }
    query_words = {
        token for token in re.findall(r"[a-z0-9_]+", (query or "").lower())
        if len(token) > 2 and token not in stop_words
    }
    if not query_words:
        return [], []

    matched_roles: list[str] = []
    matched_tools: list[str] = []
    roles = blueprint.get("crew_roles") or blueprint.get("sub_agents") or []
    for role in roles:
        if not isinstance(role, dict):
            continue
        role_name = str(role.get("role") or role.get("name") or "Agent")
        corpus = " ".join(
            str(role.get(field) or "")
            for field in ("role", "goal", "backstory", "description")
        ).lower()
        role_words = {
            token for token in re.findall(r"[a-z0-9_]+", corpus)
            if len(token) > 2 and token not in stop_words
        }
        overlap = query_words & role_words
        # Two meaningful shared terms is strong evidence; one term is accepted
        # only when the role explicitly names a concrete assigned tool.
        assigned = [str(tool) for tool in (role.get("assigned_tools") or []) if str(tool)]
        if len(overlap) >= 2 or (overlap and assigned):
            matched_roles.append(role_name)
            matched_tools.extend(assigned)
    return matched_roles, list(dict.fromkeys(matched_tools))


def _recover_flight_plan_body_from_history(history: str) -> str:
    """
    Extract the readable flight-plan steps from the latest assistant plan message.

    Must match planner output that inserts --- before **Do you approve**; older regexes
    failed on that gap and returned nothing → empty plan → approval run re-invoked planner
    with a stale/wrong mission (wrong compiler execution vs UI plan).
    """
    if not history:
        return ""
    logger.info(f"Checking history for flight plan. Total length: {len(history)}")
    
    pat_new = re.compile(
        r"(?:###\s*🗺️\s*)?Proposed\s+Flight\s+Plan\s*\n\n(.*?)\n\n---\s*\n\n\s*\*\*Do\s+you\s+approve",
        re.DOTALL | re.IGNORECASE,
    )
    found = pat_new.findall(history)
    if found:
        logger.info(f"Plan recovered via 'pat_new' (len: {len(found[-1])})")
        return found[-1].strip()

    pat_legacy = re.compile(
        r"(?:###\s*🗺️\s*)?Proposed\s+Flight\s+Plan\s*\n\n(.*?)(?:\n\n\*\*Do\s+you\s+approve|\*\*Do\s+you\s+approve[^\n]*|Plan\?)",
        re.DOTALL | re.IGNORECASE,
    )
    found = pat_legacy.findall(history)
    if found:
        logger.info(f"Plan recovered via 'pat_legacy' (len: {len(found[-1])})")
        return found[-1].strip()

    logger.warning("Failed to recover flight plan from history.")
    if len(history) > 200:
        logger.debug(f"History end snippet: {history[-500:]}")
    return ""


def _recover_user_query_before_latest_plan(history: str) -> str:
    """Full user mission text for the turn that immediately preceded the latest flight plan."""
    if not history:
        return ""
    marker = "### 🗺️ Proposed Flight Plan"
    if marker not in history:
        marker = "🗺️ Proposed Flight Plan"
        if marker not in history:
            return ""
    last_idx = history.rfind(marker)
    if last_idx < 0:
        return ""
    chunk = history[:last_idx]
    idx = chunk.rfind("User:")
    if idx < 0:
        return ""
    after = chunk[idx + len("User:") :].strip()
    after = re.split(r"\n\s*(?:Agent|Assistant)(?:\s*\([^)]*\))?:", after, maxsplit=1)[0].strip()
    return after


# ✅ SAFER approval checker (NO Azure trigger)
def _advanced_approval_check(query: str, plan: str) -> bool:
    try:
        llm = _get_crewai_llm()

        prompt = f"""
User message: "{query}"

Does this message clearly approve proceeding with a previously proposed plan?

Reply ONLY with YES or NO.
"""

        res = llm.call([{"role": "user", "content": prompt}])
        return res.strip().upper().startswith("YES")

    except Exception as e:
        logger.warning(f"Approval LLM check failed: {e}")
        return None  # IMPORTANT → distinguish failure from rejection


def shield_node(state: AgentState):
    logger.info("--- SHIELD LAYER ---")
    pipeline_event("Shield", "intent_started", trace_id=state.get("trace_id"))
    TraceManager.emit(state.get("trace_id"), {"node": "shield", "status": "analyzing_intent"})

    query = GuardrailEngine.sanitize_text(state["query"])
    history = GuardrailEngine.sanitize_text(state.get("conversation_history", ""), max_len=12000)
    blueprint = state.get("blueprint", {})

    available_tools = _available_tool_ids(blueprint)

    # Classify against this agent's blueprint, never against the platform-wide
    # catalog.  This prevents a broad mission description from turning a simple
    # conversation into an unrelated workflow and gives the classifier the
    # role/tool contract needed for agentic requests.
    blueprint_lines = []
    metadata_by_tool = {
        item.get("tool_id"): item
        for item in (blueprint.get("tool_metadata") or [])
        if isinstance(item, dict) and item.get("tool_id")
    }
    for role in (blueprint.get("crew_roles") or blueprint.get("sub_agents") or []):
        if not isinstance(role, dict):
            continue
        role_name = role.get("role") or role.get("name") or "Agent"
        role_tools = role.get("assigned_tools") or []
        role_line = f"role={role_name}; goal={role.get('goal', '')}; tools={role_tools}"
        blueprint_lines.append(role_line)
    for tool_id in sorted(available_tools):
        metadata = metadata_by_tool.get(tool_id) or {}
        description = metadata.get("description") or metadata.get("remote_description") or ""
        blueprint_lines.append(f"tool={tool_id}; description={str(description)[:400]}")
    blueprint_context = "\n".join(blueprint_lines)

    # --- EMAIL EXTRACTION ---
    query_emails = _extract_emails(query)
    history_emails = _extract_emails(history)

    extracted_emails = []
    if query_emails:
        extracted_emails = [e for e in query_emails if not _is_placeholder_email(e)]
    elif history_emails:
        extracted_emails = [e for e in reversed(history_emails) if not _is_placeholder_email(e)][:1]

    pii_map = state.get("pii_map", {}) or {}

    query_tokens = _extract_email_tokens(query)
    history_tokens = _extract_email_tokens(history)

    target_token = query_tokens[-1] if query_tokens else (history_tokens[-1] if history_tokens else "")

    if not extracted_emails and target_token:
        mapped = pii_map.get(target_token, "")
        if mapped and not _is_placeholder_email(mapped):
            extracted_emails = [mapped]

    target_email = (state.get("target_email", "") or "").strip() or (extracted_emails[0] if extracted_emails else "")

    if _is_placeholder_email(target_email):
        target_email = ""

    target_email_validated = _is_valid_email(target_email)

    # --- INTENT ---
    intent = _classify_intent_via_llm(
        query=query,
        history=history,
        available_tools=available_tools,
        blueprint_context=blueprint_context,
        pii_map=pii_map
    ) or {}

    # The local model can occasionally emit a valid but under-classified
    # `conversation` response for a multi-action request. Validate it against
    # the selected blueprint before routing; role metadata is authoritative.
    matched_roles, matched_tools = _blueprint_role_match(query, blueprint)
    # Role overlap is only a recovery hint for low-confidence model output.
    # A high-confidence conversational result must not be promoted merely
    # because a generic word (for example, "Python") appears in a role goal.
    intent_confidence = float(intent.get("confidence") or 0.0)
    if matched_roles and intent.get("mode") == "conversation" and intent_confidence < 0.65:
        intent["mode"] = "agentic"
        intent["task_type"] = "execution"
        intent["required_roles"] = list(dict.fromkeys(
            list(intent.get("required_roles") or []) + matched_roles
        ))
        valid_matched_tools = [tool for tool in matched_tools if tool in available_tools]
        intent["required_tools"] = list(dict.fromkeys(
            list(intent.get("required_tools") or []) + valid_matched_tools
        ))
        logger.info(
            "Blueprint role match promoted conversation to agentic: roles=%s tools=%s",
            matched_roles,
            valid_matched_tools,
        )

    # Natural attachment questions must use the already-normalized text when it
    # is available. Upload-time ingestion has already extracted and sanitized
    # that content; re-running extract_data_from_file is reserved for explicit
    # deep/structured analysis or missing/partial usable content.
    if _attachment_reference(query, state):
        extract_tool = "extract_data_from_file"
        attachments = state.get("attachments") or []
        usable_attachment = bool(state.get("attachment_context")) and any(
            a.get("extraction_status") in {"ok", "partial"}
            and int(a.get("text_chars") or 0) > 0
            for a in attachments
        )
        explicit_deep_analysis = bool(intent.get("requires_reprocessing", False))
        if extract_tool in available_tools and (not usable_attachment or explicit_deep_analysis):
            intent["mode"] = "agentic"
            intent["task_type"] = "file_analysis"
            intent["use_attachment"] = True
            intent["required_tools"] = list(dict.fromkeys(
                list(intent.get("required_tools") or []) + [extract_tool]
            ))
            intent["has_new_file_intent"] = True
            intent["confidence"] = max(float(intent.get("confidence") or 0), 0.95)
            logger.info("Attachment reference promoted to file workflow: tool=%s", extract_tool)
        else:
            intent["mode"] = "conversation"
            intent["task_type"] = "attachment_qa"
            intent["use_attachment"] = True
            intent["required_tools"] = []
            intent["context_file_ids"] = list(state.get("file_ids") or [])
            intent["confidence"] = max(float(intent.get("confidence") or 0), 0.90)
            logger.info("Attachment reference routed to direct Q&A; blueprint has no file tool")

    # Approval/resume messages are ambiguous to an LLM when viewed alone.
    # Treat them as an approval only when this thread has workflow state; a
    # standalone "continue" in a normal conversation must remain conversation.
    approval_words = {
        "yes", "approved", "ok", "go ahead", "approve", "yep", "sure",
        "do it", "proceed", "continue", "yes continue", "approved.",
    }
    has_workflow_state = bool(
        state.get("structured_plan")
        or state.get("plan")
        or state.get("tool_execution_id")
        or (state.get("blackboard") or {}).get("pending_tool_execution_id")
    )
    if query.strip().lower() in approval_words and has_workflow_state:
        intent["mode"] = "conversation"
        intent["task_type"] = "approval"
        intent["use_attachment"] = bool(state.get("file_ids") or state.get("file_paths"))
        intent["is_approval"] = True
        intent["confidence"] = 1.0
        logger.info("Workflow approval/resume classified explicitly: %s", query.strip())

    logger.info(f"Intent classification result: {intent}")
    pipeline_event(
        "Shield", "intent_completed", mode=intent.get("mode"),
        task_type=intent.get("task_type"),
        tools=','.join(intent.get("required_tools") or []) or "none",
    )

    required_tools = set(intent.get("required_tools", []))
    unavailable = list(required_tools - available_tools)

    if unavailable:
        return {
            "is_safe": True,
            "final_response": f"Missing required tools: {', '.join(unavailable)}",
            "error": "HITL_REQUIRED"
        }

    wants_email = intent.get("wants_email", False)
    is_approval = intent.get("is_approval", False)

    is_approved = state.get("is_approved", False)
    plan = state.get("plan", "")

    # --- 🔥 APPROVAL FIX ---
    if is_approval:
        logger.info("Approval detected → validating and recovering plan...")
        current_query = query # Store the actual "approved" message
        original_query = query

        # 🔄 Recover plan from history (must match planner markdown incl. --- before approval line)
        if not plan:
            plan = _recover_flight_plan_body_from_history(history)
            if plan:
                logger.info(f"Recovered plan from history (len: {len(plan)})")

        # 🔄 Recover original query — full text before latest flight plan (not first line only)
        recovered_q = _recover_user_query_before_latest_plan(history)
        if recovered_q:
            approval_words = {"yes", "approved", "ok", "go ahead", "approve", "yep", "sure", "do it", "proceed", "yes continue", "approved."}
            if recovered_q.lower().strip() not in approval_words:
                original_query = recovered_q
                logger.info(f"Recovered original mission query ({len(original_query)} chars)")

        # ✅ Check approval using the ACTUAL current message ("approved", "yes", etc.)
        result = _advanced_approval_check(current_query, plan)

        simple = ["approved", "yes", "ok", "go ahead", "approve", "yep", "sure", "do it", "proceed", "continue", "yes continue", "approved."]

        if result is True:
            is_approved = True
            query = original_query # Restore the mission context for the executor
        elif result is None:
            # LLM FAILED → fuzzy fallback using the actual message
            q_clean = current_query.lower().strip()
            if q_clean in simple or any(word == q_clean for word in simple):
                logger.info("Fallback approval accepted (exact).")
                is_approved = True
                query = original_query
            elif len(q_clean) < 20 and any(word in q_clean for word in simple):
                logger.info(f"Fallback approval accepted (substring match): '{q_clean}'")
                is_approved = True
                query = original_query
            elif get_close_matches(q_clean, simple, n=1, cutoff=0.75):
                matched = get_close_matches(q_clean, simple, n=1, cutoff=0.75)[0]
                logger.info(f"Fallback approval accepted (fuzzy: '{q_clean}' → '{matched}').")
                is_approved = True
                query = original_query

        else:
            logger.info("Approval rejected.")

    # --- EMAIL CHECK ---
    if wants_email and not target_email:
        # 🔍 Bypass if files are attached (email might be inside the file)
        has_files = bool(state.get("file_paths") or state.get("file_path"))
        has_file_intent = intent.get("has_new_file_intent", False) or "extract_data_from_file" in intent.get("required_tools", [])
        
        if has_files or has_file_intent:
            logger.info("Email requested but missing; allowing execution because a file is present (email may be extracted).")
        else:
            return {
                "is_safe": True,
                "final_response": "Please provide recipient email.",
                "error": "HITL_REQUIRED"
            }

    return {
        "query": query,
        "conversation_history": history,
        "is_safe": True,
        "target_email": target_email,
        "target_email_validated": target_email_validated,
        "intent": intent,
        "is_approved": is_approved,
        "plan": plan,
    }
