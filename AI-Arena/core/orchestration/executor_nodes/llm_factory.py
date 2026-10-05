import os
import logging
from crewai import LLM
from core.security.guardrails import GuardrailEngine
from core.orchestration.azure_settings import (
    get_llm_provider,
    litellm_completion,
)

logger = logging.getLogger(__name__)

# 🔥 SAFE PROMPT
_INTENT_CLASSIFICATION_PROMPT = """\
You are an intent classifier for an AI agent platform.

Analyze the CURRENT USER QUERY in the context of the CONVERSATION HISTORY.

---

CONVERSATION HISTORY (recent):
{history_snippet}

CURRENT USER QUERY:
{query}

---

BLUEPRINT CAPABILITIES (the only capabilities this agent may use):
{available_tools}

BLUEPRINT ROLES AND TOOL DESCRIPTIONS:
{blueprint_context}

---

Classify the intent by responding ONLY with valid JSON (no markdown, no explanation):

{{
  "mode": "conversation" or "agentic",
  "task_type": "conversation", "attachment_qa", "file_analysis", "execution", or "approval",
  "use_attachment": <bool; true only when the current message refers to an attached/thread-bound file>,
  "requires_reprocessing": <bool; true only when the file must be freshly/deeply/structurally reprocessed>,
  "required_capabilities": [<short capability names supported by the blueprint>],
  "required_roles": [<blueprint role names>],
  "is_approval": <bool>,
  "wants_email": <bool>,
  "required_tools": [<tool_id>, ...],
  "requires_code": <bool>,
  "requires_mcq": <bool>,
  "is_list_delivery": <bool>,
  "is_summary_followup": <bool>,
  "has_new_file_intent": <bool>,
  "is_email_followup": <bool>,
  "confidence": <float between 0 and 1>,
  "reason": <one short sentence explaining the current-turn decision>
}}

---

GUIDELINES:

1. TOOL SELECTION:
- Only use tool IDs from the AVAILABLE TOOLS list.
- Do not invent tool names.
- Use exact IDs like "execute_python", "send_email".
- A tool is required when the user asks the agent to perform an action, transform supplied content, retrieve external data, or produce a governed artifact. Ordinary greetings, explanations, and questions about the assistant are conversation.
- Self-description, greetings, capability questions, and ordinary explanations are always conversation. Do not select `web_search` for them, even when the blueprint contains a research role.
- Ground the decision in the current blueprint roles and tool descriptions. Do not activate capabilities merely because they exist elsewhere in the platform.
- An available attachment is context, not an automatic workflow. Set `use_attachment=true` only when the current message refers to that file/document/content; unrelated questions set it to false.
- If normalized attachment text is already available in the conversation context, ordinary questions about that content are `attachment_qa` with no tool. Set `requires_reprocessing=true` only for explicit deep extraction, table/row calculations, comparison requiring raw files, or when the supplied content is insufficient.
- First compare the requested action with each blueprint role's goal and assigned tools. If a role can perform the requested action, classify as `execution`, return that role in `required_roles`, and select only its assigned tool IDs. If no role/tool applies and the user is only asking for an answer or explanation, classify as `conversation`.
- Never create a new sub-agent role. Never use the agent's general mission as proof that every request needs the full workflow.

2. TOOL REQUIREMENT LOGIC:
- User needs a mathematical calculation → "execute_python"
- User wants to send an email → "send_email"
- User explicitly wants to read or extract data from a provided file → "extract_data_from_file"
- User wants to summarize large text → "summarize_content"
- User needs general knowledge, remedies, latest info, news, or a web search → "web_search"
- User wants to collect web data into a dataset, compare sources, fetch prices, or create charts/trends → "data_collector_visualizer"

CRITICAL TOOL RULE:
If the user explicitly says NOT to use the file/report, or if they ask a general knowledge question that is unrelated to the file (e.g., general remedies), DO NOT require "extract_data_from_file". Instead, use "web_search".

3. EMAIL INTENT:
- set wants_email = true ONLY if the user is explicitly asking to send, mail, or broadcast a result right now. 
- If they use "to be sent" or "for vendors" as a description of a document's purpose, set wants_email = false.

4. APPROVAL HANDLING:
- If query is like "yes", "approved", "go ahead":
  → set is_approval = true
  → Preserve other fields from previous state

4. ACCURACY:
- Return valid JSON.
- Confidence should reflect your certainty (0.0–1.0).
"""


def _to_bool(x):
    return str(x).lower() == "true"


def _get_crewai_llm(temperature: float = 0) -> LLM:
    provider = get_llm_provider()

    if provider == "ollama":
        return LLM(
            model=f"ollama/{os.getenv('OLLAMA_MODEL', 'llama3.1')}",
            base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
            temperature=temperature,
        )

    raise ValueError(f"Unsupported LLM_PROVIDER: {provider}; only ollama is supported")


