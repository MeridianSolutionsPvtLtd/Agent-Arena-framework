import uuid
import logging
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field
from langchain_core.prompts import PromptTemplate
from .registry import registry
from .llm_factory import get_llm_provider
from langchain_core.messages import HumanMessage

logger = logging.getLogger(__name__)

class CrewRole(BaseModel):
    role: str = Field(description="The professional role of the agent (e.g., 'Medical Analyst')")
    goal: str = Field(description="The primary objective of this specific agent")
    backstory: str = Field(description="The persona backstory to guide its tone and knowledge")
    assigned_tools: List[str] = Field(description="List of tool selection keys from the available list that ONLY THIS agent should have access to based on their role.")
    communication_protocol: Optional[str] = Field(None, description="A custom protocol/template for this role's emails (e.g. 'Use a formal RFP structure...'). Only generate if role has 'send_email'.")

class ValidatorConfig(BaseModel):
    checklist: List[str] = Field(default_factory=list, description="A list of 3-5 specific audit checks for this agent (e.g., 'Ensure PO number is present').")
    min_score: float = 0.5

class AgentBlueprint(BaseModel):
    name: str = Field(description="A catchy, human-readable name for the overall agent.")
    domain: str = Field(description="The industry domain (e.g., healthcare, finance, education).")
    tools: List[str] = Field(description="List of tool selection keys required by the agent. Must be selected from available tools.")
    crew_roles: List[CrewRole] = Field(description="List of multi-agent roles to execute complex sub-tasks.")
    system_prompt: str = Field(description="The overarching instruction set for the orchestrator.")
    validator_config: Optional[ValidatorConfig] = Field(None, description="The audit checklist for this agent.")
    user_intent: Optional[str] = Field(None, description="The original user query that created this agent.")

