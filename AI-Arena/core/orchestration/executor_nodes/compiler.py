import logging
import json
from core.orchestration.state import AgentState
from core.orchestration.executor_nodes.llm_factory import _get_crewai_llm
from core.orchestration.azure_settings import model_completion, get_llm_provider
from core.orchestration.trace import TraceManager

logger = logging.getLogger(__name__)

def compiler_node(state: AgentState):
    """
    Translates a Markdown Flight Plan into a structured JSON execution protocol.
    This bridges the 'reasoning gap' between planning and execution.
    """
    if not state.get("plan") or not state.get("is_approved"):
        return state

    # If the plan is already structured (e.g., from a previous loop), skip.
    if state.get("structured_plan"):
        return state

    logger.info("--- PLAN COMPILER LAYER ---")
    _tid = state.get("trace_id") or ""
    TraceManager.emit(
        _tid,
        {
            "node": "compiler",
            "status": "compiling_execution_protocol",
            "event": "compiling_start",
            "label": "Compiling machine-executable protocol…",
        },
    )

    plan = state["plan"]
    query = state["query"]
    
    compiler_prompt = f"""
You are an Execution Architect.

Your job is to convert a human-readable plan into a STRICT, machine-executable JSON protocol.

USER QUERY:
{query}

HUMAN PLAN:
{plan}

---

OUTPUT FORMAT (STRICT JSON ARRAY ONLY):

Each step MUST follow this structure:

{{
  "step": <int>,
  "role": "<exact crew role from the HUMAN PLAN line: Step N [Role]: ...>",
  "task": "<human-readable task description>",
  "tool": "<tool_name OR 'none'>",
  "input": {{ <tool-specific arguments> }},
  "output_key": "<variable_name_to_store_output>",
  "depends_on": ["<previous_output_keys_if_any>"]
}}

---

AVAILABLE TOOLS:

1. extract_data_from_file
   Input: {{ "file_path": "string" }}
   Output: extracted text/data

2. execute_python
   Input: {{ "code": "valid python code as string" }}
   Output: stdout result

3. send_email
   Input: {{ "to": "email", "subject": "string", "body": "string" }}
   Output: confirmation message

4. web_search
   Input: {{ "query": "string" }}
   Output: search results

5. summarize_content
   Input: {{ "text": "string" }}
   Output: summary

6. generate_report
   Input: {{ "content": "string", "title": "string", "format": "markdown" }}
   Output: JSON with paths to generated markdown/PDF files

7. speech_to_text
   Input: {{ "file_path": "absolute path to audio file (WAV, MP3, OGG, FLAC, M4A, etc.)" }}
   Output: JSON with transcribed text and path to saved .txt file

8. data_collector_visualizer
   Input: {{
     "research": "business/data question for automatic web research",
     "url": "optional specific public URL to extract",
     "prompt": "optional extraction guidance for a URL",
     "agentql_query": "optional AgentQL query",
     "columns": "optional comma-separated dataset columns",
     "search_results": 3,
     "max_records": 100,
     "chart": true,
     "chart_engine": "llm_code",
     "task_type": "auto",
     "title": "short chart/report title"
   }}
   Output: JSON with answer_markdown plus JSON/CSV/chart/log artifact paths and /outputs URLs

---

STRICT RULES:

0. ROLE (REQUIRED):
   For each step, set "role" to the sub-agent name shown in brackets on that step in the HUMAN PLAN
   (e.g. "Step 2 [Content Summarizer]: ..." → "role": "Content Summarizer"). This must match the crew roster.

1. TOOL MANDATORY:
   If a tool exists for the task, you MUST use it.

2. NO GUESSING:
   You MUST provide valid inputs for each tool.

3. DATA FLOW:
   If a step depends on previous output, use:
   "depends_on": ["output_key"]

4. VARIABLE USAGE:
   Refer to previous outputs clearly in inputs.

5. NO AMBIGUITY:
   Do NOT write vague tasks like "analyze data"
   Instead specify exact instructions.

6. FINAL STEP:
   If synthesis is required, use tool = "none"

7. OUTPUT:
   Return ONLY valid JSON. No markdown. No explanation.

8. DEPENDENCIES ($ PREFIX):
   When a tool needs data from a previous step, you MUST prefix the output_key with a $.
   Example: If Step 1 output_key is "data", Step 2 input MUST be {{ "text": "$data" }}.

9. VENDOR / COMPANY NAMES:
   For quotation comparisons, RFQs, or PO steps, NEVER use generic placeholders like "Vendor 1/2/3" or "Vendor A/B/C"
   unless the source documents literally use those labels. Use company names and identifiers implied by file names,
   uploaded filenames, or the plan text.

10. extract_data_from_file + execute_python:
   The extract tool returns JSON; for .txt/.md the business content is in the "text_preview" string, not as top-level
   keys like "Total Cost". execute_python must parse that text (regex, line parsing) — do NOT use json.loads on a
   prior step’s entire output as if it were a flat vendor dict with fields like Total Cost or Email.
   Generated Python must use dict.get(...) for all fields and must not assume fixed keys like "compliance" unless set uniformly.
"""

    try:
        if get_llm_provider() == "ollama":
            res = model_completion(
                messages=[{"role": "user", "content": compiler_prompt}],
                max_tokens=2500,
                temperature=0,
            ).choices[0].message.content
        else:
            provider_llm = _get_crewai_llm()
            res = provider_llm.call([{"role": "user", "content": compiler_prompt}])
        
        # Strip markdown fences if present
        clean_res = res.replace("```json", "").replace("```", "").strip()
        structured_plan = json.loads(clean_res)
        
        logger.info(f"Compiled Plan: {json.dumps(structured_plan, indent=2)}")

        if _tid:
            TraceManager.emit(
                _tid,
                {
                    "event": "compiling_complete",
                    "steps": len(structured_plan),
                    "label": f"Protocol compiled ({len(structured_plan)} steps)",
                },
            )

        return {
            "structured_plan": structured_plan
        }
    except Exception as e:
        logger.error(f"Plan compilation failed: {e}")
        # Fallback: Create a simple one-step structured plan from the query
        fallback_plan = [{
            "step": 1,
            "task": f"Execute the following plan: {plan}",
            "tool": "none",
            "expected_output": "Final answer"
        }]
        if _tid:
            TraceManager.emit(
                _tid,
                {
                    "event": "compiling_complete",
                    "steps": len(fallback_plan),
                    "fallback": True,
                    "label": "Compiler fallback — single-step execution",
                },
            )
        return {"structured_plan": fallback_plan}
