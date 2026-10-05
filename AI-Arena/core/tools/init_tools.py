from .extract_data_from_file import FileExtractorTool
from .send_email import EmailTool
from .python_executor import PythonExecutorTool
from .summarize_content import SummarizeTool
from .web_search import web_search
from .mail_tracker import mailbox_tracker_graph
from .generate_report import ReportGeneratorTool
from .speech_to_text import SpeechToTextTool
from .deep_research_visualizer import DataCollectorVisualizerTool
from ..orchestration.registry import registry
import logging
from config import settings

logger = logging.getLogger(__name__)

def register_default_tools():
    """Registers default tools into the central ToolRegistry."""
    # Capability metadata used by orchestration for generic intent/capability guards.
    registry.register(
        FileExtractorTool(),
        metadata={
            "intent_keywords": ["extract", "read file", "parse file", "analyze file", "pdf", "csv", "xlsx", "xls", "txt", "document"],
            "success_markers": ["file extracted", "parsed file", "data extracted from file"],
        },
    )
    registry.register(
        ReportGeneratorTool(),
        metadata={
            "intent_keywords": ["report", "generate report", "write report", "create document", "professional report", "pdf export"],
            "success_markers": ["report generated", "report saved", "pdf created"],
        },
    )
    registry.register(
        EmailTool(),
        metadata={
            "intent_keywords": ["email", "mail", "send to", "forward", "dispatch", "send it"],
            "success_markers": ["email sent", "mail sent", "dispatched via email", "sent successfully"],
        },
    )
    if settings.ENABLE_UNSAFE_PYTHON_TOOL:
        registry.register(
            PythonExecutorTool(),
            metadata={
                "intent_keywords": ["calculate", "compute", "run python", "execute code", "script", "determinant", "fibonacci", "statistics"],
                "success_markers": ["code executed", "python execution completed", "script output"],
            },
        )
    registry.register(
        SummarizeTool(),
        metadata={
            "intent_keywords": ["summarize", "summary", "brief", "condense", "tldr"],
            "success_markers": ["summary generated", "content summarized"],
        },
    )
    registry.register(
        web_search,
        metadata={
            "intent_keywords": ["search", "look up", "find online", "web", "internet", "latest", "current"],
            "success_markers": ["web results found", "scraped", "search completed"],
        },
    )
    registry.register(
        mailbox_tracker_graph,
        metadata={
            "intent_keywords": [
                "mail tracker",
                "mailbox",
                "inbox",
                "new mails",
                "unread emails",
                "track email",
                "mark read",
                "graph mail",
            ],
            "success_markers": [
                "marked_read",
                "total_found",
                "tracked_at",
                "emails",
            ],
        },
    )
    registry.register(
        SpeechToTextTool(),
        metadata={
            "intent_keywords": ["speech to text", "transcribe", "audio", "voice", "recording", "speech", "dictation", "spoken", "listen"],
            "success_markers": ["transcription saved", "speech recognized", "text extracted from audio"],
        },
    )
    if settings.ENABLE_ADVANCED_WEB_TOOL:
        registry.register(
            DataCollectorVisualizerTool(),
            metadata={
                "intent_keywords": [
                    "data collector", "data visualizer", "collect data", "fetch data",
                    "price history", "time series", "visualize", "chart", "trend",
                    "ranking", "compare sources", "dataset", "csv", "agentql",
                ],
                "success_markers": [
                    "answer_preview", "artifacts", "csv", "chart", "auto_research",
                    "url_collection",
                ],
            },
        )
    logger.info(
        "Default tools registered: extract_data_from_file, generate_report, send_email, "
        "summarize_content, web_search, mailbox_tracker_graph, speech_to_text, data_collector_visualizer"
    )
