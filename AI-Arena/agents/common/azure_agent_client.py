import os
import logging
from typing import Any, Optional
from azure.ai.agents import AgentsClient
from azure.identity import DefaultAzureCredential
from azure.ai.agents.models import ListSortOrder
from dotenv import load_dotenv

# Ensure environment variables are loaded if this is called independently
load_dotenv()

logger = logging.getLogger(__name__)

class AzureAgentClient:
    """Shared client for Azure AI Foundry Agents."""

    def __init__(self, agent_id: str, endpoint: Optional[str] = None) -> None:
        # Registry agents may select a validated project endpoint. Existing
        # code-owned agents retain the environment-backed default.
        self.endpoint = endpoint or os.getenv("AZURE_AI_ENDPOINT")
        self.agent_id = agent_id

        if not self.endpoint:
            logger.error("AZURE_AI_ENDPOINT not found in environment variables")
            raise ValueError("AZURE_AI_ENDPOINT not found in environment variables")
        if not self.agent_id:
            logger.error("agent_id not provided to AzureAgentClient")
            raise ValueError("agent_id not provided")

        logger.info("Connecting to Azure AI Agents endpoint: %s", self.endpoint)
        self._client = AgentsClient(
            endpoint=self.endpoint,
            credential=DefaultAzureCredential(),
        )
        # Validate the agent exists at startup
        try:
            agent = self._client.get_agent(self.agent_id)
            self.agent_name = str(getattr(agent, "name", "") or self.agent_id)
            logger.info("Agent loaded: %s (%s)", agent.name, agent.id)
        except Exception as e:
            logger.error("Failed to load agent %s: %s", self.agent_id, str(e))
            raise

    def run_analysis(self, prompt: str, thread_id: Optional[str] = None) -> dict[str, Any]:
        """
        Create a new thread (or reuse an existing one), post the prompt,
        run the agent, and return the assistant's response.
        """
        if thread_id:
            try:
                thread_obj = self._client.threads.get(thread_id)
                logger.info("Reusing thread: %s", thread_obj.id)
            except Exception:
                logger.warning("Thread %s not found, creating new one", thread_id)
                thread_obj = self._client.threads.create()
        else:
            thread_obj = self._client.threads.create()
            logger.info("Created thread: %s", thread_obj.id)

        self._client.messages.create(
            thread_id=thread_obj.id,
            role="user",
            content=prompt,
        )

        run = self._client.runs.create_and_process(
            thread_id=thread_obj.id,
            agent_id=self.agent_id,
        )
        logger.info("Run %s finished with status: %s", run.id, run.status)

        # Extract usage if available
        usage = {}
        if hasattr(run, "usage") and run.usage:
            usage = {
                "prompt_tokens": getattr(run.usage, "prompt_tokens", 0),
                "completion_tokens": getattr(run.usage, "completion_tokens", 0),
                "total_tokens": getattr(run.usage, "total_tokens", 0),
            }

        if run.status == "failed":
            error_msg = getattr(run, "last_error", "Unknown agent error")
            logger.error("Agent run failed: %s", error_msg)
            return {
                "thread_id": thread_obj.id,
                "response": f"Agent run failed: {error_msg}",
                "status": "failed",
                "usage": usage
            }

        response_text = self._extract_last_assistant_message(thread_obj.id)

        return {
            "thread_id": thread_obj.id,
            "response": response_text,
            "status": "completed",
            "usage": usage
        }

    def get_thread_messages(self, thread_id: str) -> list[dict[str, Any]]:
        """Return all messages from an existing thread (ascending order)."""
        messages = self._client.messages.list(
            thread_id=thread_id,
            order=ListSortOrder.ASCENDING,
        )
        result = []
        for msg in messages:
            content = ""
            if msg.text_messages:
                content = msg.text_messages[-1].text.value
            elif hasattr(msg, "content") and msg.content:
                # Fallback for different SDK versions or content types
                content = msg.content[0].text.value if hasattr(msg.content[0], "text") else str(msg.content[0])
            
            result.append({"role": msg.role, "content": content})
        return result

    def _extract_last_assistant_message(self, thread_id: str) -> str:
        """Walk the thread (ascending) and return the last assistant text."""
        messages = self._client.messages.list(
            thread_id=thread_id,
            order=ListSortOrder.ASCENDING,
        )

        last_response = ""
        for msg in messages:
            if msg.role == "assistant":
                if msg.text_messages:
                    last_response = msg.text_messages[-1].text.value
                elif hasattr(msg, "content") and msg.content:
                    last_response = msg.content[0].text.value if hasattr(msg.content[0], "text") else str(msg.content[0])

        return last_response or "No response generated."
