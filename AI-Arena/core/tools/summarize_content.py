from crewai.tools import BaseTool
from typing import Type
import logging
from core.orchestration.azure_settings import model_completion

logger = logging.getLogger(__name__)

from pydantic import BaseModel, Field


class SummarizationError(RuntimeError):
    """Controlled failure returned to the governed execution pipeline."""

    def __init__(self, message: str, *, code: str, retryable: bool):
        super().__init__(message)
        self.code = code
        self.retryable = retryable

class SummarizeInput(BaseModel):
    text: str = Field(..., description="The raw text content that needs to be summarized. Should be substantial content, not just a few words.")

class SummarizeTool(BaseTool):
    name: str = "summarize_content"
    description: str = """
    Summarizes long content or text into a concise, high-quality summary.
    
    USE THIS TOOL WHEN:
    - You have a large block of text (from a file, web search, or email) that is too long to present directly.
    - The user asks for a 'summary', 'tldr', or 'briefing' of specific content.
    
    INPUT:
    - text: The full string to be condensed.
    
    OUTPUT:
    - A comprehensive summary highlighting the most critical key points.
    
    DO NOT:
    - Use this for short text (under 2-3 paragraphs).
    - Use this if you only need to extract a single specific fact.
    
    Example:
    {"text": "The quick brown fox jumps over the lazy dog... [10 pages of text]"}
    """
    args_schema: Type[BaseModel] = SummarizeInput

    def _run(self, text: str) -> str:
        """Internal execution logic."""
        if not text or not text.strip():
            return "No text provided to summarize."
            
        # Safety truncation to prevent context limit issues
        if len(text) > 8000:
            text = text[:8000] + "... [Text truncated for summarization tool limit]"
    
        try:
            # Extract USER QUESTION if it was prepended by the pipeline
            user_question = ""
            content_to_summarize = text
            if text.startswith("USER QUESTION:"):
                parts = text.split("\n\nFULL CONTENT:\n", 1)
                if len(parts) == 2:
                    user_question = parts[0].replace("USER QUESTION:", "").strip()
                    content_to_summarize = parts[1]

            if user_question:
                prompt = (
                    "You are a precise evidence summarizer.\n\n"
                    f"USER REQUEST (context only): {user_question}\n\n"
                    f"SOURCE CONTENT TO SUMMARIZE:\n{content_to_summarize}\n\n"
                    "TASK: Summarize the supplied source content faithfully.\n\n"
                    "GUIDELINES:\n"
                    "1. Use only facts present in the supplied source content.\n"
                    "2. Extract important names, dates, numbers, claims, and conclusions.\n"
                    "3. Clearly distinguish source facts from uncertainty or missing information.\n"
                    "4. Do not perform a new search or recommend a different search.\n"
                    "5. Do not judge whether the search was relevant; summarize what was retrieved.\n"
                    "6. Use clear headings and bullets when they improve readability.\n"
                )
            else:
                prompt = f"Summarize the following content, highlighting the key points:\n\n{text}"

            res = model_completion(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                # Local models become disproportionately slow with a large
                # completion budget. Summaries should be concise and factual.
                max_tokens=800,
            )

            return res.choices[0].message.content.strip()
        except RuntimeError as e:
            message = str(e).lower()
            if "timed out" in message or "timeout" in message:
                logger.error("Summarization timed out: %s", e)
                raise SummarizationError(
                    "Local model request timed out during summarization",
                    code="local_model_timeout",
                    retryable=True,
                ) from None
            logger.error("Summarization model failure: %s", e)
            raise SummarizationError(
                "Summarization could not be completed by the local model",
                code="summarization_failed",
                retryable=False,
            ) from e
        except Exception as e:
            logger.error("Unexpected summarization failure: %s", e)
            raise SummarizationError(
                "Summarization could not be completed",
                code="summarization_failed",
                retryable=False,
            ) from e
