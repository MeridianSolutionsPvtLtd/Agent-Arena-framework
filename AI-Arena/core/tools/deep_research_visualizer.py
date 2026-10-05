import argparse
import importlib.util
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional, Type

from crewai.tools import BaseTool
from dotenv import load_dotenv
from pydantic import BaseModel, Field


BACKEND_DIR = Path(__file__).resolve().parents[2]
load_dotenv(BACKEND_DIR / ".env")

OUTPUTS_DIR = BACKEND_DIR / "outputs"
DEFAULT_OUTPUT_DIR = OUTPUTS_DIR / "data_collector_visualizer"
DEFAULT_PIPELINE_PATH = Path(__file__).resolve().parent / "data_collector_visualizer.py"


class DataCollectorVisualizerInput(BaseModel):
    research: str = Field(
        default="",
        description="Research question for automatic web search, structured data collection, answer synthesis, and chart generation.",
    )
    url: str = Field(
        default="",
        description="Specific public URL to extract structured data from. If provided, also provide prompt or agentql_query.",
    )
    prompt: str = Field(
        default="",
        description="Natural language extraction prompt for a specific URL, or additional extraction guidance for research mode.",
    )
    agentql_query: str = Field(
        default="",
        description="Optional AgentQL query for URL extraction mode.",
    )
    columns: str = Field(
        default="",
        description="Optional comma-separated output columns for the generated dataset.",
    )
    search_results: int = Field(
        default=3,
        description="Number of search results to collect in research mode.",
    )
    max_records: int = Field(
        default=100,
        description="Maximum records to keep in generated datasets.",
    )
    chart: bool = Field(
        default=True,
        description="Whether to generate a chart artifact when possible.",
    )
    chart_engine: str = Field(
        default="llm_code",
        description="'llm', 'llm_code', or 'fixed'.",
    )
    task_type: str = Field(
        default="auto",
        description="Task hint such as comparison, trend_analysis, ranking, or risk_analysis.",
    )
    title: str = Field(
        default="Data Collection Visualization",
        description="Title used in generated artifacts.",
    )
    output_name: str = Field(
        default="",
        description="Optional base filename without extension.",
    )


class DataCollectorVisualizerTool(BaseTool):
    name: str = "data_collector_visualizer"
    description: str = (
        "End-to-end data collection and visualization pipeline. It searches or extracts web data, "
        "builds structured JSON/CSV datasets, synthesizes an evidence-backed answer, writes a "
        "workflow log, and generates trend/comparison/ranking charts when possible. Use this as "
        "the primary tool for requests like fetch daily prices, collect data, build a dataset, "
        "compare sources, rank entities, or visualize trends. Do not pair it with web_search for "
        "the same data collection task unless the user explicitly asks for separate search-only evidence."
    )
    args_schema: Type[BaseModel] = DataCollectorVisualizerInput

    def _run(
        self,
        research: str = "",
        url: str = "",
        prompt: str = "",
        agentql_query: str = "",
        columns: str = "",
        search_results: int = 3,
        max_records: int = 100,
        chart: bool = True,
        chart_engine: str = "llm_code",
        task_type: str = "auto",
        title: str = "Data Collection Visualization",
        output_name: str = "",
    ) -> str:
        try:
            module = self._load_pipeline_module()

            research = (research or "").strip()
            url = (url or "").strip()
            prompt = (prompt or "").strip()
            agentql_query = (agentql_query or "").strip()

            if not research and not url:
                return json.dumps(
                    {
                        "status": "error",
                        "message": "Provide either research or url.",
                    },
                    indent=2,
                )

            if url and not prompt and not agentql_query:
                prompt = research or "Extract the most relevant structured data from this page."

            output_dir = self._resolve_output_dir()
            safe_name = output_name.strip() or self._safe_name(research or url)
            args = argparse.Namespace(
                url=url or None,
                research=research or None,
                query=agentql_query or None,
                prompt=prompt or None,
                columns=columns or None,
                no_column_generator=False,
                api_key=None,
                serpapi_key=None,
                search_results=max(1, int(search_results or 3)),
                max_records=max(1, int(max_records or 100)),
                task_type=task_type or "auto",
                chart=bool(chart),
                chart_engine=chart_engine if chart_engine in {"llm", "llm_code", "fixed"} else "llm_code",
                output_dir=str(output_dir),
                name=safe_name,
                title=title or "Data Collection Visualization",
                timeout=900,
                wait_for=0,
                scroll_to_bottom=False,
                mode="fast",
            )

            paths = module.DataCollectorVisualizerPipeline(args).run()
            result = self._format_result(paths)
            result.update(
                {
                    "status": "success",
                    "mode": "url_collection" if url else "auto_research",
                    "research": research,
                    "url": url,
                }
            )
            return json.dumps(result, indent=2, default=str)
        except BaseException as exc:
            return json.dumps({"status": "error", "message": str(exc)}, indent=2)

    def _load_pipeline_module(self):
        pipeline_path = str(DEFAULT_PIPELINE_PATH)
        if not os.path.exists(pipeline_path):
            raise FileNotFoundError(
                "Data collector visualizer pipeline not found. "
                "Expected core/tools/data_collector_visualizer.py."
            )

        spec = importlib.util.spec_from_file_location("data_collector_visualizer_pipeline", pipeline_path)
        if not spec or not spec.loader:
            raise ImportError(f"Could not load pipeline module from {pipeline_path}")

        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module

    def _resolve_output_dir(self) -> Path:
        configured = os.getenv("DATA_COLLECTOR_OUTPUT_DIR")
        output_dir = Path(configured).expanduser() if configured else DEFAULT_OUTPUT_DIR
        output_dir.mkdir(parents=True, exist_ok=True)
        return output_dir

    def _format_result(self, paths: dict) -> dict:
        normalized = {key: str(value) for key, value in (paths or {}).items() if value}
        answer_markdown = ""
        answer_path = normalized.get("answer")
        if answer_path and os.path.exists(answer_path):
            answer_markdown = Path(answer_path).read_text(encoding="utf-8", errors="ignore")

        artifacts = {}
        for key, kind, mime in (
            ("json", "json", "application/json"),
            ("csv", "csv", "text/csv"),
            ("chart", "chart", "image/png"),
            ("log", "log", "text/plain"),
            ("answer", "answer", "text/markdown"),
        ):
            artifact_path = normalized.get(key)
            if not artifact_path or not os.path.exists(artifact_path):
                continue
            path = Path(artifact_path)
            artifacts[key] = {
                "kind": kind,
                "mime": mime,
                "filename": path.name,
                "path": str(path),
                "url": self._outputs_url(path),
            }

        return {
            "artifacts": artifacts,
            "answer_markdown": answer_markdown,
            "answer_preview": answer_markdown[:2000],
        }

    def _outputs_url(self, path: Path) -> str:
        try:
            rel = path.resolve().relative_to(OUTPUTS_DIR.resolve())
            return "/outputs/" + "/".join(rel.parts)
        except ValueError:
            return ""

    def _safe_name(self, value: str) -> str:
        import re

        base = re.sub(r"[^A-Za-z0-9_-]+", "_", value.strip())[:60].strip("_")
        if not base:
            base = "deep_research"
        return f"{base}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"


# Backward-compatible import alias for older code references.
DeepResearchVisualizerInput = DataCollectorVisualizerInput
DeepResearchVisualizerTool = DataCollectorVisualizerTool
