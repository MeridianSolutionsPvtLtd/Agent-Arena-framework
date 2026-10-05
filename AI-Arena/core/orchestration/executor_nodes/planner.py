import json
import logging
from core.orchestration.state import AgentState
from core.security.audit import emit_audit_event
from core.orchestration.azure_settings import litellm_completion, get_llm_provider, model_completion
from core.orchestration.executor_nodes.llm_factory import _get_crewai_llm
from core.orchestration.trace import TraceManager
from utils.logger import pipeline_event

logger = logging.getLogger(__name__)


def _fallback_blueprint_plan(state: AgentState) -> list[dict]:
    """Build a minimal plan from validated blueprint assignments.

    This is only used when local Ollama cannot return parseable JSON. It does
    not invent tools: every step comes from the intent and the selected role's
    assigned_tools, preserving the same governance boundary as the LLM path.
    """
    intent = state.get("intent", {}) or {}
    requested = [str(tool) for tool in (intent.get("required_tools") or []) if str(tool)]
    roles = state.get("blueprint", {}).get("crew_roles") or state.get("blueprint", {}).get("sub_agents") or []
    role_by_tool = {}
    for role in roles:
        if not isinstance(role, dict):
            continue
        name = role.get("role") or role.get("name") or "Agent"
        for tool in role.get("assigned_tools") or []:
            role_by_tool[str(tool)] = str(name)
    steps = []
    for index, tool in enumerate(requested, 1):
        steps.append({
            "step": index,
            "role": role_by_tool.get(tool, "Agent"),
            "task": f"Use {tool} to complete the relevant part of the user's request.",
            "tool": tool,
        })
    return steps

