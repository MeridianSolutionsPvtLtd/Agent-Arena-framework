import json
import logging
import re
from core.orchestration.state import AgentState
from core.orchestration.executor_nodes.llm_factory import _get_crewai_llm
from core.orchestration.trace import TraceManager
from utils.logger import pipeline_event

logger = logging.getLogger(__name__)


def _get_precision_instructions(min_score: float) -> str:
    """
    Returns band-specific auditor strictness instructions based on min_score.

    Bands:
      0.00 – 0.35  → LENIENT / TOLERANT
      0.36 – 0.65  → STANDARD / MODERATE
      0.66 – 0.85  → STRICT / HIGH-PRECISION
      0.86 – 1.00  → VERY STRICT / ZERO-TOLERANCE

    The returned text is injected verbatim into the validator LLM prompt so the
    auditor calibrates its alignment_score and issue detection accordingly.
    This function does NOT affect temperature, randomness, or retry limits.
    """
    if min_score <= 0.35:
        return (
            "AUDIT RIGOR & PRECISION LEVEL: LENIENT (Tolerant Review)\n"
            "- Focus ONLY on critical failures: a complete refusal to answer, "
            "extreme factual hallucinations, or severe execution errors.\n"
            "- Be tolerant of minor formatting issues, non-essential missing details, "
            "or slight tone variations that do not affect the core answer.\n"
            "- Rate alignment_score generously if the core request was meaningfully answered, "
            "even if small imperfections exist."
        )
    elif min_score <= 0.65:
        return (
            "AUDIT RIGOR & PRECISION LEVEL: STANDARD (Balanced Review)\n"
            "- Evaluate standard protocol adherence and evidence grounding at a balanced level.\n"
            "- Flag clear unsupported factual claims or missed major execution steps.\n"
            "- Deduct score proportionally for noticeable discrepancies between the output "
            "and the retrieved tool evidence, but do not penalise minor stylistic variations."
        )
    elif min_score <= 0.85:
        return (
            "AUDIT RIGOR & PRECISION LEVEL: STRICT (High-Precision Audit)\n"
            "- Perform a thorough, high-precision inspection of all claims, numbers, dates, "
            "and steps against the retrieved tool evidence.\n"
            "- Any ungrounded factual assertion, missing execution step, or approximate metric "
            "MUST reduce the alignment_score significantly.\n"
            "- Do NOT excuse shortcuts, partially completed steps, or vague answers."
        )
    else:
        return (
            "AUDIT RIGOR & PRECISION LEVEL: VERY STRICT (Zero-Tolerance Audit)\n"
            "- Apply absolute zero-tolerance for any defect, omission, unverified metric, "
            "or protocol variance.\n"
            "- If ANY factual claim is not explicitly supported by the retrieved tool evidence, "
            "or if ANY step or checklist item was not fully and correctly satisfied, "
            "set is_aligned to False or reduce alignment_score below the required threshold.\n"
            "- Rejection feedback MUST be granular, specific, and actionable."
        )