def _classify_intent_via_llm(
    query: str,
    history: str,
    available_tools: set,
    blueprint_context: str = "",
    pii_map: dict = None,
) -> dict:
    try:
        import json

        history_snippet = (history or "")[-8000:]
        if pii_map:
            history_snippet = GuardrailEngine.detokenize_text(history_snippet, pii_map)

        prompt = _INTENT_CLASSIFICATION_PROMPT.format(
            history_snippet=history_snippet,
            query=query,
            available_tools=sorted(list(available_tools)),
            blueprint_context=blueprint_context or "(No blueprint metadata supplied)",
        )

        raw = litellm_completion(prompt, max_tokens=350, temperature=0, json_mode=True)

        if raw.startswith("```"):
            raw = raw.replace("```json", "").replace("```", "").strip()

        intent = json.loads(raw)

        valid_tools = set(available_tools)
        filtered_tools = [t for t in intent.get("required_tools", []) if t in valid_tools]

        conf = float(intent.get("confidence", 0.8))
        conf = max(0.0, min(1.0, conf))

        result = {
            "mode": str(intent.get("mode", "agentic")).strip().lower(),
            "task_type": str(intent.get("task_type", "")).strip().lower(),
            "use_attachment": _to_bool(intent.get("use_attachment", False)),
            "requires_reprocessing": _to_bool(intent.get("requires_reprocessing", False)),
            "required_capabilities": [str(x).strip() for x in (intent.get("required_capabilities") or []) if str(x).strip()],
            "required_roles": [str(x).strip() for x in (intent.get("required_roles") or []) if str(x).strip()],
            "is_approval": _to_bool(intent.get("is_approval", False)),
            "wants_email": _to_bool(intent.get("wants_email", False)),
            "required_tools": filtered_tools,
            "requires_code": _to_bool(intent.get("requires_code", False)),
            "requires_mcq": _to_bool(intent.get("requires_mcq", False)),
            "is_list_delivery": _to_bool(intent.get("is_list_delivery", False)),
            "is_summary_followup": _to_bool(intent.get("is_summary_followup", False)),
            "has_new_file_intent": _to_bool(intent.get("has_new_file_intent", False)),
            "is_email_followup": _to_bool(intent.get("is_email_followup", False)),
            "confidence": conf,
            "reason": str(intent.get("reason", "")).strip()[:240],
        }
        if result["mode"] not in {"conversation", "agentic"}:
            result["mode"] = "agentic" if result["required_tools"] else "conversation"
        if result["task_type"] not in {"conversation", "attachment_qa", "file_analysis", "execution", "approval"}:
            result["task_type"] = "execution" if result["mode"] == "agentic" else "conversation"
        # A blueprint role/capability match is also agentic even when the
        # model did not emit a concrete tool ID. The planner will bind the
        # validated role to its assigned tools; this avoids turning a valid
        # blueprint task into direct chat just because the small local model
        # omitted one optional JSON field.
        if (
            result["required_tools"]
            or result["required_roles"]
            or result["required_capabilities"]
            or result["wants_email"]
            or result["requires_code"]
            or result["has_new_file_intent"]
        ):
            result["mode"] = "agentic"
            result["task_type"] = "execution"
        elif result["task_type"] == "execution":
            result["mode"] = "agentic"

        logger.info("LLM Intent Classification: %s", result)
        return result

    except Exception as e:
        logger.warning("LLM intent classification failed (%s)", e)
        return _intent_fallback(query, available_tools)


def _intent_fallback(query: str, available_tools: set) -> dict:
    q = (query or "").lower().strip()
    approval_words = [
        "yes", "approved", "go ahead", "ok", "sure", "approve", "yep", "proceed", "continue", "yes continue",
    ]
    from difflib import get_close_matches

    is_fuzzy_approval = (
        q in approval_words
        or bool(get_close_matches(q, approval_words, n=1, cutoff=0.75))
        or (len(q) < 20 and any(w in q for w in approval_words))
    )

    required_tools = []
    if "web_search" in available_tools and any(
        x in q for x in ["news", "latest", "current", "headline", "today", "recent", "search", "look up", "find online"]
    ):
        required_tools.append("web_search")

    return {
        "mode": "agentic" if (
            required_tools
            or any(x in q for x in ["calculate", "compute", "code"])
            or "email" in q
            or "send" in q
            or "file" in q
            or "upload" in q
        ) else "conversation",
        "is_approval": is_fuzzy_approval,
        "task_type": "approval" if is_fuzzy_approval else "conversation",
        "use_attachment": False,
        "requires_reprocessing": False,
        "wants_email": ("email" in q) or ("send" in q and "@" in q),
        "required_tools": required_tools,
        "requires_code": any(x in q for x in ["calculate", "compute", "code"]),
        "requires_mcq": "mcq" in q,
        "is_list_delivery": "multiple" in q or "list" in q,
        "is_summary_followup": "summary" in q,
        "has_new_file_intent": "file" in q or "upload" in q,
        "is_email_followup": "@" in q,
        "confidence": 0.5,
    }
