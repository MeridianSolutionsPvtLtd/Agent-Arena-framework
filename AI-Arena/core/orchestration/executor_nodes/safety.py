import os
import re
import json
import logging
from core.orchestration.state import AgentState
from core.security.guardrails import GuardrailEngine
from core.security.audit import emit_audit_event
from core.security.output_safety import OutputSafetyEngine
from core.orchestration.executor_nodes.utils import _available_tool_ids, _tool_capability_specs, _is_valid_email, _is_placeholder_email
from core.orchestration.registry import registry
from core.orchestration.trace import TraceManager

logger = logging.getLogger(__name__)

def safety_node(state: AgentState):
    if not state.get("is_safe"):
        return state
    if state.get("error") and state.get("error") not in ("RETRY_REQUIRED", ""):
        return state
        
    logger.info("--- SAFETY LAYER ---")
    TraceManager.emit(state.get("trace_id"), {"node": "safety", "status": "verifying_output"})
    
    output = state.get("crew_output", "")
    blueprint = state.get("blueprint", {})
    available_tools = _available_tool_ids(blueprint)
    
    intent = state.get("intent", {})
    is_email_action = intent.get("wants_email", False)
    required_tools = intent.get("required_tools", [])
    is_search_mission = any(t in ["web_search", "duckduckgo"] for t in required_tools)
    is_analysis = "extract_data_from_file" in required_tools
    
    if is_email_action or is_analysis:
        is_search_mission = False
        
    retry_count = state.get("retry_count", 0)
    loop_guard_count = int(state.get("loop_guard_count", 0))
    
    if loop_guard_count >= 2:
        return {
            "is_factual": True,
            "final_response": output,
            "error": "",
            "retry_count": 0,
            "loop_guard_count": loop_guard_count
        }
    
    # --- TABLE VALIDATION ---
    if is_search_mission and "|" not in output and retry_count < 1:
        return {
            "is_factual": False, 
            "error": "RETRY_REQUIRED",
            "retry_count": retry_count + 1,
            "loop_guard_count": loop_guard_count,
            "crew_output": "CRITICAL FAILURE: Provide a Markdown table with at least 3 results."
        }
    
    # --- CLEAN MARKDOWN FENCES ---
    def _unwrap_table_fence(match):
        return match.group(1).strip()
    output = re.sub(r"```(?:markdown|md|text)?\n([\s\S]*?)```", _unwrap_table_fence, output, flags=re.IGNORECASE)
    
    # --- CODE CONTROL ---
    asked_for_code = intent.get("requires_code", False) or "execute_python" in required_tools
    if not asked_for_code:
        output = re.sub(r'```python.*?```', '', output, flags=re.DOTALL).strip()
        output = output.replace("--- CODE EXECUTED ---", "")
    else:
        output = output.replace("--- CODE EXECUTED ---", "\n### Source Code (Verification Layer)\n")

    # --- RESULT NORMALIZATION ---
    if "**Computation Result:**" not in output:
        output = output.replace("--- RESULT ---", "\n**Computation Result:**")
    
    output = output.replace("--- ERRORS ---", "\n> [!CAUTION]\n> **System Error Detected:**\n>")

    # --- REMOVE REACT LEAKS ---
    react_patterns = [
        r"(?i)Thought:\s*[\s\S]*?(?=\n\w+:|$)",
        r"(?i)Action:\s*[\s\S]*?(?=\n\w+:|$)",
        r"(?i)Action Input:\s*[\s\S]*?(?=\n\w+:|$)",
        r"(?i)Observation:\s*[\s\S]*?(?=\n\w+:|$)",
    ]
    for pattern in react_patterns:
        output = re.sub(pattern, "", output).strip()

    output = re.sub(r'\n{3,}', '\n\n', output)

    # --- DEDUP ---
    lines = output.split('\n')
    seen = set()
    deduped = []
    for line in lines:
        clean = line.strip().lower()
        if len(clean) > 15:
            if clean in seen:
                continue
            seen.add(clean)
        deduped.append(line)
    output = '\n'.join(deduped).strip()

    # --- ✅ IMPROVED LLM TRIMMER ---
    is_structured = output.strip().startswith(("{", "[", "```"))
    if len(output) > 300 and not (is_email_action or is_analysis or is_structured):  # Guard: avoid unnecessary calls or data corruption in critical missions
        try:
            from core.orchestration.executor_nodes.llm_factory import _get_crewai_llm
            trimmer_llm = _get_crewai_llm(temperature=0)

            trim_prompt = f"""
You are an output formatter.

USER QUERY:
{state.get('query')}

AGENT OUTPUT:
{output[:6000]}

STRICT FACT PRESERVATION DIRECTIVES:
- Do NOT change any numerical values, metrics, currency, percentages, or amounts.
- Do NOT change any dates, years, timestamps, or timeframes.
- Do NOT change any names, IDs, email addresses, URLs, or entity references.
- Do NOT add any new facts or claims not present in AGENT OUTPUT.
- Do NOT remove any factual details or data needed to answer USER QUERY.
- Preserve all tables, code blocks, bullet points, and structured data EXACTLY.
- Only remove conversational filler text and redundant formatting.
- If uncertain whether text contains factual information, leave it UNCHANGED.
- Return only the cleaned output.
"""

            res = trimmer_llm.call([{"role": "user", "content": trim_prompt}])

            if res and len(res.strip()) > 50:
                output = res.strip()

        except Exception as e:
            logger.error(f"Trimmer failed: {e}")

    # --- SAFETY CHECK ---
    safety_res = OutputSafetyEngine.evaluate(
        query=state.get("query", ""),
        output=output,
        grounding_context=f"{state.get('query', '')}\n{state.get('conversation_history', '')}",
    )

    if safety_res.get("blocked"):
        logger.warning(f"Output safety policy block triggered: {safety_res.get('reason')}")
        return {
            "is_safe": False,
            "final_response": safety_res.get("reason", "Output blocked by content moderation policy."),
            "error": "",
        }

    if safety_res.get("high_risk") and retry_count < 1 and loop_guard_count < 2:
        logger.warning("Safety Engine detected high-risk hallucination markers -> forcing retry")
        return {
            "is_factual": False,
            "error": "RETRY_REQUIRED",
            "retry_count": retry_count + 1,
            "loop_guard_count": loop_guard_count + 1,
            "crew_output": "",
            "validation_feedback": (
                "CRITICAL SAFETY FAILURE: The generated output contained unverified guarantee claims "
                "or fake action statements. Regenerate using strictly factual data."
            ),
        }

    # --- PLACEHOLDER CHECK ---
    if "provided above" in output.lower() and retry_count < 1:
        return {
            "is_factual": False,
            "error": "RETRY_REQUIRED",
            "retry_count": retry_count + 1,
            "loop_guard_count": loop_guard_count,
            "crew_output": "CRITICAL FAILURE: Provide actual content. No placeholders."
        }

    output = GuardrailEngine.detokenize_text(output, state.get("pii_map", {}) or {})
    
    return {
        "is_factual": True,
        "final_response": output,
        "error": "",
        "retry_count": 0,
        "loop_guard_count": loop_guard_count,
        "pii_map": state.get("pii_map", {})
    }