def validation_node(state: AgentState):
    """
    Advanced semantic validator with fine-tunable checklist support:
    - Validates alignment with plan + query
    - Detects hallucination / generic answers
    - Checks missing outputs
    - Loads domain-specific checklist from agent_config
    - Produces actionable retry feedback
    """
    logger.info("--- VALIDATION LAYER ---")
    pipeline_event("Validator", "started", trace_id=state.get("trace_id"))
    _tid = state.get("trace_id") or ""
    TraceManager.emit(
        _tid,
        {
            "node": "validator",
            "status": "verifying_semantic_alignment",
            "event": "validating_start",
            "label": "Quality audit — output vs plan & compliance checklist…",
        },
    )

    output = state.get("crew_output", "")
    plan = state.get("plan", "")
    structured_plan = state.get("structured_plan", [])
    query = state.get("query", "")
    retry_count = state.get("retry_count", 0)
    loop_guard_count = int(state.get("loop_guard_count", 0))

    # ── Load Fine-Tuning DNA ──
    agent_config = state.get("agent_config", {})
    validator_config = agent_config.get("validator_config", {})
    checklist = validator_config.get("checklist", [])
    min_score = float(validator_config.get("min_score", 0.5))
    custom_retry_instructions = validator_config.get("retry_instructions", "")

    # --- HARD GUARD ---
    if not plan or loop_guard_count >= 2 or retry_count >= 2:
        if _tid:
            TraceManager.emit(
                _tid,
                {"event": "validating_complete", "outcome": "skipped", "reason": "guard_or_retry_limits"},
            )
        return {
            "error": state.get("error", ""),
            "is_factual": True
        }

    # --- FAST FAILURE DETECTION ---
    error_tokens = ["[Error:", "Traceback", "No console output", "SyntaxError"]
    if any(tok in output for tok in error_tokens):
        logger.warning("Execution output contains errors → forcing retry")
        if _tid:
            TraceManager.emit(
                _tid,
                {"event": "validating_complete", "outcome": "retry", "reason": "execution_errors_in_output"},
            )
        return {
            "is_factual": False,
            "error": "RETRY_REQUIRED",
            "retry_count": retry_count + 1,
            "loop_guard_count": loop_guard_count + 1,
            "crew_output": "",
            "validation_feedback": (
                "Execution failed. Fix the error and strictly follow the structured plan."
            )
        }

    protocol_str = (
        json.dumps(structured_plan, indent=2)
        if structured_plan else plan
    )

    # ── Format Bounded Tool Evidence ──
    step_outputs = state.get("step_outputs", [])
    blackboard = state.get("blackboard", {})

    evidence_blocks = []
    if step_outputs:
        for item in step_outputs:
            step_num = item.get("step", "?")
            task_desc = (item.get("task") or "").strip()
            out_val = (str(item.get("output", "")) or "").strip()
            if len(out_val) > 800:
                out_val = out_val[:800] + " ... [truncated]"
            evidence_blocks.append(f"Step {step_num} ({task_desc}):\n{out_val}")
    elif blackboard:
        for k, v in blackboard.items():
            val_str = str(v).strip()
            if len(val_str) > 800:
                val_str = val_str[:800] + " ... [truncated]"
            evidence_blocks.append(f"[{k}]: {val_str}")

    evidence_str = "\n\n".join(evidence_blocks) if evidence_blocks else "(No explicit tool evidence recorded)"
    if len(evidence_str) > 3500:
        evidence_str = evidence_str[:3500] + "\n... [evidence budget limit reached]"

    # ── Build Checklist Section ──
    checklist_section = ""
    if checklist:
        checklist_items = "\n".join([f"  - {item}" for item in checklist])
        checklist_section = f"""
6. DOMAIN-SPECIFIC CHECKLIST (from Agent Config):
   The following items MUST be present in the output.
   Score each item as PASS or FAIL:
{checklist_items}
"""

    # ── Resolve precision-level instructions for this run ──
    precision_instructions = _get_precision_instructions(min_score)

    # --- GPT-4o OPTIMIZED AUDITOR PROMPT ---
    validation_prompt = f"""
You are a Senior Quality Assurance Auditor. Your objective is to perform a rigorous, hyper-critical review of the agent's work.

{precision_instructions}

INPUTS FOR AUDIT:
1. USER QUERY: {query}
2. EXECUTION PROTOCOL (The Plan): {protocol_str}
3. RETRIEVED TOOL EVIDENCE (Source of Truth):
{evidence_str}
4. AGENT FINAL OUTPUT: {output[:4000]}

AUDIT CRITERIA (Strict Enforcement):
1. PROTOCOL ADHERENCE: Did the agent execute EVERY step of the protocol? If it skipped a tool call or took a shortcut, it is a FAIL.
2. SOURCE GROUNDING & EVIDENCE CONSISTENCY: Compare all numbers, dates, names, and key claims in the AGENT FINAL OUTPUT against the RETRIEVED TOOL EVIDENCE. Any factual value, metric, or detail in the output that contradicts or is unsupported by the retrieved tool evidence MUST be flagged as an issue and reduces the alignment_score. If it looks like a generic LLM hallucination unsupported by evidence, it is a FAIL.
3. PARAMETER INTEGRITY: Did the agent respect specific parameters (e.g., sending to the EXACT email requested, using the EXACT file path)?
4. VERACITY: Are numbers, names, and dates factually consistent with the provided context and tool evidence?
5. DOMAIN ALIGNMENT: Does the tone and structure meet the standards of the industry domain?
{checklist_section}

STRICT SCORING RULES:
- If ANY checklist item is FAIL, the alignment_score MUST be below 0.5.
- If the agent missed a 'send_email' or 'execute_python' step when requested, is_aligned MUST be False.

OUTPUT FORMAT (STRICT JSON ONLY):
{{
  "is_aligned": <bool>,
  "alignment_score": <float 0.0 to 1.0>,
  "missing_elements": ["<list specific missing actions or data>"],
  "issues": ["<list specific hallucinations or errors>"],
  "checklist_results": {{"<item>": "PASS/FAIL"}},
  "feedback": "<precise instruction for the agent to fix the work in the NEXT iteration>"
}}
"""

    try:
        val_llm = _get_crewai_llm()
        res = val_llm.call([{"role": "user", "content": validation_prompt}])

        clean_res = res.strip()

        # --- CLEAN MARKDOWN ---
        if clean_res.startswith("```"):
            clean_res = re.sub(
                r"```(?:json)?\n?([\s\S]*?)```",
                r"\1",
                clean_res
            ).strip()

        try:
            val_data = json.loads(clean_res)
        except Exception:
            logger.warning("Validator JSON parsing failed → fallback triggered")
            val_data = {
                "is_aligned": False,
                "alignment_score": 0.3,
                "missing_elements": ["Unknown (parsing failure)"],
                "issues": ["Validator could not parse response"],
                "checklist_results": {},
                "feedback": "Re-execute strictly following structured steps."
            }

        # --- SAFE DEFAULTS ---
        is_aligned = val_data.get("is_aligned", True)
        score = float(val_data.get("alignment_score", 0.6))

        # ── Log Checklist Results ──
        checklist_results = val_data.get("checklist_results", {})
        if checklist_results:
            failed_items = [item for item, result in checklist_results.items() if result.upper() == "FAIL"]
            if failed_items:
                logger.warning(f"Validator checklist failures: {failed_items}")
                # Reduce score proportionally for failed checklist items
                if checklist:
                    fail_ratio = len(failed_items) / len(checklist)
                    score = score * (1 - fail_ratio * 0.5)

        # --- SMART REJECTION ---
        if not is_aligned or score < min_score:
            feedback_text = val_data.get(
                "feedback",
                "Execution did not follow protocol."
            )

            # ── Inject Custom Retry Instructions ──
            if custom_retry_instructions:
                feedback_text += f"\n\nAGENT-SPECIFIC INSTRUCTIONS:\n{custom_retry_instructions}"

            # ── Inject Failed Checklist Items ──
            if checklist_results:
                failed = [item for item, result in checklist_results.items() if result.upper() == "FAIL"]
                if failed:
                    feedback_text += "\n\nFAILED CHECKLIST ITEMS:\n" + "\n".join([f"- {f}" for f in failed])

            feedback_text += (
                "\n\nSTRICT INSTRUCTION:\n"
                "- Follow EACH step in structured_plan\n"
                "- Do NOT skip tool usage\n"
                "- Do NOT generate generic answers\n"
                "- Output ONLY final results\n"
            )

            logger.warning(f"Validator rejected output | Score: {score}")

            if _tid:
                TraceManager.emit(
                    _tid,
                    {"event": "validating_complete", "outcome": "rejected", "score": score},
                )

            return {
                "is_factual": False,
                "error": "RETRY_REQUIRED",
                "retry_count": retry_count + 1,
                "loop_guard_count": loop_guard_count + 1,
                "crew_output": output,
                "validation_feedback": feedback_text
            }

        # --- PASS CASE ---
        logger.info(f"Validator passed | Score: {score}")
        if _tid:
            TraceManager.emit(
                _tid,
                {"event": "validating_complete", "outcome": "passed", "score": score},
            )

    except Exception as e:
        logger.error(f"Validator LLM failed: {e}")
        if _tid:
            TraceManager.emit(
                _tid,
                {"event": "validating_complete", "outcome": "error", "reason": str(e)[:200]},
            )

    return {
        "error": state.get("error", ""),
        "is_factual": True
    }
