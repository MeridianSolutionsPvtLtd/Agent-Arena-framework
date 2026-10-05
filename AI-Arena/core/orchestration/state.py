from typing import TypedDict, List, Dict, Any, Set, Optional

class AgentState(TypedDict, total=False):
    blueprint: Dict[str, Any]
    query: str
    conversation_history: str
    is_safe: bool
    crew_output: str
    is_factual: bool
    final_response: str
    direct_response: bool
    error: str
    trace_id: str
    retry_count: int
    loop_guard_count: int
    target_email: str
    target_email_token: str
    target_email_validated: bool
    pii_map: Dict[str, str]
    wants_email_action: bool
    email_followup_only: bool
    is_approved: bool
    plan: str
    structured_plan: List[Dict[str, Any]]
    intent: Dict[str, Any]
    validation_feedback: str
    file_paths: List[str]  # Absolute paths to any attached files for this request
    file_ids: List[str]
    attachments: List[Dict[str, Any]]
    attachment_context: str
    context_policy: Dict[str, Any]
    user_id: str
    tenant_id: str
    agent_id: str
    thread_id: str
    agent_run_id: str
    # First-class HITL continuation handle. Do not rely only on nested
    # blackboard state because clients need this exact value to approve/resume.
    tool_execution_id: str
    executed_steps: List[str]  # Tracking executed steps for exactly-once logic
    seen_queries: List[str]  # Anti-loop cache for search queries

    # ────────────────────────────────────────────────────────────
    # NEW: Stateful Blackboard & Fine-Tuning DNA
    # ────────────────────────────────────────────────────────────

    # The Blackboard is a structured fact store that holds raw extraction
    # data, vendor lists, emails, specs, etc.  Every sub-agent reads from
    # and writes to this dictionary so that NO data is lost between steps.
    blackboard: Dict[str, Any]

    # The Agent Config is the "DNA" loaded from the DB at runtime.
    # It contains:
    #   sub_agents:       List of {role, backstory, goal} for each crew role
    #   executor_policy:  Dict with keys like email_strategy, allow_hallucinations, etc.
    #   validator_config: Dict with a checklist list and min_score
    agent_config: Dict[str, Any]

    # Full unfiltered step outputs, stored in state so the validator
    # and synthesizer can access every step's raw result.
    step_outputs: List[Dict[str, Any]]

    # ────────────────────────────────────────────────────────────
    # MULTI-AGENT CHAT ISOLATION
    # ────────────────────────────────────────────────────────────
    
    # sub_agent_histories is a mapping of agent roles to their message history.
    # Format: {"RFP Specialist": [{"sender": "Agent", "text": "..."}, ...], ...}
    sub_agent_histories: Dict[str, List[Dict[str, Any]]]