class AgentBuilder:
    """The Meta-Agent that generates a deterministic JSON blueprint for user agents."""

    @staticmethod
    def _sanitize_query_for_planning(user_query: str) -> str:
        """Reduce provider false positives while preserving intent for planning."""
        q = (user_query or "").strip()
        # Replace direct email strings with a placeholder for planning stage only.
        q = __import__("re").sub(
            r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b",
            "<email_address>",
            q,
        )
        return q

    @staticmethod
    def _build_primary_prompt() -> PromptTemplate:
        return PromptTemplate.from_template(
            "You are an Elite Agentic Architect. Your mission is to translate high-level user intent into a high-fidelity multi-agent 'Workforce DNA'.\n\n"
            "CONTEXTUAL ANALYSIS:\n"
            "Analyze the CONVERSATION HISTORY and USER REQUEST to identify not just the primary goal, but the hidden requirements (e.g., tone, formatting, security, specific data dependencies).\n\n"
            "CONVERSATION HISTORY:\n{history}\n\n"
            "USER REQUEST:\n{query}\n\n"
            "AVAILABLE TOOLS:\n{tools}\n\n"
            "ARCHITECTURAL PRINCIPLES:\n"
            "1. WORKFORCE DESIGN: Design a sophisticated multi-agent hierarchy using 'crew_roles'. Assign highly professional, specialized personas to each role.\n"
            "2. TOOL ASSIGNMENT: Select and assign only exact short selection keys (for example tool_001) from AVAILABLE TOOLS. Never output the display name, invent a key, or assume a tool that is not listed.\n"
            "3. MISSION CONTROL: Write a comprehensive 'system_prompt' that establishes the tone, 'Mission of Truth' rules, and operational bounds.\n"
            "4. COMMUNICATION PROTOCOLS: For any role that has the 'send_email' tool, you MUST generate a high-quality 'communication_protocol' (tone, structure, and required fields) for that specific persona.\n"
            "5. EXPERT VALIDATION: Generate a 3-5 item 'validator_config.checklist' to ensure the agent's output is compliant with domain standards (e.g. PO formatting, data privacy).\n"
            "6. CONSTRAINTS: Preserve every explicit constraint mentioned (e.g., 'use table format', 'keep under 200 words').\n"
        )

    @staticmethod
    def _build_fallback_prompt() -> PromptTemplate:
        return PromptTemplate.from_template(
            "Return a valid agent blueprint JSON.\n"
            "Request: {query}\n"
            "Tools: {tools}\n"
            "Requirements:\n"
            "- Select only exact short selection keys listed in Tools; never output display names or invent keys.\n"
            "- Include crew_roles with assigned_tools and communication_protocol for emailers.\n"
            "- Include validator_config with a 3-item checklist."
        )

    @staticmethod
    def _apply_tool_allowlist(
        blueprint: Dict[str, Any], available_tools: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Make an LLM blueprint internally consistent with the catalog.

        The model may emit a friendly alias or a tool remembered from an older
        prompt. Only exact current catalog IDs may cross the Builder boundary.
        Crew-role assignments are constrained to the same selected set, and
        version references are derived exclusively from trusted catalog data.
        """

        available_by_id = {item["id"]: item for item in available_tools}
        available_by_key = {
            item["selection_key"]: item
            for item in available_tools
            if item.get("selection_key")
        }
        name_counts: dict[str, int] = {}
        for item in available_tools:
            name_key = str(item.get("name") or "").strip().casefold()
            if name_key:
                name_counts[name_key] = name_counts.get(name_key, 0) + 1
        available_by_unique_name = {
            str(item.get("name") or "").strip().casefold(): item
            for item in available_tools
            if str(item.get("name") or "").strip()
            and name_counts[str(item.get("name") or "").strip().casefold()] == 1
        }

        def resolve(raw_value: Any) -> str | None:
            if not isinstance(raw_value, str):
                return None
            value = raw_value.strip()
            item = (
                available_by_key.get(value)
                or available_by_id.get(value)
                or available_by_unique_name.get(value.casefold())
            )
            return item["id"] if item else None

        selected: list[str] = []
        seen: set[str] = set()
        for raw_tool_id in blueprint.get("tools") or []:
            tool_id = resolve(raw_tool_id)
            if tool_id and tool_id not in seen:
                seen.add(tool_id)
                selected.append(tool_id)

        selected_set = set(selected)
        for role in blueprint.get("crew_roles") or []:
            if not isinstance(role, dict):
                continue
            assigned: list[str] = []
            for raw_tool_id in role.get("assigned_tools") or []:
                tool_id = resolve(raw_tool_id)
                if tool_id and tool_id in selected_set and tool_id not in assigned:
                    assigned.append(tool_id)
            role["assigned_tools"] = assigned

        blueprint["tools"] = selected
        blueprint["tool_refs"] = [
            {
                "tool_id": tool_id,
                "version": available_by_id[tool_id]["version"],
            }
            for tool_id in selected
            if available_by_id[tool_id].get("version")
        ]
        return blueprint

    @staticmethod
    def _rephrase_user_instructions(raw_query: str) -> str:
        """
        Analyze the user's raw agent-creation prompt and rephrase it into a
        clear, concise instruction — without adding extra information.
        Returns the rephrased text, or the original if rephrasing fails.
        """
        if not raw_query or len(raw_query.strip()) < 10:
            return raw_query

        try:
            llm = get_llm_provider()  # plain LLM, no structured output
            rephrase_prompt = (
                "You are a Prompt Clarity Engine.\n\n"
                "TASK:\n"
                "Analyze the user's raw input below and rephrase it into a clear, "
                "simple, and actionable agent instruction.\n\n"
                "STRICT RULES:\n"
                "1. DO NOT add any new information, features, or capabilities that "
                "the user did not explicitly mention.\n"
                "2. DO NOT expand the scope — keep it focused on what the user asked.\n"
                "3. Remove filler words, typos, and redundancy.\n"
                "4. Preserve every specific detail the user mentioned (product names, "
                "quantities, prices, email addresses, vendor names, file references).\n"
                "5. Output ONLY the rephrased instruction — no explanation, no "
                "preamble, no markdown formatting.\n"
                "6. Keep it to 1-3 sentences maximum.\n\n"
                f"USER'S RAW INPUT:\n{raw_query}\n\n"
                "REPHRASED INSTRUCTION:"
            )
            
            result = llm.invoke([HumanMessage(content=rephrase_prompt)])
            rephrased = (result.content if hasattr(result, "content") else str(result)).strip()

            if rephrased and len(rephrased) > 5:
                logger.info(f"Rephrased user instructions: '{raw_query[:80]}…' → '{rephrased[:80]}…'")
                return rephrased
        except Exception as e:
            logger.warning(f"Instruction rephrasing failed, using original: {e}")

        return raw_query

    @staticmethod
    def build(
        user_query: str,
        user_id: str,
        custom_name: Optional[str] = None,
        conversation_history: str = "",
        catalog_tools: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Translates user intent into a structured Agent Blueprint."""

        if catalog_tools is not None:
            available_tools = [
                {
                    "selection_key": f"tool_{index:03d}",
                    "id": item["capability_id"],
                    "version": item["version"],
                    "name": item.get("name") or item["capability_id"],
                    "description": item.get("description", ""),
                }
                for index, item in enumerate(catalog_tools, start=1)
            ]
        else:
            available_tools = [
                {
                    "selection_key": f"tool_{index:03d}",
                    "id": item.id,
                    "version": None,
                    "name": item.id,
                    "description": item.description,
                }
                for index, item in enumerate(registry.get_all_metadata(), start=1)
            ]
        tools_str = "\n".join(
            f"- {item['selection_key']} | {item['name']}: {item['description']}"
            for item in available_tools
        )

        structured_llm = get_llm_provider(structured_class=AgentBlueprint)

        # Step 0: Rephrase raw user input into a clear, concise instruction
        rephrased_query = AgentBuilder._rephrase_user_instructions(user_query)
        sanitized_query = AgentBuilder._sanitize_query_for_planning(rephrased_query)

        try:
            chain = AgentBuilder._build_primary_prompt() | structured_llm
            result: AgentBlueprint = chain.invoke({"query": sanitized_query, "tools": tools_str, "history": conversation_history})
        except Exception as primary_err:
            logger.warning(f"Primary builder prompt failed, retrying fallback: {primary_err}")
            fallback_chain = AgentBuilder._build_fallback_prompt() | structured_llm
            result = fallback_chain.invoke({"query": sanitized_query, "tools": tools_str, "history": conversation_history})

        if hasattr(result, "model_dump"):
            blueprint = result.model_dump()
        else:
            blueprint = result

        blueprint["agent_id"] = f"agent_{uuid.uuid4().hex[:8]}"
        blueprint["user_id"] = user_id
        blueprint["user_intent"] = user_query
        blueprint = AgentBuilder._apply_tool_allowlist(blueprint, available_tools)

        if custom_name:
            blueprint["name"] = custom_name

        if "executor_policy" not in blueprint:
            blueprint["executor_policy"] = {
                "email_strategy": "auto",
                "allow_hallucinations": False,
                "strict_spec_compliance": True,
                "final_report_style": "professional_markdown",
                "max_steps": 8,
            }

        if not blueprint.get("validator_config"):
            blueprint["validator_config"] = {
                "checklist": ["Ensure response is professional", "Verify data accuracy"],
                "min_score": 0.5,
            }

        logger.info(f"Successfully generated blueprint for '{blueprint['name']}'")
        return blueprint
