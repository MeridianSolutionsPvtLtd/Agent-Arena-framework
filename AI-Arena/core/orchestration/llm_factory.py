import os
import logging
from typing import Any, Optional
from langchain_ollama import ChatOllama
from core.orchestration.azure_settings import get_llm_provider as get_configured_llm_provider

logger = logging.getLogger(__name__)

class LLMFactory:
    """Centralized factory for the local Ollama provider."""

    @staticmethod
    def get_llm(structured_class: Optional[Any] = None) -> Any:
        """
        Returns a LangChain LLM instance based on LLM_PROVIDER in .env.
        Args:
            structured_class: If provided, returns an LLM with_structured_output(structured_class).
        """
        provider = get_configured_llm_provider()

        if provider == "ollama":
            model_name = os.getenv("OLLAMA_MODEL", "llama3.1")
            base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
            
            logger.info(f"Initializing Local Ollama LLM with model: {model_name}")
            llm = ChatOllama(
                model=model_name,
                base_url=base_url,
                temperature=0.3,
                format="json" if structured_class else "",
                num_predict=4096,
                # Force every possible timeout level to 10 minutes (600s)
                timeout=600,
                request_timeout=600.0,
                client_kwargs={
                    "timeout": 600.0
                }
            )
            
            if structured_class:
                # ChatOllama supports .with_structured_output() in recent versions
                # It uses JSON mode under the hood.
                return llm.with_structured_output(structured_class)
            return llm

        else:
            raise ValueError(f"Unsupported LLM_PROVIDER: {provider}; only ollama is supported.")

# Global singleton or helper access
def get_llm_provider(structured_class: Optional[Any] = None):
    return LLMFactory.get_llm(structured_class)
