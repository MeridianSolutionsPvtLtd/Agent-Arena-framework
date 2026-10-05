import asyncio
import logging
from typing import Dict, Any
from langgraph.graph import StateGraph, END

from core.orchestration.state import AgentState
from core.orchestration.trace import TraceManager

logger = logging.getLogger(__name__)


class AgentExecutor:
    """
    The LangGraph Orchestrator that manages the execution of a CrewAI workforce.
    This class is a lightweight orchestrator that delegates logic to modular nodes.
    """

    @staticmethod
    def build_executor():
        """Constructs the LangGraph state machine mapping to the Meridian Architecture."""
        workflow = StateGraph(AgentState)

        # ✅ Correct imports (single source of truth)
        from core.orchestration.executor_nodes.shield import shield_node
        from core.orchestration.executor_nodes.planner import planner_node
        from core.orchestration.executor_nodes.compiler import compiler_node
        from core.orchestration.executor_nodes.execution import execution_node
        from core.orchestration.executor_nodes.validator import validation_node
        from core.orchestration.executor_nodes.safety import safety_node

        # 1. Add Nodes
        workflow.add_node("shield", shield_node)
        workflow.add_node("planner", planner_node)
        workflow.add_node("compiler", compiler_node)
        workflow.add_node("execute", execution_node)
        workflow.add_node("validator", validation_node)
        workflow.add_node("safety", safety_node)

        # 2. Entry Point
        workflow.set_entry_point("shield")

        # 3. Routing Logic

        def check_shield(state: AgentState):
            if not state.get("is_safe"):
                return END

            if state.get("error") == "HITL_REQUIRED":
                return END

            # Conversation-mode requests are already answered by the planner;
            # do not send them through compiler, broker, or tool execution.
            if state.get("direct_response"):
                return END

            if not state.get("is_approved"):
                return "planner"

            # ✅ Prevent compiler from running with empty plan
            if not state.get("plan"):
                logger.warning("Approved but no plan found. Redirecting to planner.")
                return "planner"

            return "compiler"

        def check_planner(state: AgentState):
            if state.get("error") == "HITL_REQUIRED":
                return END
            if state.get("direct_response"):
                return END
            return "compiler"

        def check_execution(state: AgentState):
            """Do not let approval/rejection/failure become a successful answer."""

            if state.get("error") in {
                "HITL_REQUIRED",
                "TOOL_EXECUTION_FAILED",
                "TOOL_EXECUTION_REJECTED",
            }:
                return END
            return "validator"

        def check_validator(state: AgentState):
            # ✅ Loop guard
            if int(state.get("loop_guard_count", 0)) >= 2:
                return "safety"

            # ✅ Controlled retry
            if state.get("error") == "RETRY_REQUIRED":
                if int(state.get("retry_count", 0)) >= 1:
                    return "safety"
                return "execute"

            return "safety"

        def check_safety(state: AgentState):
            if int(state.get("loop_guard_count", 0)) >= 2:
                return END

            if state.get("error") == "RETRY_REQUIRED":
                if int(state.get("retry_count", 0)) >= 1:
                    return END
                return "execute"

            return END

        # 4. Graph Edges
        workflow.add_conditional_edges("shield", check_shield)
        workflow.add_conditional_edges("planner", check_planner)
        workflow.add_edge("compiler", "execute")
        workflow.add_conditional_edges("execute", check_execution)
        workflow.add_conditional_edges("validator", check_validator)
        workflow.add_conditional_edges("safety", check_safety)

        return workflow.compile()

    @classmethod
    def run(
        cls,
        blueprint: Dict[str, Any],
        query: str,
        conversation_history: str = "",
        trace_id: str = None,
        pii_map: Dict[str, str] = None,
        target_email_hint: str = "",
        file_paths: list = None,
        pre_approved_plan: list = None,
        blackboard: dict = None,
        user_id: str = "",
        tenant_id: str = "",
        agent_id: str = "",
        thread_id: str = "",
        file_ids: list = None,
        attachments: list = None,
        attachment_context: str = "",
        context_policy: dict = None,
    ) -> Dict[str, Any]:
        """Compatibility entry point for non-async callers.

        Production FastAPI execution uses ``run_async`` so the graph, broker,
        MongoDB driver, and MCP clients stay on the application event loop.
        """

        return asyncio.run(
            cls.run_async(
                blueprint=blueprint,
                query=query,
                conversation_history=conversation_history,
                trace_id=trace_id,
                pii_map=pii_map,
                target_email_hint=target_email_hint,
                file_paths=file_paths,
                pre_approved_plan=pre_approved_plan,
                blackboard=blackboard,
                user_id=user_id,
                tenant_id=tenant_id,
                agent_id=agent_id,
                thread_id=thread_id,
                file_ids=file_ids,
                attachments=attachments,
                attachment_context=attachment_context,
                context_policy=context_policy,
            )
        )

    @classmethod
    async def run_async(
        cls,
        blueprint: Dict[str, Any],
        query: str,
        conversation_history: str = "",
        trace_id: str = None,
        pii_map: Dict[str, str] = None,
        target_email_hint: str = "",
        file_paths: list = None,
        pre_approved_plan: list = None,
        blackboard: dict = None,
        user_id: str = "",
        tenant_id: str = "",
        agent_id: str = "",
        thread_id: str = "",
        file_ids: list = None,
        agent_run_id: str = "",
        attachments: list = None,
        attachment_context: str = "",
        context_policy: dict = None,
    ) -> Dict[str, Any]:
        """Run LangGraph without crossing the application's async loop boundary."""

        # ✅ Trace start
        TraceManager.emit(trace_id, {"node": "executor", "status": "started"})

        app = cls.build_executor()

        # ── Load Fine-Tuning DNA from Blueprint ──
        agent_config = {
            "sub_agents": blueprint.get("crew_roles", []),
            "executor_policy": blueprint.get("executor_policy", {}),
            "validator_config": blueprint.get("validator_config", {}),
        }

        initial_state = {
            "blueprint": blueprint,
            "query": query,
            "conversation_history": conversation_history,
            "is_safe": True,
            "crew_output": "",
            "is_factual": True,
            "final_response": "",
            "error": "",
            "trace_id": trace_id,
            "retry_count": 0,
            "loop_guard_count": 0,
            "pii_map": pii_map or {},
            "target_email": target_email_hint or "",
            "target_email_token": "",
            "target_email_validated": False,
            "wants_email_action": False,
            "email_followup_only": False,
            "is_approved": bool(pre_approved_plan),
            "plan": "Approved continuation" if pre_approved_plan else "",
            "structured_plan": pre_approved_plan or [],
            "intent": {},
            "validation_feedback": "",
            "file_paths": file_paths or [],
            "file_ids": file_ids or [],
            "attachments": attachments or [],
            "attachment_context": attachment_context or "",
            "context_policy": context_policy or {},
            "user_id": user_id,
            "tenant_id": tenant_id or user_id,
            "agent_id": agent_id,
            "thread_id": thread_id,
            "agent_run_id": agent_run_id or "",
            "tool_execution_id": "",
            "executed_steps": [],
            # ── NEW: Stateful Blackboard & Fine-Tuning DNA ──
            "blackboard": blackboard or {},
            "agent_config": agent_config,
            "step_outputs": [],
            "sub_agent_histories": {},
        }

        from core.security.guardrails import GuardrailEngine
        token = GuardrailEngine.set_runtime_pii_map(pii_map)

        try:
            result = await app.ainvoke(initial_state)
        finally:
            GuardrailEngine.reset_runtime_pii_map(token)

        # ✅ Ensure trace_id never gets lost
        result["trace_id"] = result.get("trace_id") or trace_id

        if result.get("error") and result.get("error") != "HITL_REQUIRED":
            feedback = result.get("validation_feedback") or result["error"]
            error_code = result.get("error_code", "tool_execution_failed")
            return {
                "status": "error",
                "message": feedback,
                "error_code": error_code,
                "error_retryable": bool(result.get("error_retryable", False)),
                "error_trace_id": result.get("error_trace_id"),
                "trace_id": result.get("trace_id"),
            }

        out = {
            "status": "success",
            "message": result.get("final_response", "No response generated."),
            "trace_id": result.get("trace_id"),
            "pii_map": result.get("pii_map", {}),
            "blackboard": result.get("blackboard", {}),
            "sub_agent_histories": result.get("sub_agent_histories", {}),
            "agent_sequence": result.get("agent_sequence", []),
            "step_outputs": result.get("step_outputs", []),
        }
        if result.get("error") == "HITL_REQUIRED":
            # HITL has three distinct meanings:
            #   plan  - user reviews the proposed flight plan; no tool record exists.
            #   tool  - Execution Broker created a resumable tex_* record.
            #   input - execution cannot proceed until the user supplies missing data.
            # Keep the generic graph signal internal and expose an explicit type so
            # clients never attempt /tool-executions/{id}/approval for a plan pause.
            out["hitl_pending"] = True
            pending_execution_id = result.get("tool_execution_id") or (
                result.get("blackboard") or {}
            ).get("pending_tool_execution_id")
            if pending_execution_id:
                out["approval_type"] = "tool"
                out["message"] = result.get("validation_feedback") or "Tool approval is required"
                out["tool_execution_id"] = pending_execution_id
            elif result.get("structured_plan"):
                out["approval_type"] = "plan"
                out["message"] = result.get("final_response") or "Plan approval is required"
            else:
                out["approval_type"] = "input"
                out["message"] = (
                    result.get("final_response")
                    or result.get("validation_feedback")
                    or "Additional information is required"
                )
            sp = result.get("structured_plan")
            if isinstance(sp, list) and len(sp) > 0:
                out["structured_plan"] = sp
        return out