def planner_node(state: AgentState):
    """Generates a structured execution plan with tool binding."""

    # An approved continuation already has a structured plan. An approved
    # state without a plan still needs planning (for example, a conversation
    # request); do not skip this node in that case.
    if not state.get("is_safe") or (
        state.get("is_approved") and state.get("structured_plan")
    ):
        return state

    logger.info("--- PLANNER LAYER ---")
    pipeline_event("Planner", "started", trace_id=state.get("trace_id"))
    _tid = state.get("trace_id") or ""
    TraceManager.emit(
        _tid,
        {"node": "planner", "status": "generating_flight_plan", "event": "planning_start", "label": "Architecting flight plan & specialist routing…"},
    )

    query = state["query"]
    history = state.get("conversation_history", "")
    intent = state.get("intent", {})

    # ── Load Fine-Tuning DNA ──
    agent_config = state.get("agent_config", {})
    sub_agents = agent_config.get("sub_agents", [])
    executor_policy = agent_config.get("executor_policy", {})

    required_tools = intent.get("required_tools", [])
    task_mode = intent.get("mode", "agentic")
    task_type = intent.get("task_type", "execution" if task_mode == "agentic" else "conversation")
    requires_code = intent.get("requires_code", False)
    wants_email = intent.get("wants_email", False)

    # Direct conversational/general responses must not inherit every tool from
    # a blueprint whose mission happens to be web research. Explicit tool
    # intent, files, code, and email requests continue through planning.
    if (
        task_type == "conversation"
        or task_mode == "conversation"
        or not required_tools
        and not wants_email
        and not requires_code
        and not state.get("file_paths")
        and not intent.get("has_new_file_intent", False)
    ):
        direct_context = query
        attachment_context = state.get("attachment_context", "")
        if intent.get("use_attachment") and attachment_context:
            direct_context = (
                "Answer the user's question using the attached-document context below. "
                "Do not claim facts that are not present in the document.\n\n"
                f"User question:\n{query}\n\n"
                f"Attached-document context:\n{attachment_context[:16000]}"
            )
        response = model_completion(
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Respond naturally to the user's conversational message in no more than two concise paragraphs. "
                        "Do not propose tools or a workflow. For attachment questions, answer only from the supplied "
                        "attached-document context and say when the document does not contain the answer."
                    ),
                },
                {"role": "user", "content": direct_context},
            ],
            max_tokens=1000,
            temperature=0.2,
        ).choices[0].message.content.strip()
        if _tid:
            TraceManager.emit(
                _tid,
                {"event": "planning_complete", "mode": "direct_response", "step_count": 0, "label": "Direct response — no tool required"},
            )
        pipeline_event("Planner", "direct_response", step_count=0, mode="conversation")
        return {
            "is_approved": True,
            "plan": "",
            "final_response": response,
            "direct_response": True,
            "structured_plan": [],
        }

    from core.orchestration.executor_nodes.utils import _available_tool_ids, _tool_capability_specs
    available_tools = _available_tool_ids(state.get("blueprint", {}))
    specs = _tool_capability_specs()

    # Designed and implemented by Rajadurai R.
    # Give the planner safe catalog metadata only; execution contracts remain broker-owned.
    governed_metadata = {
        item.get("tool_id"): item
        for item in (state.get("blueprint", {}).get("tool_metadata") or [])
        if isinstance(item, dict) and item.get("tool_id")
    }

    tool_context = "\n".join([
        f"- {t_id}: "
        f"{(governed_metadata.get(t_id) or specs.get(t_id) or {}).get('description', '')[:200]}"
        for t_id in available_tools
    ])

    enforcement_rules = ""
    if required_tools:
        enforcement_rules += f"\nMANDATORY TOOLS: {required_tools}"
    if requires_code:
        enforcement_rules += "\nMust use execute_python for calculations."
    if wants_email:
        enforcement_rules += "\nMust use send_email as final step."

    file_paths = state.get("file_paths", [])
    if file_paths:
        enforcement_rules += f"\nATTACHED FILES: {file_paths}\nCRITICAL: If multiple files are attached and the user asks to analyze/compare them, you MUST create a separate `extract_data_from_file` step for EACH file, specifying the exact absolute path in the task description."

    # ── Inject Sub-Agent Roles ──
    role_context = ""
    if sub_agents:
        role_lines = []
        for sa in sub_agents:
            tools_list = ", ".join(sa.get("assigned_tools", [])) or "None"
            role_lines.append(f"- {sa.get('role', 'Agent')} (Tools: {tools_list}): Goal: {sa.get('goal', 'N/A')} | Backstory: {sa.get('backstory', '')}")
        role_context = "\nAVAILABLE SUB-AGENT ROLES:\n" + "\n".join(role_lines)
        role_context += "\nAssign each step to the most relevant sub-agent role, strictly respecting their allowed tools."

    # ── Inject Executor Policy ──
    policy_context = ""
    if executor_policy:
        email_strategy = executor_policy.get("email_strategy", "auto")
        if email_strategy == "winner_only":
            policy_context += "\nEMAIL POLICY: Only send emails to the selected/best vendor. Do NOT broadcast."
        elif email_strategy == "broadcast":
            policy_context += "\nEMAIL POLICY: Send emails to ALL vendors."

        if executor_policy.get("strict_spec_compliance"):
            policy_context += "\nSPEC COMPLIANCE: Use ONLY the exact specifications from the user's request. Do not add or hallucinate specs."

    tool_governance = state.get("blueprint", {}).get("tool_governance") or {}
    for tool_id, governance in tool_governance.items():
        if tool_id not in available_tools or not isinstance(governance, dict):
            continue
        purpose = governance.get("purpose") or ""
        instruction = governance.get("usage_instruction") or ""
        confirmation = " Confirmation is mandatory." if governance.get("confirmation_required") else ""
        policy_context += (
            f"\nTOOL POLICY [{tool_id}]: Purpose: {purpose}. "
            f"Instruction: {instruction}.{confirmation}"
        )

    max_steps = executor_policy.get("max_steps", 8) if executor_policy else 8

    # ── Agent Mission Context ──
    agent_mission = state.get("blueprint", {}).get("system_prompt", "")
    agent_intent = state.get("blueprint", {}).get("user_intent", "")
    mission_context = f"\nAGENT CORE MISSION:\n{agent_mission}\n{agent_intent}"

    # ── Temporal Context ──
    from datetime import datetime
    current_date = datetime.now().strftime("%B %d, %Y")
    current_month_year = datetime.now().strftime("%B %Y")

    # 🔥 INTENT-SCOPE ISOLATED STRATEGIC PLANNER PROMPT
    plan_prompt = f"""
You are a Lead Systems Engineer & Strategic Planner. Your task is to architect a **minimal, precisely-scoped** 'Flight Plan' that satisfies ONLY the user's immediate request.

🕐 TODAY'S DATE: {current_date}
TEMPORAL RULES:
- If the user's query contains a SPECIFIC YEAR (e.g., "2025", "2024"), use THAT year in your task descriptions. Do NOT override it with today's date.
- ONLY when the user says "recent", "latest", "current", or "today" WITHOUT specifying a year, include "{current_month_year}" in search task descriptions to ensure fresh results.
- NEVER rely on your training data for time-sensitive information — always delegate to web_search.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🔒 STEP 0 — MANDATORY SCOPE ANALYSIS (do this FIRST)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Before generating ANY steps, you MUST perform a silent Scope Analysis:
1. Extract the PRIMARY VERB from the user's query (e.g., "draft", "create", "analyze", "compare", "send", "find").
2. Extract the PRIMARY OBJECT (e.g., "requirement proposal", "purchase order", "comparison report").
3. The plan MUST ONLY accomplish: [PRIMARY VERB] + [PRIMARY OBJECT].
4. Any step that goes BEYOND this scope is a VIOLATION and must be removed.

Example Scope Analysis:
- Query: "Draft a requirement proposal for 50 rackets" → Verb: DRAFT, Object: REQUIREMENT PROPOSAL → Plan should ONLY draft the proposal. Do NOT add vendor analysis, PO generation, or email steps.
- Query: "Analyze these vendor quotations and rank them" → Verb: ANALYZE + RANK, Object: VENDOR QUOTATIONS → Plan should ONLY extract data and summarize rankings. Do NOT add PO or email steps.
- Query: "Send the purchase order to the best vendor" → Verb: SEND, Object: PURCHASE ORDER → Plan should generate PO and send email.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📋 MISSION PARAMETERS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
- USER QUERY: {query}
- INTENT CLASSIFICATION: {intent}
- AVAILABLE ROLES: {role_context}
- EXECUTION POLICIES: {policy_context}
{enforcement_rules}

BACKGROUND CONTEXT (for understanding the agent's domain — NOT for expanding scope):
{mission_context}
⚠️ The above AGENT CORE MISSION describes the agent's FULL lifecycle capabilities. It is NOT a directive to execute ALL capabilities in every request. Use it ONLY to understand the domain vocabulary and role assignments.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🚫 HARD CONSTRAINTS (violations = plan failure)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. **SCOPE CEILING**: The plan MUST NOT exceed the scope identified in Step 0. If the user asks to "draft a proposal", you produce ONLY the proposal. You do NOT add vendor lookup, PO generation, or email dispatch — even if those tools exist and those roles are available.
2. **VERB-GATE**: Each step's tool must directly serve the PRIMARY VERB. If a tool serves a FUTURE verb the user hasn't requested yet, EXCLUDE it.
3. **NO SPECULATIVE STEPS**: Do NOT add steps "in case the user might want them later." The user will ask for the next phase when ready.
4. **ROLE-TOOL STRICTNESS**: You MUST NOT assign a tool to a role if that role does not explicitly possess it in the AVAILABLE ROLES list.
5. **MAX STEPS**: 1 to {max_steps} steps. Prefer fewer steps. A 1-step plan is perfectly valid.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📏 OPERATIONAL GUIDELINES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
- TOOL BOUNDING: Use ONLY the following tools:
{tool_context}
- DATA FLOW: Ensure every step logically leads to the next.
- **TEMPORAL BOUNDARY**: Every query is a fresh mission. If the user's current query does NOT explicitly mention 'Quotation', 'Comparison', or 'Purchase Order', you MUST NOT include steps for those workflows.
- **CONTEXTUAL AMNESIA**: Ignore all data, vendors, or documents from previous missions unless the user's CURRENT query explicitly asks to "use", "reference", or "continue" from them.
- **SEARCH GRANULARITY**: If you need to find resources for multiple distinct topics, create a separate step for EACH topic.
- **QUERY PRECISION**: Use keyword-rich queries for search tools.
- **VERBATIM CITATION**: Copy URLs exactly as they appear in tool outputs.
- If math or calculations are required, you MUST use 'execute_python'.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🚨 ANTI-PATTERNS (you MUST NOT do these)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
❌ User says "draft a proposal" → Plan includes vendor analysis + PO + email (WRONG — scope is only "draft")
❌ User says "analyze quotations" → Plan includes PO generation + email dispatch (WRONG — scope is only "analyze")
❌ User says "create a report" → Plan adds email step because send_email tool exists (WRONG — tool existence ≠ user intent)
✅ User says "draft a proposal" → Plan has 1 step: generate_report to draft the proposal (CORRECT)
✅ User says "analyze quotations and send PO to best vendor" → Plan includes extract + analyze + generate PO + email (CORRECT — user explicitly asked for all phases)

OUTPUT FORMAT (STRICT JSON ONLY):
[
  {{
    "step": 1,
    "role": "Assigned Sub-Agent Role (e.g. RFP Specialist)",
    "task": "High-fidelity description of the specific action",
    "tool": "tool_id"
  }}
]
"""

    try:
        raw = model_completion(
            messages=[{"role": "user", "content": plan_prompt}],
            max_tokens=2500,
            temperature=0,
        ).choices[0].message.content.strip()

        # Robust JSON extraction
        structured_plan = None
        if "```json" in raw:
            raw_json = raw.split("```json")[1].split("```")[0].strip()
        else:
            raw_json = raw

        # Attempt to find the array using regex if direct parse fails
        import re
        match = re.search(r'\[\s*\{.*?\}\s*\]', raw_json, re.DOTALL)
        if match:
            raw_json = match.group(0)

        try:
            structured_plan = json.loads(raw_json)
        except Exception as e:
            logger.error(f"Failed to parse Planner JSON. Raw LLM output: {raw}")
            raise e

        # 🔥 safety validation
        if not isinstance(structured_plan, list) or len(structured_plan) == 0:
            raise ValueError("Invalid plan structure")

        # Human-readable Markdown: blank lines between steps so ReactMarkdown renders separate blocks.
        step_blocks = []
        for i, s in enumerate(structured_plan):
            role = s.get("role", "Agent")
            task = s.get("task", "")
            tool = s.get("tool", "")
            try:
                n = int(s.get("step", i + 1))
            except (TypeError, ValueError):
                n = i + 1
            step_blocks.append(
                f"**Step {n} · {role}**\n\n{task}\n\n*Tool:* `{tool}`"
            )
        readable_plan = "\n\n".join(step_blocks)

        from core.security.guardrails import GuardrailEngine
        pii_map = state.get("pii_map", {}) or {}

        flight_plan = (
            "### 🗺️ Proposed Flight Plan\n\n"
            f"{readable_plan}\n\n"
            "---\n\n"
            "**Do you approve of this plan?**"
        )
        flight_plan = GuardrailEngine.detokenize_text(flight_plan, pii_map)

        emit_audit_event(
            "plan_generated",
            trace_id=state.get("trace_id"),
            plan_preview=readable_plan[:200]
        )

        if _tid:
            plan_steps = []
            for i, s in enumerate(structured_plan):
                try:
                    sn = int(s.get("step", i + 1))
                except (TypeError, ValueError):
                    sn = i + 1
                plan_steps.append(
                    {
                        "step": sn,
                        "role": str(s.get("role", "Agent")),
                        "task": str(s.get("task", "")),
                        "tool": str(s.get("tool", "")),
                    }
                )
            TraceManager.emit(
                _tid,
                {
                    "event": "planning_complete",
                    "mode": "hitl",
                    "step_count": len(structured_plan),
                    "label": f"Flight plan ready ({len(structured_plan)} steps)",
                    "plan_steps": plan_steps,
                },
            )

        # A single read-only step can run without a separate flight-plan
        # confirmation. Approval remains catalog-driven; missing metadata is
        # conservative, while WRITE/DESTRUCTIVE tools still pause.
        auto_execute = False
        tool_id = ""
        if len(structured_plan) == 1:
            tool_id = str(structured_plan[0].get("tool") or "")
            metadata = governed_metadata.get(tool_id) or {}
            policy = metadata.get("spec") if isinstance(metadata.get("spec"), dict) else metadata
            risk = str(policy.get("risk_level") or policy.get("risk") or "").lower()
            requires_approval = policy.get("requires_approval")
            auto_execute = bool(
                metadata
                and requires_approval is not True
                and risk in {"read_only", "sensitive_read", "readonly", "sensitive-read"}
            )
        if auto_execute:
            pipeline_event("Planner", "plan_auto_approved", step_count=1, tool=tool_id)
            return {
                "plan": readable_plan,
                "structured_plan": structured_plan,
                "final_response": "",
                "error": "",
                "is_approved": True,
            }

        pipeline_event("Planner", "plan_created", step_count=len(structured_plan), mode="approval")
        return {
            "plan": readable_plan,
            "structured_plan": structured_plan,
            "final_response": flight_plan,
            "error": "HITL_REQUIRED",
            "is_factual": True
        }

    except Exception as e:
        logger.error(f"Planning failed: {e}")
        fallback_plan = _fallback_blueprint_plan(state)
        if fallback_plan:
            # Preserve HITL semantics while avoiding a false input error when
            # the only failure was local-model plan formatting.
            readable = "\n\n".join(
                f"**Step {step['step']} · {step['role']}**\n\n{step['task']}\n\n*Tool:* `{step['tool']}`"
                for step in fallback_plan
            )
            logger.warning("Using validated blueprint fallback plan after planner failure")
            pipeline_event("Planner", "plan_created", step_count=len(fallback_plan), mode="fallback")
            return {
                "plan": readable,
                "structured_plan": fallback_plan,
                "final_response": "### 🗺️ Proposed Flight Plan\n\n" + readable + "\n\n---\n\n**Do you approve of this plan?**",
                "error": "HITL_REQUIRED",
                "is_factual": True,
            }
        if _tid:
            TraceManager.emit(
                _tid,
                {"event": "planning_failed", "label": str(e)[:240]},
            )
        return {
            "is_approved": False,
            "final_response": "I encountered an error while generating the plan. Please try again.",
            "error": "HITL_REQUIRED"
        }
