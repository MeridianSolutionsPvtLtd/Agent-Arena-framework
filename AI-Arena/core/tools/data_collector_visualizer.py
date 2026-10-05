"""
Collect structured web data with AgentQL and create simple visual outputs.

Usage:
    python data_collector_visualizer.py --url https://www.agentql.com/blog --query "{ posts[] { title url date author } }"

Or:
    python data_collector_visualizer.py --url https://www.agentql.com/blog --prompt "blog posts with title, url, date, and author"

Interactive:
    python data_collector_visualizer.py

Auto research with SerpAPI:
    python data_collector_visualizer.py --research "compare recent data points across sources and visualize the trend"

Set your API key before running:
    set AGENTQL_API_KEY=your_key_here
    set SERPAPI_API_KEY=your_serpapi_key_here

Optional:
    python data_collector_visualizer.py --api-key your_key_here --url ... --prompt ...
"""

from __future__ import annotations

import argparse
import ast
import csv
import json
import logging
import os
import re
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

from dotenv import load_dotenv


load_dotenv(Path(__file__).resolve().parents[2] / ".env")


GENERIC_BASE_COLUMNS = [
    "entity",
    "metric",
    "value",
    "unit",
    "date",
    "location",
    "category",
    "source_name",
    "source_url",
    "confidence",
    "notes",
]


DEFAULT_OUTPUT_CONTRACT = {
    "domain": "general",
    "task_type": "data_collection",
    "decision_context": "Answer the user's data request with structured evidence.",
    "entities": [],
    "metrics": [],
    "dimensions": ["date", "location", "category"],
    "required_columns": GENERIC_BASE_COLUMNS,
    "source_strategy": {
        "query": "",
        "preferred_source_types": [],
    },
    "deliverables": ["answer", "dataset", "visualization", "sources"],
    "sections": ["summary", "key_findings", "visualization", "dataset", "sources"],
    "chart_plan": {
        "enabled": False,
        "type": "auto",
        "x_axis": "",
        "y_axis": "",
        "group_by": "",
        "reason": "",
    },
    "quality_rules": [
        "Preserve source URLs.",
        "Represent missing values as empty values or null.",
        "Do not invent values.",
        "Prefer comparable numeric metrics when available.",
    ],
}


EMPTY_MARKERS = {
    "",
    "n/a",
    "na",
    "none",
    "null",
    "not available",
    "not provided",
    "not specified",
    "unknown",
}

NON_VALUE_FIELD_HINTS = {
    "date",
    "time",
    "period",
    "year",
    "month",
    "day",
    "season",
    "url",
    "link",
    "source",
    "name",
    "title",
    "label",
    "category",
    "group",
    "type",
    "venue",
    "location",
}

TEXT_OUTCOME_FIELD_HINTS = {
    "answer",
    "comment",
    "description",
    "detail",
    "finding",
    "note",
    "observation",
    "outcome",
    "reason",
    "result",
    "review",
    "status",
    "summary",
    "verdict",
}

ALLOWED_CHART_TRANSFORMS = {
    "none",
    "count_by_category",
    "count_entity_mentions_in_text",
    "average_by_category",
    "sum_by_category",
    "latest_value_by_entity",
    "rank_by_metric",
}

CHART_CODE_ALLOWED_IMPORT_ROOTS = {
    "math",
    "matplotlib",
    "numpy",
    "pandas",
    "plotly",
    "seaborn",
}

CHART_CODE_BLOCKED_NAMES = {
    "__import__",
    "compile",
    "eval",
    "exec",
    "globals",
    "input",
    "locals",
    "open",
}

RAW_SCHEMA_METADATA_FIELDS = {
    "_record_group",
    "_source_title",
    "_source_url",
    "_source_snippet",
}


@dataclass(frozen=True)
class PipelineConfig:
    """Runtime controls for one tool execution."""

    output_dir: Path
    base_name: str
    max_records: int
    force_chart: bool
    task_type: str
    title: str

    @classmethod
    def from_args(cls, args: argparse.Namespace, default_name: str) -> "PipelineConfig":
        return cls(
            output_dir=Path(args.output_dir),
            base_name=args.name or default_name,
            max_records=args.max_records,
            force_chart=args.chart,
            task_type=args.task_type,
            title=args.title,
        )


@dataclass(frozen=True)
class OutputPaths:
    """Canonical artifact locations for one run."""

    json: Path
    csv: Path
    chart: Path
    log: Path
    answer: Path | None = None

    @classmethod
    def build(cls, output_dir: Path, base_name: str, *, with_answer: bool) -> "OutputPaths":
        return cls(
            json=output_dir / f"{base_name}.json",
            csv=output_dir / f"{base_name}.csv",
            chart=output_dir / f"{base_name}_chart.png",
            log=output_dir / f"{base_name}.log",
            answer=output_dir / f"{base_name}_answer.md" if with_answer else None,
        )

    def as_printable(self, chart_image_path: Path | None = None) -> dict[str, Path]:
        paths = {"json": self.json, "csv": self.csv, "log": self.log}
        if self.answer:
            paths["answer"] = self.answer
        if chart_image_path:
            paths["chart"] = chart_image_path
        return paths


class PipelineLogger:
    """Enterprise workflow trace logger for agent observability."""

    def __init__(self, log_path: Path) -> None:
        self.log_path = log_path
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self.stage_index = 0
        self.started_at = datetime.now()
        self._write(
            "\n".join(
                [
                    "AI Workflow Execution",
                    "",
                    f"Started: {self.started_at.strftime('%Y-%m-%d %H:%M:%S')}",
                    f"Trace File: {self.log_path}",
                    "",
                ]
            ),
            mode="w",
        )

    @contextmanager
    def stage(
        self,
        name: str,
        *,
        location: str,
        inputs: dict[str, Any] | None = None,
    ) -> Iterator[dict[str, Any]]:
        """
        Log one component execution.

        The yielded dict can be populated by the caller with an "output" key.
        Timing is wall-clock O(1) instrumentation around the real component.
        """
        state: dict[str, Any] = {}
        start = time.perf_counter()
        self.stage_index += 1
        stage_number = self.stage_index
        try:
            yield state
        except Exception as exc:
            elapsed_ms = (time.perf_counter() - start) * 1000
            self._write(
                format_stage_trace(
                    stage_number=stage_number,
                    name=name,
                    location=location,
                    status="FAILED",
                    duration_ms=elapsed_ms,
                    inputs=inputs or {},
                    output={},
                    error=str(exc),
                )
            )
            raise
        else:
            elapsed_ms = (time.perf_counter() - start) * 1000
            output = state.get("output", {})
            status = infer_stage_status(name, output)
            self._write(
                format_stage_trace(
                    stage_number=stage_number,
                    name=name,
                    location=location,
                    status=status,
                    duration_ms=elapsed_ms,
                    inputs=inputs or {},
                    output=output,
                    error=None,
                )
            )

    def _write(self, text: str, *, mode: str = "a") -> None:
        with self.log_path.open(mode, encoding="utf-8") as file:
            file.write(text.rstrip() + "\n\n")
        print(text.rstrip())


def infer_stage_status(name: str, output: Any) -> str:
    if isinstance(output, dict):
        if output.get("chart") == "not_generated" or output.get("exists") is False:
            return "WARNING"
        if output.get("combined_records") == 0:
            return "WARNING"
        if name == "agentql_collect_pages":
            page_results = output.get("page_results", [])
            if isinstance(page_results, list) and page_results:
                errors = [item for item in page_results if item.get("status") == "error"]
                if len(errors) == len(page_results):
                    return "FAILED"
                if errors:
                    return "WARNING"
    return "SUCCESS"


def format_stage_trace(
    *,
    stage_number: int,
    name: str,
    location: str,
    status: str,
    duration_ms: float,
    inputs: dict[str, Any],
    output: Any,
    error: str | None,
) -> str:
    title = humanize_stage_name(name)
    lines = [
        f"Stage {stage_number} - {title}",
        f"Component: {name}",
        f"Code Location: {location}",
        f"Status: {status}",
        f"Duration: {duration_ms / 1000:.2f}s",
    ]

    request = extract_request_summary(inputs)
    if request:
        lines.extend(["", "Request:", *indent_lines(request)])

    if error:
        lines.extend(["", "Error:", *indent_lines([error])])
        lines.extend(format_failure_guidance(error, name))
        return "\n".join(lines)

    output_lines = format_stage_output(name, output)
    if output_lines:
        lines.extend(["", "Outputs:", *indent_lines(output_lines)])

    warning_lines = format_stage_warnings(name, output, status)
    if warning_lines:
        lines.extend(["", "Warnings:", *indent_lines(warning_lines)])

    failure_lines = format_stage_failure(name, output, status)
    if failure_lines:
        lines.extend(failure_lines)

    return "\n".join(lines)


def humanize_stage_name(name: str) -> str:
    acronyms = {
        "agentql": "AgentQL",
        "serpapi": "SerpAPI",
        "json": "JSON",
        "csv": "CSV",
        "llm": "LLM",
    }
    return " ".join(acronyms.get(part, part.capitalize()) for part in name.split("_"))


def indent_lines(lines: list[str], level: int = 1) -> list[str]:
    prefix = "  " * level
    return [prefix + line for line in lines]


def extract_request_summary(inputs: dict[str, Any]) -> list[str]:
    if "question" in inputs:
        return [str(inputs["question"]).replace("\n", " ").strip()]
    if "query" in inputs:
        return [f"Query: {inputs['query']}", f"Requested Results: {inputs.get('num_results', '')}"]
    if "url" in inputs:
        return [f"URL: {inputs['url']}"]
    return []


def format_stage_output(name: str, output: Any) -> list[str]:
    if not isinstance(output, dict):
        return [str(output)]

    if name == "infer_output_contract":
        return format_contract_output(output)
    if name == "plan_search_query":
        return [f"Generated Query: \"{output.get('search_query', '')}\""]
    if name == "plan_columns":
        return format_list_block("Columns", output.get("planned_columns", []), count=output.get("count"))
    if name == "serpapi_search":
        return format_sources(output.get("search_results", []))
    if name == "agentql_collect_pages":
        return format_page_collection(output.get("page_results", []), output.get("raw_records"))
    if name == "normalize_prune_records":
        lines = [
            f"Raw Records: {output.get('raw_records', 0)}",
            f"Usable Records: {output.get('combined_records', 0)}",
            f"Schema Strategy: {output.get('schema_strategy', 'unknown')}",
            f"Planned Coverage: {output.get('planned_coverage', 'unknown')}",
            *format_list_block("Fields", output.get("fields", [])),
        ]
        if output.get("schema_strategy") == "recovered_raw_schema":
            lines.extend(format_list_block("Recovered Fields", output.get("recovered_fields", [])))
        return lines
    if name == "synthesize_answer":
        return [f"Answer Length: {output.get('answer_chars', 0)} characters"]
    if name == "plan_chart":
        if output.get("chart") == "not_generated":
            return ["Chart Plan: not generated"]
        return [
            f"Chart Type: {output.get('type', '')}",
            f"Requested Type: {output.get('requested_type', '')}",
            f"X Axis / Label: {output.get('label_field', '')}",
            f"Y Axis / Value: {output.get('value_field', '')}",
            f"Adjustment: {output.get('chart_adjustment', '') or 'none'}",
            f"Points: {len(output.get('points', []))}",
        ]
    if name == "render_chart":
        return [
            f"Requested Engine: {output.get('requested_engine', '')}",
            f"Engine Used: {output.get('engine_used', '')}",
            f"Chart Path: {output.get('chart_path')}",
            f"Chart Code: {output.get('chart_code_path') or 'n/a'}",
            f"Generated: {output.get('exists')}",
            f"Fallback Reason: {output.get('fallback_reason', '') or 'none'}",
            f"LLM Chart Type: {output.get('llm_chart_type', '') or 'n/a'}",
            f"Transform: {output.get('transform', '') or 'none'}",
            f"Transform Rows: {output.get('transform_input_rows', 0)} -> {output.get('transform_output_rows', 0)}",
            f"LLM Rationale: {output.get('llm_rationale', '') or 'n/a'}",
        ]
    if name == "save_artifacts":
        return format_artifacts(output)

    return flatten_dict_for_log(output)


def format_contract_output(contract: dict[str, Any]) -> list[str]:
    lines = [
        f"Domain: {contract.get('domain', '')}",
        f"Task Type: {contract.get('task_type', '')}",
        f"Decision Context: {contract.get('decision_context', '')}",
    ]
    lines.extend(format_list_block("Entities", contract.get("entities", [])))
    lines.extend(format_list_block("Metrics", contract.get("metrics", [])))
    lines.extend(format_list_block("Dimensions", contract.get("dimensions", [])))
    lines.extend(format_list_block("Deliverables", contract.get("deliverables", [])))
    chart_plan = contract.get("chart_plan", {})
    if isinstance(chart_plan, dict):
        lines.append("Chart Plan:")
        lines.extend(indent_lines([
            f"Enabled: {chart_plan.get('enabled', '')}",
            f"Type: {chart_plan.get('type', '')}",
            f"X Axis: {chart_plan.get('x_axis', '')}",
            f"Y Axis: {chart_plan.get('y_axis', '')}",
            f"Group By: {chart_plan.get('group_by', '')}",
        ]))
    return lines


def format_list_block(title: str, values: Any, count: Any = None) -> list[str]:
    if isinstance(values, dict) and values.get("type") == "list":
        values = values.get("sample", [])
    if not isinstance(values, list):
        return [f"{title}: {values}"] if values else []
    if not values:
        return [f"{title}: none"]
    suffix = f" ({count})" if count is not None else ""
    lines = [f"{title}{suffix}:"]
    lines.extend(indent_lines([str(item) for item in values[:12]]))
    if len(values) > 12:
        lines.append(f"  ... {len(values) - 12} more")
    return lines


def format_sources(search_results: Any) -> list[str]:
    if isinstance(search_results, dict) and search_results.get("type") == "list":
        search_results = search_results.get("sample", [])
    if not isinstance(search_results, list) or not search_results:
        return ["Sources: none"]
    lines = [f"Sources: {len(search_results)}"]
    for item in search_results[:8]:
        title = item.get("source") or item.get("title") or "Source"
        url = item.get("url", "")
        lines.append(f"  - {title}: {url}")
    return lines


def format_page_collection(page_results: Any, raw_records: Any) -> list[str]:
    if not isinstance(page_results, list):
        return [f"Raw Records: {raw_records}"]
    ok_count = sum(1 for item in page_results if item.get("status") == "ok")
    error_count = sum(1 for item in page_results if item.get("status") == "error")
    record_count = sum(int(item.get("record_count") or 0) for item in page_results)
    lines = [
        f"Pages Processed: {len(page_results)}",
        f"Successful Pages: {ok_count}",
        f"Failed Pages: {error_count}",
        f"Extracted Records: {record_count}",
    ]
    for item in page_results[:5]:
        source = item.get("search_result", {}).get("source") or item.get("search_result", {}).get("title", "Source")
        status = item.get("status", "")
        records = item.get("record_count", 0)
        lines.append(f"  - {source}: {status}, records={records}")
        if item.get("error"):
            lines.append(f"    Error: {item['error']}")
    return lines


def format_artifacts(output: dict[str, Any]) -> list[str]:
    lines = ["Artifacts Generated:"]
    for key in ["json", "csv", "answer", "chart", "log"]:
        value = output.get(key)
        if value:
            lines.append(f"  - {key}: {value}")
    return lines


def format_stage_warnings(name: str, output: Any, status: str) -> list[str]:
    if status not in {"WARNING", "FAILED"} or not isinstance(output, dict):
        return []
    if name == "normalize_prune_records" and output.get("combined_records") == 0:
        return ["No usable records were extracted after normalization and pruning."]
    if name == "normalize_prune_records" and output.get("schema_strategy") == "recovered_raw_schema":
        return [
            "Planned schema coverage was low.",
            "Recovered useful raw extracted fields instead of dropping valid data.",
        ]
    if name == "plan_chart" and output.get("chart") == "not_generated":
        return ["Chart generation was skipped because no numeric chart-ready dataset was available."]
    if name == "render_chart" and output.get("exists") is False:
        return ["No chart image was written."]
    return []


def format_stage_failure(name: str, output: Any, status: str) -> list[str]:
    if status != "FAILED" or name != "agentql_collect_pages" or not isinstance(output, dict):
        return []
    page_results = output.get("page_results", [])
    errors = [item.get("error", "") for item in page_results if item.get("error")]
    root_cause = most_common_text(errors) or "Page extraction failed."
    lines = [
        "",
        "Root Cause:",
        *indent_lines([root_cause]),
        "",
        "Impact:",
        *indent_lines([
            "Data extraction failed for all source pages.",
            "Dataset may become empty.",
            "Chart generation may be skipped.",
        ]),
        "",
        "Suggested Fix:",
        *indent_lines(suggest_fix_for_error(root_cause)),
    ]
    return lines


def format_failure_guidance(error: str, name: str) -> list[str]:
    return [
        "",
        "Root Cause:",
        *indent_lines([error]),
        "",
        "Suggested Fix:",
        *indent_lines(suggest_fix_for_error(error)),
    ]


def suggest_fix_for_error(error: str) -> list[str]:
    lowered = error.lower()
    if "agentql_api_key" in lowered:
        return ["Set AGENTQL_API_KEY in environment variables or pass --api-key."]
    if "serpapi_api_key" in lowered:
        return ["Set SERPAPI_API_KEY in environment variables or pass --serpapi-key."]
    if "connection" in lowered or "socket" in lowered or "network" in lowered:
        return ["Check network access and rerun with required network permissions."]
    if "matplotlib" in lowered:
        return ["Install matplotlib in the active environment."]
    return ["Inspect the component error and rerun after fixing the failing dependency or input."]


def most_common_text(values: list[str]) -> str:
    counts: dict[str, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    if not counts:
        return ""
    return max(counts.items(), key=lambda item: item[1])[0]


def flatten_dict_for_log(output: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    for key, value in output.items():
        if isinstance(value, list):
            lines.append(f"{key}: {len(value)} item(s)")
        elif isinstance(value, dict):
            lines.append(f"{key}: {', '.join(list(value)[:8])}")
        else:
            lines.append(f"{key}: {value}")
    return lines


def compact_for_log(value: Any, *, max_text: int = 700) -> str:
    """Create bounded log text so large responses do not flood the console."""
    try:
        text = json.dumps(summarize_for_log(value), ensure_ascii=False, default=str)
    except TypeError:
        text = str(value)
    if len(text) > max_text:
        return text[:max_text] + "...[truncated]"
    return text


def summarize_for_log(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, list):
        return {"type": "list", "count": len(value), "sample": value[:2]}
    if isinstance(value, dict):
        summary: dict[str, Any] = {}
        for key, item in value.items():
            if isinstance(item, list):
                summary[key] = {"type": "list", "count": len(item), "sample": item[:2]}
            elif isinstance(item, dict):
                summary[key] = {"type": "dict", "keys": list(item)[:12]}
            else:
                summary[key] = item
        return summary
    return value


def load_dotenv_if_available() -> None:
    """Load .env values when python-dotenv is installed."""
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv()


def require_package() -> None:
    """Show a clear install message if langchain-agentql is missing."""
    try:
        import langchain_agentql  # noqa: F401
    except ImportError as exc:
        raise SystemExit(
            "Missing dependency: langchain-agentql\n"
            "Install it with:\n"
            "    pip install -U langchain-agentql"
        ) from exc


def collect_with_agentql(
    url: str,
    *,
    query: str | None = None,
    prompt: str | None = None,
    api_key: str | None = None,
    timeout: int = 900,
    wait_for: int = 0,
    scroll_to_bottom: bool = False,
    mode: str = "fast",
) -> dict[str, Any]:
    """
    Extract structured data from a public web page using AgentQL's REST-backed
    LangChain tool.

    Args:
        url: Public web page URL.
        query: AgentQL query, for example "{ posts[] { title url date author } }".
        prompt: Natural language extraction instruction.
        api_key: AgentQL API key. If omitted, AGENTQL_API_KEY is used.
        timeout: Request timeout in seconds.
        wait_for: Seconds to wait before extraction.
        scroll_to_bottom: Whether AgentQL should scroll before extracting.
        mode: "fast" or "standard".

    Returns:
        AgentQL tool response as a dictionary.
    """
    if not query and not prompt:
        raise ValueError("Provide either query or prompt.")

    require_package()

    selected_api_key = api_key or os.environ.get("AGENTQL_API_KEY")
    if selected_api_key:
        os.environ["AGENTQL_API_KEY"] = selected_api_key

    if not os.environ.get("AGENTQL_API_KEY"):
        raise ValueError(
            "AGENTQL_API_KEY is not set. Set it in the environment or pass --api-key."
        )

    from langchain_agentql.tools import ExtractWebDataTool

    tool = ExtractWebDataTool(
        timeout=timeout,
        wait_for=wait_for,
        is_scroll_to_bottom_enabled=scroll_to_bottom,
        mode=mode,
    )

    payload: dict[str, Any] = {"url": url}
    if query:
        payload["query"] = query
    if prompt:
        payload["prompt"] = prompt

    result = tool.invoke(payload)
    if not isinstance(result, dict):
        return {"data": result}
    return result


def search_web_serpapi(
    research_question: str,
    *,
    api_key: str | None = None,
    num_results: int = 5,
) -> list[dict[str, Any]]:
    """
    Search the web with SerpAPI and return normalized organic results.

    The function uses SERPAPI_API_KEY unless api_key is passed directly.
    """
    selected_api_key = api_key or os.environ.get("SERPAPI_API_KEY")
    if not selected_api_key:
        raise ValueError(
            "SERPAPI_API_KEY is not set. Set it in the environment or pass --serpapi-key."
        )

    try:
        import requests
    except ImportError as exc:
        raise SystemExit(
            "Missing dependency: requests\n"
            "Install it with:\n"
            "    pip install requests"
        ) from exc

    response = requests.get(
        "https://serpapi.com/search.json",
        params={
            "engine": "google",
            "q": research_question,
            "api_key": selected_api_key,
            "num": num_results,
        },
        timeout=45,
    )
    response.raise_for_status()
    payload = response.json()

    results: list[dict[str, Any]] = []
    for item in payload.get("organic_results", [])[:num_results]:
        link = item.get("link")
        if not link:
            continue
        results.append(
            {
                "title": item.get("title", ""),
                "url": link,
                "snippet": item.get("snippet", ""),
                "position": item.get("position", len(results) + 1),
                "source": item.get("source", ""),
            }
        )

    return results


def dedupe_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        clean_value = value.strip()
        if not clean_value or clean_value in seen:
            continue
        seen.add(clean_value)
        result.append(clean_value)
    return result


def parse_json_array(text: str) -> list[str]:
    """Parse a JSON string that should contain a list of column names."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:].strip()

    start = cleaned.find("[")
    end = cleaned.rfind("]")
    if start >= 0 and end > start:
        cleaned = cleaned[start : end + 1]

    parsed = json.loads(cleaned)
    if not isinstance(parsed, list):
        return []

    return [
        str(item).strip().lower().replace(" ", "_")
        for item in parsed
        if str(item).strip()
    ]


def parse_json_object(text: str) -> dict[str, Any]:
    """Parse a JSON object from plain text or a fenced LLM response."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:].strip()

    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start >= 0 and end > start:
        cleaned = cleaned[start : end + 1]

    parsed = json.loads(cleaned)
    return parsed if isinstance(parsed, dict) else {}


def normalize_slug(value: str) -> str:
    cleaned = "".join(char.lower() if char.isalnum() else "_" for char in value)
    return "_".join(part for part in cleaned.split("_") if part)


def generate_columns_with_llm(question: str) -> list[str]:
    """
    Generate output columns from the user's question using the repo's LLM config.

    Uses core.llm_factory, which supports Azure OpenAI, OpenAI, and Ollama based on
    environment variables. Failures fall back to local heuristic planning.
    """
    if not has_configured_llm():
        return []

    try:
        content = invoke_llm_text(
            "You generate compact CSV column schemas for research datasets. "
            "Return only a JSON array of snake_case column names. "
            "Do not include markdown, explanations, or nested objects. "
            "Choose 6 to 12 columns. Always include source_name and source_url.",
            "Create dataset columns for this research/data collection question:\n"
            f"{question}",
        )
        return dedupe_preserve_order(parse_json_array(str(content)))[:14]
    except Exception:
        return []


def invoke_llm_text(system_prompt: str, user_prompt: str) -> str:
    """Call the repo-configured chat model and return plain text."""
    try:
        from core.orchestration.llm_factory import get_llm_provider

        model = get_llm_provider()
    except Exception:
        from core.llm_factory import create_langchain_chat_model

        model = create_langchain_chat_model(temperature=0)
    response = model.invoke([("system", system_prompt), ("human", user_prompt)])
    content = getattr(response, "content", str(response))
    if isinstance(content, list):
        return " ".join(str(part) for part in content)
    return str(content)


def has_configured_llm() -> bool:
    return bool(
        os.getenv("LLM_PROVIDER")
        or os.getenv("OPENAI_API_KEY")
        or (os.getenv("AZURE_OPENAI_API_KEY") and os.getenv("AZURE_OPENAI_ENDPOINT"))
    )


def infer_output_contract_node(question: str, requested_task_type: str = "auto") -> dict[str, Any]:
    """
    Infer a domain-agnostic output contract from a user request.

    This keeps the tool generic. A user may ask about commerce, medicine,
    education, law, sports, science, public policy, local services, or any other
    field; the pipeline uses the inferred contract instead of static use cases.
    """
    q = question.lower()
    contract = dict(DEFAULT_OUTPUT_CONTRACT)

    if requested_task_type != "auto":
        contract["task_type"] = normalize_slug(requested_task_type)
    elif any(word in q for word in ["compare", "versus", "vs", "benchmark"]):
        contract["task_type"] = "comparison"
    elif any(word in q for word in ["trend", "history", "over time", "forecast"]):
        contract["task_type"] = "trend_analysis"
    elif any(word in q for word in ["risk", "safety", "regulation", "compliance"]):
        contract["task_type"] = "risk_analysis"
    elif any(word in q for word in ["rank", "best", "top", "shortlist"]):
        contract["task_type"] = "ranking"
    elif any(word in q for word in ["extract", "table", "dataset", "collect"]):
        contract["task_type"] = "data_extraction"

    if not has_configured_llm():
        return contract

    try:
        planned = invoke_llm_text(
            "You create a generic data-tool output contract for any user domain. "
            "Return only JSON with keys: domain, task_type, decision_context, "
            "entities, metrics, dimensions, required_columns, source_strategy, "
            "deliverables, sections, chart_plan, quality_rules. chart_plan must include "
            "enabled, type, x_axis, y_axis, group_by, and reason. The type can be any "
            "reasonable data visualization such as bar, horizontal_bar, line, area, "
            "scatter, pie, histogram, box, heatmap, stacked_bar, or table. Do not restrict "
            "yourself to any fixed use case. "
            "Use compact snake_case names where possible.",
            question,
        )
        parsed = parse_json_object(planned)
        return {
            **contract,
            **parsed,
            "task_type": normalize_slug(str(parsed.get("task_type", contract["task_type"]))),
            "domain": normalize_slug(str(parsed.get("domain", contract["domain"]))),
        }
    except Exception:
        return contract


def estimate_runtime_complexity(
    *,
    search_results: int,
    planned_columns: int,
    max_records: int,
) -> dict[str, Any]:
    """
    Summarize expected cost for agent orchestration.

    Network/runtime cost is dominated by the number of searched pages. Local
    normalization is proportional to records times columns.

    Complexity:
        SerpAPI search: O(1) external call.
        AgentQL extraction: O(P) external calls, where P is search_results.
        Normalization/chart planning: O(R * C), where R is capped records and
        C is planned columns/fields.
    """
    pages = max(search_results, 0)
    columns = max(planned_columns, 1)
    records = max(max_records, 1)
    return {
        "network_calls": f"O({pages}) AgentQL page extractions + 1 SerpAPI search",
        "normalization": f"O({records} records * {columns} columns)",
        "chart_planning": f"O({records} records * {columns} fields)",
        "bounded_by": {
            "search_results": pages,
            "max_records": records,
            "planned_columns": columns,
        },
    }


def plan_search_query_node(question: str) -> str:
    """Rewrite the user question into a concise web-search query."""
    if not has_configured_llm():
        return question

    try:
        rewritten = invoke_llm_text(
            "Rewrite user questions into concise Google search queries. "
            "Correct obvious spelling mistakes. Return only the search query.",
            question,
        )
        return rewritten.strip().strip('"') or question
    except Exception:
        return question


def plan_columns_node(
    question: str,
    *,
    custom_columns: str | None = None,
    use_llm: bool = True,
    output_contract: dict[str, Any] | None = None,
) -> list[str]:
    """
    Plan dataset columns from the user's question.

    This is the schema-planning node. It keeps CSV/chart outputs consistent even
    when different websites return different field names.
    """
    if custom_columns:
        return dedupe_preserve_order(
            [column.strip().lower().replace(" ", "_") for column in custom_columns.split(",")]
        )

    if output_contract:
        contract_columns = [
            normalize_slug(str(column))
            for column in output_contract.get("required_columns", [])
            if str(column).strip()
        ]
        if contract_columns:
            return dedupe_preserve_order(contract_columns)

    if use_llm:
        generated_columns = generate_columns_with_llm(question)
        if generated_columns:
            return generated_columns

    columns = list(GENERIC_BASE_COLUMNS)
    if output_contract:
        dynamic_columns = ["entity"]
        dynamic_columns.extend(normalize_slug(str(item)) for item in output_contract.get("metrics", [])[:6])
        dynamic_columns.extend(normalize_slug(str(item)) for item in output_contract.get("dimensions", [])[:6])
        dynamic_columns.extend(["source_name", "source_url", "confidence", "notes"])
        dynamic_columns = [column for column in dynamic_columns if column]
        if len(dynamic_columns) > 5:
            columns = dedupe_preserve_order(dynamic_columns)

    return dedupe_preserve_order(columns)


def build_planned_extraction_prompt(
    question: str,
    columns: list[str],
    output_contract: dict[str, Any] | None = None,
) -> str:
    column_text = ", ".join(columns)
    contract_text = ""
    if output_contract:
        contract_text = (
            f"Domain: {output_contract.get('domain', 'general')}. "
            f"Task type: {output_contract.get('task_type', 'data_collection')}. "
            f"Decision context: {output_contract.get('decision_context', '')}. "
            f"Entities: {', '.join(str(item) for item in output_contract.get('entities', []))}. "
            f"Metrics: {', '.join(str(item) for item in output_contract.get('metrics', []))}. "
            f"Dimensions: {', '.join(str(item) for item in output_contract.get('dimensions', []))}. "
            f"Chart plan: {json.dumps(output_contract.get('chart_plan', {}), ensure_ascii=False)}. "
            f"Expected deliverables: {', '.join(str(item) for item in output_contract.get('deliverables', []))}. "
            f"Expected report sections: {', '.join(str(item) for item in output_contract.get('sections', []))}.\n\n"
        )
    return (
        contract_text +
        "Extract a clean dataset that answers this research question: "
        f"{question}\n\n"
        "Return records using these exact columns whenever possible: "
        f"{column_text}.\n"
        "Use null or an empty value when a column is not available. Keep numeric values "
        "as numbers when possible. Include source_name, source_url, and confidence when available. "
        "Extract decision-useful facts, metrics, comparisons, risks, dates, and table rows from the page. "
        "Do not invent values that are not present on the page."
    )


def find_first_table_like_data(value: Any) -> list[dict[str, Any]]:
    """
    Find the first list of dictionaries inside an AgentQL response.

    AgentQL usually returns shapes like:
        {"data": {"posts": [{"title": "..."}]}}
    """
    if isinstance(value, list):
        if all(isinstance(item, dict) for item in value):
            return value
        return []

    if isinstance(value, dict):
        for item in value.values():
            found = find_first_table_like_data(item)
            if found:
                return found

    return []


def find_all_table_like_data(value: Any, path: str = "data") -> list[tuple[str, list[dict[str, Any]]]]:
    """Find every list of dictionaries in a nested response."""
    tables: list[tuple[str, list[dict[str, Any]]]] = []

    if isinstance(value, list):
        if value and all(isinstance(item, dict) for item in value):
            return [(path, value)]
        return []

    if isinstance(value, dict):
        for key, item in value.items():
            child_path = f"{path}.{key}" if path else str(key)
            tables.extend(find_all_table_like_data(item, child_path))

    return tables


def collect_records_from_response(response: dict[str, Any]) -> list[dict[str, Any]]:
    """Collect all table-like records from an AgentQL response."""
    tables = find_all_table_like_data(response.get("data", response))
    records: list[dict[str, Any]] = []

    for group_name, group_records in tables:
        for record in group_records:
            enriched_record = dict(record)
            enriched_record["_record_group"] = group_name
            records.append(enriched_record)

    return records


def flatten_record(record: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    """Flatten nested dictionaries so records can be written to CSV."""
    flattened: dict[str, Any] = {}

    for key, value in record.items():
        field_name = f"{prefix}.{key}" if prefix else str(key)

        if isinstance(value, dict):
            flattened.update(flatten_record(value, field_name))
        elif isinstance(value, list):
            flattened[field_name] = json.dumps(value, ensure_ascii=False)
        else:
            flattened[field_name] = value

    return flattened


def normalize_key(key: str) -> str:
    return "".join(char for char in key.lower() if char.isalnum())


def normalize_value(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return value


def has_value(value: Any) -> bool:
    if value is None:
        return False
    text = str(value).strip()
    return text.lower() not in EMPTY_MARKERS


def prune_empty_dataset(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Remove empty rows and columns before producing final user-facing outputs.

    Complexity: O(R * C), where R is number of records and C is number of fields.
    """
    if not records:
        return []

    flattened_records = [flatten_record(record) for record in records]
    non_empty_records = [
        record
        for record in flattened_records
        if any(has_value(value) for key, value in record.items() if not key.startswith("_"))
    ]
    if not non_empty_records:
        return []

    fieldnames = ordered_fieldnames(non_empty_records)
    keep_fields = [
        field
        for field in fieldnames
        if field.startswith("_") or any(has_value(record.get(field)) for record in non_empty_records)
    ]

    return [
        {field: record.get(field, "") for field in keep_fields}
        for record in non_empty_records
    ]


def first_matching_value(flattened: dict[str, Any], column: str) -> Any:
    aliases = {
        "category": ["category", "type", "group", "recordgroup"],
        "confidence": ["confidence", "reliability", "certainty"],
        "date": ["date", "currentdate", "updated", "published", "time"],
        "dimension": ["dimension", "segment", "group", "category"],
        "entity": ["entity", "name", "title", "subject", "item", "organization"],
        "evidence": ["evidence", "quote", "snippet", "support", "source_text"],
        "impact": ["impact", "effect", "consequence"],
        "location": ["location", "city", "country", "region"],
        "metric": ["metric", "measure", "indicator", "field"],
        "notes": ["notes", "description", "summary", "snippet"],
        "period": ["period", "date", "timeframe", "year", "month"],
        "source_name": ["sourcename", "source", "sourcetitle"],
        "source_url": ["sourceurl", "url", "link"],
        "summary": ["summary", "snippet", "description", "notes"],
        "title": ["title", "headline", "name"],
        "unit": ["unit", "measureunit"],
        "url": ["url", "link", "sourceurl"],
        "value": ["value", "amount", "number", "score"],
    }

    normalized_column = normalize_key(column)
    normalized_fields = {normalize_key(key): key for key in flattened}

    for alias in [normalized_column, *aliases.get(column, [])]:
        original_key = normalized_fields.get(normalize_key(alias))
        if original_key and flattened.get(original_key) not in (None, ""):
            return normalize_value(flattened[original_key])

    for normalized_field, original_key in normalized_fields.items():
        if normalized_column in normalized_field and flattened.get(original_key) not in (None, ""):
            return normalize_value(flattened[original_key])

    return ""


def normalize_records_to_columns(
    records: list[dict[str, Any]],
    planned_columns: list[str],
) -> list[dict[str, Any]]:
    """
    Convert varied extraction results into the planned dataset schema.

    Complexity: O(R * C * F), where R is records, C is planned columns, and F is
    flattened source fields. R is bounded by --max-records.
    """
    normalized_records: list[dict[str, Any]] = []

    for record in records:
        flattened = flatten_record(record)
        normalized = {
            column: first_matching_value(flattened, column)
            for column in planned_columns
        }
        if "_record_group" in flattened:
            normalized["_record_group"] = flattened["_record_group"]
        normalized_records.append(normalized)

    return normalized_records


def reconcile_records_to_schema(
    raw_records: list[dict[str, Any]],
    planned_columns: list[str],
    *,
    output_contract: dict[str, Any] | None = None,
    min_coverage: float = 0.4,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """
    Normalize into planned columns, but recover raw schema when coverage is poor.

    This protects production runs from losing valid extracted data when the LLM
    planned a wide schema but the extractor returned long-format rows.
    Complexity: O(R * C * F) for planned normalization plus O(R * F) recovery.
    """
    normalized = prune_empty_dataset(normalize_records_to_columns(raw_records, planned_columns))
    coverage = schema_value_coverage(normalized, planned_columns)
    recovered = recover_raw_schema_records(raw_records)
    recovered = filter_records_by_requested_entities(recovered, output_contract)
    recovered_field_count = len([field for field in ordered_fieldnames(recovered) if not field.startswith("_")])

    should_recover = (
        bool(recovered)
        and recovered_field_count > max(1, len([field for field in ordered_fieldnames(normalized) if not field.startswith("_")]))
        and coverage < min_coverage
    )

    reconciled = recovered if should_recover else augment_with_informative_raw_fields(
        normalized,
        raw_records,
        planned_columns,
    )

    metadata = {
        "strategy": "recovered_raw_schema" if should_recover else "planned_schema",
        "planned_columns": planned_columns,
        "planned_coverage": round(coverage, 3),
        "normalized_fields": ordered_fieldnames(reconciled),
        "recovered_fields": ordered_fieldnames(recovered),
        "raw_records": len(raw_records),
        "usable_records": len(reconciled),
    }
    return reconciled, metadata


def augment_with_informative_raw_fields(
    normalized_records: list[dict[str, Any]],
    raw_records: list[dict[str, Any]],
    planned_columns: list[str],
) -> list[dict[str, Any]]:
    """
    Preserve useful extracted fields that were not part of the planned schema.

    This is generic: fields are kept because their names and values look useful
    for downstream analysis, not because they belong to any specific domain.
    Complexity: O(R * F), where R is records and F is flattened source fields.
    """
    if not normalized_records or not raw_records:
        return normalized_records

    flattened_raw = [flatten_record(record) for record in raw_records[: len(normalized_records)]]
    planned_keys = {normalize_key(column) for column in planned_columns}
    existing_keys = {normalize_key(field) for field in ordered_fieldnames(normalized_records)}
    candidates = informative_raw_fields(flattened_raw, planned_keys | existing_keys)
    if not candidates:
        return normalized_records

    augmented: list[dict[str, Any]] = []
    for index, record in enumerate(normalized_records):
        merged = dict(record)
        raw = flattened_raw[index] if index < len(flattened_raw) else {}
        for field in candidates:
            if field not in merged and has_value(raw.get(field)):
                merged[field] = normalize_value(raw[field])
        augmented.append(merged)
    return prune_empty_dataset(augmented)


def informative_raw_fields(
    flattened_records: list[dict[str, Any]],
    existing_normalized_keys: set[str],
) -> list[str]:
    candidates: list[str] = []
    row_count = max(1, len(flattened_records))
    for field in ordered_fieldnames(flattened_records):
        normalized = normalize_key(field)
        if not normalized or normalized in existing_normalized_keys:
            continue
        if field.startswith("_") or should_drop_recovered_field(field):
            continue
        values = [record.get(field) for record in flattened_records if has_value(record.get(field))]
        if not values:
            continue
        fill_ratio = len(values) / row_count
        if field_has_text_signal(field, values) or field_has_numeric_signal(field, values):
            if fill_ratio >= 0.1:
                candidates.append(field)
    return candidates[:8]


def field_has_text_signal(field: str, values: list[Any]) -> bool:
    normalized = normalize_key(field)
    if any(hint in normalized for hint in TEXT_OUTCOME_FIELD_HINTS):
        return True
    text_values = [str(value).strip() for value in values if isinstance(value, str)]
    if not text_values:
        return False
    average_length = sum(len(value) for value in text_values[:20]) / min(len(text_values), 20)
    return average_length >= 18 and sum(1 for value in text_values if " " in value) >= max(2, len(text_values) // 3)


def field_has_numeric_signal(field: str, values: list[Any]) -> bool:
    if not is_chart_value_field(field):
        return False
    numeric_count = sum(1 for value in values if to_float(value) is not None)
    return numeric_count >= max(2, int(len(values) * 0.6))


def schema_value_coverage(records: list[dict[str, Any]], planned_columns: list[str]) -> float:
    if not records or not planned_columns:
        return 0.0
    filled_columns = 0
    for column in planned_columns:
        if any(has_value(record.get(column)) for record in records):
            filled_columns += 1
    return filled_columns / len(planned_columns)


def recover_raw_schema_records(raw_records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    recovered: list[dict[str, Any]] = []
    for record in raw_records:
        flattened = flatten_record(record)
        cleaned = {
            key: normalize_value(value)
            for key, value in flattened.items()
            if has_value(value) and not should_drop_recovered_field(key)
        }
        for metadata_field in RAW_SCHEMA_METADATA_FIELDS:
            if has_value(flattened.get(metadata_field)):
                cleaned[metadata_field] = flattened[metadata_field]
        if any(has_value(value) for key, value in cleaned.items() if not key.startswith("_")):
            recovered.append(cleaned)
    return prune_empty_dataset(recovered)


def should_drop_recovered_field(field: str) -> bool:
    normalized = normalize_key(field)
    noisy_fragments = ["snippet", "descriptionhtml", "rawhtml"]
    return any(fragment in normalized for fragment in noisy_fragments)


def filter_records_by_requested_entities(
    records: list[dict[str, Any]],
    output_contract: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    if not records or not output_contract:
        return records
    entity_terms = build_entity_terms(output_contract.get("entities", []))
    if not entity_terms:
        return records

    matched = [
        record
        for record in records
        if record_matches_entity_terms(record, entity_terms)
    ]
    return matched if matched else records


def build_entity_terms(entities: Any) -> list[str]:
    if not isinstance(entities, list):
        return []
    terms: list[str] = []
    stopwords = {"the", "and", "vs", "versus", "market", "markets"}
    for entity in entities:
        text = normalize_slug(str(entity)).replace("_", " ")
        if not text:
            continue
        terms.append(text)
        parts = [part for part in text.split() if len(part) >= 3 and part not in stopwords]
        distinctive_parts = [
            part
            for part in parts
            if sum(1 for other in entities if part in normalize_slug(str(other)).replace("_", " ").split()) == 1
        ]
        terms.extend(distinctive_parts or parts)
    return dedupe_preserve_order(terms)


def record_matches_entity_terms(record: dict[str, Any], entity_terms: list[str]) -> bool:
    searchable_values = [
        str(value).lower().replace("_", " ")
        for key, value in record.items()
        if not key.startswith("_") and has_value(value)
    ]
    searchable_text = " ".join(searchable_values)
    return any(term in searchable_text for term in entity_terms)


def cap_records(records: list[dict[str, Any]], max_records: int) -> list[dict[str, Any]]:
    """Bound downstream cost for agent-builder execution."""
    if max_records <= 0:
        return records
    return records[:max_records]


def score_source_result(result: dict[str, Any]) -> str:
    """Simple source-quality label for generated reports."""
    url = str(result.get("url", "")).lower()
    source = str(result.get("source", "")).lower()
    trusted_markers = [".gov", ".edu", "sec.gov", "rbi.org", "worldbank", "imf.org", "oecd.org"]
    company_markers = ["investor", "annual", "press", "ir."]
    if any(marker in url or marker in source for marker in trusted_markers):
        return "high"
    if any(marker in url or marker in source for marker in company_markers):
        return "medium_high"
    if any(marker in url for marker in ["blog", "forum", "reddit", "social"]):
        return "low"
    return "medium"


def make_json_serializable(value: Any) -> Any:
    """Recursively convert common runtime objects before JSON persistence."""
    if isinstance(value, dict):
        return {str(key): make_json_serializable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [make_json_serializable(item) for item in value]
    if isinstance(value, tuple):
        return [make_json_serializable(item) for item in value]
    if isinstance(value, set):
        return sorted(make_json_serializable(item) for item in value)
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def save_json(data: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(make_json_serializable(data), indent=2, ensure_ascii=False), encoding="utf-8")


def save_text(text: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def save_csv(records: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    if not records:
        path.write_text("", encoding="utf-8")
        return

    flattened_records = [flatten_record(record) for record in records]
    fieldnames = ordered_fieldnames(flattened_records)

    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(flattened_records)


def ordered_fieldnames(records: list[dict[str, Any]]) -> list[str]:
    fieldnames: list[str] = []
    seen: set[str] = set()

    for record in records:
        for key in record:
            if key in seen:
                continue
            seen.add(key)
            fieldnames.append(key)

    return fieldnames


def summarize_records(records: list[dict[str, Any]]) -> dict[str, Any]:
    flattened_records = [flatten_record(record) for record in records]
    fields = ordered_fieldnames(flattened_records)

    filled_counts = {
        field: sum(1 for record in flattened_records if record.get(field) not in (None, ""))
        for field in fields
    }

    return {
        "record_count": len(records),
        "field_count": len(fields),
        "fields": fields,
        "filled_counts": filled_counts,
    }


def build_basic_answer(
    question: str,
    records: list[dict[str, Any]],
    search_results: list[dict[str, Any]],
    output_contract: dict[str, Any] | None = None,
) -> str:
    lines = [f"# Answer: {question}", ""]
    lines.append("## Summary")
    lines.append(f"- Collected {len(records)} records from {len(search_results)} search results.")
    if output_contract:
        lines.append(f"- Domain: {output_contract.get('domain', 'general')}.")
        lines.append(f"- Task type: {output_contract.get('task_type', 'data_collection')}.")
    lines.append("- Open the CSV output for the full dataset.")
    lines.append("")
    lines.append("## Sources")
    for item in search_results:
        lines.append(f"- {item.get('title', 'Source')}: {item.get('url', '')}")
    return "\n".join(lines)


def synthesize_answer_node(
    question: str,
    *,
    planned_columns: list[str],
    records: list[dict[str, Any]],
    raw_records: list[dict[str, Any]],
    search_results: list[dict[str, Any]],
    output_contract: dict[str, Any] | None = None,
    runtime_complexity: dict[str, Any] | None = None,
) -> str:
    """
    Convert collected data into a readable answer with tables, bullets, and sources.
    """
    if not has_configured_llm():
        return build_basic_answer(question, records, search_results, output_contract)

    compact_payload = {
        "question": question,
        "output_contract": output_contract,
        "planned_columns": planned_columns,
        "records": records[:80],
        "raw_records_sample": raw_records[:40],
        "sources": search_results,
        "runtime_complexity": runtime_complexity,
    }

    try:
        return invoke_llm_text(
            "You write concise production reports from extracted web data for any domain. "
            "Use the provided data only. If values conflict, provide ranges and mention "
            "that sources vary. Structure the answer for the inferred domain and task type. "
            "Prefer markdown tables for numeric comparisons, include key insights, risks, "
            "recommended next actions, and end with source links. Omit missing fields; "
            "do not fill the answer with 'not provided', 'N/A', or similar placeholders. "
            "Do not invent missing values.",
            json.dumps(compact_payload, ensure_ascii=False),
        ).strip()
    except Exception:
        return build_basic_answer(question, records, search_results, output_contract)


def wants_chart_node(question: str | None, *, force_chart: bool = False) -> bool:
    """Detect whether the user asked for a chart/plot/graph visualization."""
    if force_chart:
        return True
    if not question:
        return False

    q = question.lower()
    chart_words = [
        "chart",
        "plot",
        "graph",
        "visualize",
        "visualise",
        "bar chart",
        "line chart",
        "pie chart",
        "trend",
        "compare visually",
        "comparison chart",
    ]
    return any(word in q for word in chart_words)


def to_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)

    text = str(value)
    cleaned = "".join(char for char in text if char.isdigit() or char in ".-")
    if cleaned in ("", ".", "-", "-."):
        return None

    try:
        return float(cleaned)
    except ValueError:
        return None


def is_chart_value_field(field: str) -> bool:
    normalized = normalize_key(field)
    if not normalized:
        return False
    return not any(hint in normalized for hint in NON_VALUE_FIELD_HINTS)


def is_time_like_field(field: str) -> bool:
    normalized = normalize_key(field)
    return any(hint in normalized for hint in ["date", "time", "period", "year", "month", "day"])


def is_entity_like_field(field: str) -> bool:
    normalized = normalize_key(field)
    return any(hint in normalized for hint in ["name", "entity", "commodity", "model", "company", "brand", "asset", "item"])


def normalize_chart_type(value: str, *, task_type: str = "") -> str:
    requested = normalize_slug(value)
    aliases = {
        "bar_chart": "bar",
        "column": "bar",
        "column_chart": "bar",
        "horizontal_bar_chart": "horizontal_bar",
        "hbar": "horizontal_bar",
        "line_chart": "line",
        "trend": "line",
        "trend_line": "line",
        "area_chart": "area",
        "scatter_plot": "scatter",
        "bubble": "scatter",
        "bubble_chart": "scatter",
        "pie_chart": "pie",
        "donut": "pie",
        "donut_chart": "pie",
        "hist": "histogram",
        "distribution": "histogram",
        "box_plot": "box",
        "boxplot": "box",
        "heat_map": "heatmap",
        "matrix": "heatmap",
        "stacked_column": "stacked_bar",
        "stacked_bar_chart": "stacked_bar",
    }
    supported = {
        "bar",
        "horizontal_bar",
        "line",
        "area",
        "scatter",
        "pie",
        "histogram",
        "box",
        "heatmap",
        "stacked_bar",
        "table",
    }
    normalized = aliases.get(requested, requested)
    if normalized in supported:
        return normalized
    if task_type == "trend_analysis":
        return "line"
    if task_type == "distribution":
        return "histogram"
    return "bar"


def choose_compatible_chart_type(
    requested_type: str,
    *,
    label_field: str,
    value_field: str,
    group_field: str | None,
    records: list[dict[str, Any]],
    task_type: str,
) -> tuple[str, str | None]:
    """
    Ensure chart type fits the actual reconciled data shape.

    The LLM can request any chart, but renderer selection must avoid misleading
    visuals. Cross-sectional entity comparisons should not become line charts.
    """
    chart_type = normalize_chart_type(requested_type, task_type=task_type)
    unique_labels = {
        str(record.get(label_field, "")).strip()
        for record in records
        if has_value(record.get(label_field))
    }
    has_time_axis = is_time_like_field(label_field)
    has_grouping = bool(group_field and any(has_value(record.get(group_field)) for record in records))

    if chart_type in {"line", "area"} and not has_time_axis:
        if has_grouping:
            return "horizontal_bar", "Changed from line/area because the data is categorical with grouping, not a time series."
        return "horizontal_bar", "Changed from line/area because the data is categorical, not a time series."

    if chart_type == "pie" and len(unique_labels) > 8:
        return "horizontal_bar", "Changed from pie because there are too many categories for a readable pie chart."

    if chart_type == "scatter" and len(unique_labels) <= 3 and not has_time_axis:
        return "bar", "Changed from scatter because the data has few categorical comparison points."

    return chart_type, None


def plan_chart_node(
    question: str,
    records: list[dict[str, Any]],
    *,
    force_chart: bool = False,
    fallback_records: list[dict[str, Any]] | None = None,
    search_results: list[dict[str, Any]] | None = None,
    output_contract: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """
    Plan a chart only when the user asks for one.

    The chart is based on available CSV-like records, so it works without extra
    plotting dependencies.
    """
    chart_plan = (output_contract or {}).get("chart_plan", {})
    if not isinstance(chart_plan, dict):
        chart_plan = {}
    contract_wants_chart = bool(chart_plan.get("enabled"))
    if not (contract_wants_chart or wants_chart_node(question, force_chart=force_chart)):
        return None

    flattened_records = [flatten_record(record) for record in records]
    if not flattened_records:
        return None

    fields = ordered_fieldnames(flattened_records)
    numeric_fields = [
        field
        for field in fields
        if is_chart_value_field(field)
        and sum(1 for record in flattened_records if to_float(record.get(field)) is not None) >= 2
    ]
    if not numeric_fields:
        return None

    normalized_fields = {normalize_key(field): field for field in fields}

    def field_from_contract(*names: str) -> str | None:
        for name in names:
            value = str(chart_plan.get(name, "")).strip()
            if not value:
                continue
            exact = normalized_fields.get(normalize_key(value))
            if exact:
                return exact
            for normalized_field, original_field in normalized_fields.items():
                if normalize_key(value) in normalized_field:
                    return original_field
        return None

    label_field = field_from_contract("x_axis", "label_field", "group_by")
    task_type = str((output_contract or {}).get("task_type", ""))
    if label_field and is_time_like_field(label_field) and "comparison" in task_type:
        entity_fields = [field for field in fields if is_entity_like_field(field)]
        if entity_fields:
            label_field = max(
                entity_fields,
                key=lambda field: sum(1 for record in flattened_records if has_value(record.get(field))),
            )
    if not label_field:
        non_numeric_fields = [field for field in fields if field not in numeric_fields]
        entity_fields = [field for field in non_numeric_fields if is_entity_like_field(field)]
        if entity_fields:
            non_numeric_fields = entity_fields
        label_field = max(
            non_numeric_fields or fields,
            key=lambda field: sum(1 for record in flattened_records if has_value(record.get(field))),
        )

    value_field = field_from_contract("y_axis", "value_field", "metric")
    if value_field not in numeric_fields:
        value_field = max(
            numeric_fields,
            key=lambda field: sum(1 for record in flattened_records if to_float(record.get(field)) is not None),
        )

    q = question.lower()
    requested_type = str(chart_plan.get("type", ""))
    task_type = str((output_contract or {}).get("task_type", ""))
    chart_type = normalize_chart_type(
        requested_type,
        task_type=task_type,
    )
    if not chart_plan.get("type"):
        chart_type = "line" if any(word in q for word in ["trend", "line", "over time", "history"]) else chart_type
    group_field = field_from_contract("group_by")
    chart_type, chart_adjustment = choose_compatible_chart_type(
        chart_type,
        label_field=label_field,
        value_field=value_field,
        group_field=group_field,
        records=flattened_records,
        task_type=task_type,
    )

    points: list[dict[str, Any]] = []
    for record in flattened_records:
        value = to_float(record.get(value_field))
        if value is None:
            continue
        label = str(record.get(label_field, "")).strip() or f"Row {len(points) + 1}"
        points.append({"label": label[:80], "value": value})
        if len(points) >= 25:
            break

    if len(points) < 2 and fallback_records:
        return plan_chart_node(
            question,
            fallback_records,
            force_chart=True,
            output_contract=output_contract,
        )

    if len(points) < 2 and search_results:
        snippet_chart = chart_from_search_snippets(search_results)
        if snippet_chart:
            return snippet_chart

    if len(points) < 2:
        return None

    return {
        "type": chart_type,
        "requested_type": requested_type,
        "label_field": label_field,
        "value_field": value_field,
        "group_field": group_field,
        "chart_adjustment": chart_adjustment,
        "reason": chart_plan.get("reason", ""),
        "points": points,
    }


def chart_from_search_snippets(search_results: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Fallback chart from numeric values visible in search snippets."""
    points: list[dict[str, Any]] = []

    for result in search_results:
        snippet = str(result.get("snippet", ""))
        matches = re.findall(r"[-+]?\d[\d,\s]*(?:\.\d+)?\s*%?", snippet)
        for match in matches[:2]:
            value = to_float(match)
            if value is None:
                continue
            label = result.get("source") or result.get("title") or f"Source {len(points) + 1}"
            points.append({"label": str(label)[:80], "value": value})
            break

    if len(points) < 2:
        return None

    return {
        "type": "bar",
        "label_field": "source",
        "value_field": "snippet_numeric_value",
        "points": points[:25],
    }


def require_matplotlib() -> None:
    try:
        import matplotlib  # noqa: F401
    except ImportError as exc:
        raise SystemExit(
            "Missing dependency: matplotlib\n"
            "Install it with:\n"
            "    pip install matplotlib"
        ) from exc


def render_matplotlib_chart(chart_spec: dict[str, Any] | None, output_path: Path) -> Path | None:
    """
    Render the LLM-planned chart as a PNG with Matplotlib.

    Complexity: O(N), where N is chart points. The chart plan is generated by
    the LLM; this function only executes a compatible Matplotlib rendering.
    """
    if not chart_spec or not chart_spec.get("points"):
        return None

    require_matplotlib()
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    points = chart_spec["points"][:25]
    labels = [str(point.get("label", f"Row {index + 1}")) for index, point in enumerate(points)]
    values = [float(point.get("value", 0)) for point in points]
    chart_type = normalize_chart_type(str(chart_spec.get("type", "bar")))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig_width = max(8, min(16, 0.55 * len(labels) + 5))
    fig, ax = plt.subplots(figsize=(fig_width, 5.8), dpi=160)

    title = f"{chart_spec.get('value_field', 'value')} by {chart_spec.get('label_field', 'label')}"
    subtitle = str(chart_spec.get("reason", "")).strip()

    if chart_type == "line":
        ax.plot(labels, values, marker="o", linewidth=2.2, color="#2563eb")
        ax.set_ylabel(str(chart_spec.get("value_field", "value")))
        ax.grid(axis="y", alpha=0.25)
    elif chart_type == "area":
        ax.plot(labels, values, marker="o", linewidth=2, color="#2563eb")
        ax.fill_between(range(len(values)), values, alpha=0.22, color="#2563eb")
        ax.set_xticks(range(len(labels)), labels)
        ax.set_ylabel(str(chart_spec.get("value_field", "value")))
        ax.grid(axis="y", alpha=0.25)
    elif chart_type == "scatter":
        ax.scatter(range(len(values)), values, s=70, color="#0f766e")
        ax.set_xticks(range(len(labels)), labels)
        ax.set_ylabel(str(chart_spec.get("value_field", "value")))
        ax.grid(axis="y", alpha=0.25)
    elif chart_type == "pie":
        positive_points = [(label, value) for label, value in zip(labels, values) if value > 0]
        if len(positive_points) < 2:
            plt.close(fig)
            chart_spec = {**chart_spec, "type": "bar"}
            return render_matplotlib_chart(chart_spec, output_path)
        labels, values = zip(*positive_points)
        ax.pie(values, labels=labels, autopct="%1.1f%%", startangle=90, textprops={"fontsize": 8})
        ax.axis("equal")
    elif chart_type == "histogram":
        ax.hist(values, bins=min(10, max(3, len(values) // 2)), color="#2563eb", edgecolor="#ffffff")
        ax.set_xlabel(str(chart_spec.get("value_field", "value")))
        ax.set_ylabel("count")
        ax.grid(axis="y", alpha=0.25)
    elif chart_type == "box":
        ax.boxplot(values, vert=True, patch_artist=True, boxprops={"facecolor": "#dbeafe"})
        ax.set_xticks([1], [str(chart_spec.get("value_field", "value"))])
        ax.grid(axis="y", alpha=0.25)
    elif chart_type == "heatmap":
        matrix = [[value] for value in values]
        image = ax.imshow(matrix, aspect="auto", cmap="Blues")
        ax.set_yticks(range(len(labels)), labels)
        ax.set_xticks([0], [str(chart_spec.get("value_field", "value"))])
        fig.colorbar(image, ax=ax, fraction=0.046, pad=0.04)
    elif chart_type == "horizontal_bar":
        ax.barh(labels, values, color="#0f766e")
        ax.invert_yaxis()
        ax.set_xlabel(str(chart_spec.get("value_field", "value")))
        ax.grid(axis="x", alpha=0.25)
    else:
        ax.bar(labels, values, color="#0f766e")
        ax.set_ylabel(str(chart_spec.get("value_field", "value")))
        ax.grid(axis="y", alpha=0.25)

    if chart_type not in {"pie", "heatmap", "horizontal_bar", "box", "histogram"}:
        ax.tick_params(axis="x", labelrotation=35)
        for tick in ax.get_xticklabels():
            tick.set_ha("right")

    ax.set_title(title, fontsize=13, weight="bold", pad=12)
    if subtitle and chart_type != "pie":
        ax.text(0, 1.02, subtitle, transform=ax.transAxes, fontsize=9, color="#64748b")
    fig.tight_layout()
    fig.savefig(output_path, bbox_inches="tight")
    plt.close(fig)
    return output_path


def profile_dataset_for_chart(records: list[dict[str, Any]], max_sample: int = 12) -> dict[str, Any]:
    """
    Summarize actual finalized data for visualization planning.

    Complexity: O(R * C), bounded by the finalized dataset size.
    """
    rows = prune_empty_dataset(records)
    fields = ordered_fieldnames(rows)
    profile: dict[str, Any] = {
        "row_count": len(rows),
        "columns": [],
        "sample_rows": rows[:max_sample],
        "available_transforms": sorted(ALLOWED_CHART_TRANSFORMS),
    }
    for field in fields:
        values = [record.get(field) for record in rows if has_value(record.get(field))]
        numeric_count = sum(1 for value in values if to_float(value) is not None)
        unique_count = len({str(value).strip().lower() for value in values[:500]})
        profile["columns"].append(
            {
                "name": field,
                "filled_count": len(values),
                "numeric_count": numeric_count,
                "is_numeric": numeric_count >= max(2, int(len(values) * 0.6)) if values else False,
                "is_time_like": is_time_like_field(field),
                "is_entity_like": is_entity_like_field(field),
                "is_text_outcome_like": field_has_text_signal(field, values),
                "unique_count": unique_count,
                "examples": [str(value) for value in values[:5]],
            }
        )
    return profile


def generate_chart_spec_with_llm(
    question: str,
    records: list[dict[str, Any]],
    output_contract: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Ask the configured LLM for a chart spec, not executable code."""
    if not has_configured_llm() or not records:
        return None
    profile = profile_dataset_for_chart(records)
    columns = [column["name"] for column in profile["columns"]]
    payload = {
        "question": question,
        "output_contract": output_contract or {},
        "dataset_profile": profile,
            "requirements": {
                "allowed_chart_types": [
                    "bar",
                    "horizontal_bar",
                "line",
                "area",
                "scatter",
                "pie",
                "histogram",
                "box",
                    "heatmap",
                ],
                "allowed_transforms": sorted(ALLOWED_CHART_TRANSFORMS),
                "must_use_existing_columns_only": columns,
                "no_code": True,
            },
        }
    try:
        content = invoke_llm_text(
            "You are a senior data visualization engineer. "
            "Choose the most truthful chart for the actual dataset, not just the user request. "
            "Return only JSON with keys: chart_type, transform, x, y, color, text_field, entities, "
            "aggregation, title, rationale, sort_by, limit. "
            "Use only column names that exist in the dataset_profile. Do not return code. "
            "If rows are events or observations and a text outcome/status/result field contains requested "
            "entities, use transform=count_entity_mentions_in_text. If data is categorical, prefer "
            "horizontal_bar or bar. Use line/area only for a real time axis.",
            json.dumps(payload, ensure_ascii=False),
        )
        parsed = parse_json_object(content)
        if not parsed:
            return None
        return validate_chart_spec(parsed, columns)
    except Exception:
        return None


def generate_chart_code_with_llm(
    question: str,
    records: list[dict[str, Any]],
    output_contract: dict[str, Any] | None,
    llm_spec: dict[str, Any] | None,
) -> str | None:
    """Ask the LLM for executable chart code for evaluation mode."""
    if not has_configured_llm() or not records:
        return None
    profile = profile_dataset_for_chart(records, max_sample=20)
    payload = {
        "question": question,
        "output_contract": output_contract or {},
        "chart_spec": llm_spec or {},
        "dataset_profile": profile,
        "requirements": {
            "function_name": "render_chart",
            "signature": "render_chart(records, output_path, context)",
            "output": "Write one PNG chart to output_path and return output_path.",
            "allowed_libraries": sorted(CHART_CODE_ALLOWED_IMPORT_ROOTS),
            "no_network": True,
            "no_file_reads": True,
            "no_file_writes_except_output_path": True,
        },
    }
    content = invoke_llm_text(
        "You are a senior Python data visualization engineer. "
        "Generate production-quality Python chart code for the actual dataset. "
        "Return only Python code, no markdown. "
        "Define exactly one public function: render_chart(records, output_path, context). "
        "The function must create a readable chart, save a PNG to output_path, and return output_path. "
        "Use matplotlib with Agg backend; seaborn, pandas, numpy, or plotly may be used only if helpful. "
        "Do not use network, subprocess, filesystem reads, open(), eval(), exec(), or environment variables. "
        "Prefer aggregation/transformation when raw rows are event-style or text-outcome records.",
        json.dumps(payload, ensure_ascii=False),
    )
    code = extract_python_code(content)
    return code if code.strip() else None


def extract_python_code(content: str) -> str:
    text = content.strip()
    fenced = re.search(r"```(?:python)?\s*(.*?)```", text, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        return fenced.group(1).strip()
    return text


def validate_generated_chart_code(code: str) -> tuple[bool, str]:
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return False, f"Generated chart code has syntax error: {exc}"

    function_names = [node.name for node in tree.body if isinstance(node, ast.FunctionDef)]
    if "render_chart" not in function_names:
        return False, "Generated chart code must define render_chart(records, output_path, context)."

    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            imports = [alias.name for alias in node.names]
            if isinstance(node, ast.ImportFrom) and node.module:
                imports.append(node.module)
            for imported in imports:
                root = imported.split(".")[0]
                if root not in CHART_CODE_ALLOWED_IMPORT_ROOTS:
                    return False, f"Import is not allowed in chart code: {imported}"
        if isinstance(node, ast.Name) and node.id in CHART_CODE_BLOCKED_NAMES:
            return False, f"Blocked name used in chart code: {node.id}"
        if isinstance(node, ast.Attribute) and node.attr.startswith("__"):
            return False, f"Dunder attribute access is blocked: {node.attr}"
        if isinstance(node, ast.Call):
            called = ""
            if isinstance(node.func, ast.Name):
                called = node.func.id
            elif isinstance(node.func, ast.Attribute):
                called = node.func.attr
            if called in CHART_CODE_BLOCKED_NAMES:
                return False, f"Blocked function call used in chart code: {called}"
    return True, ""


def execute_generated_chart_code(
    code: str,
    records: list[dict[str, Any]],
    output_path: Path,
    context: dict[str, Any],
) -> Path | None:
    safe_builtins = {
        "__import__": restricted_chart_import,
        "abs": abs,
        "all": all,
        "any": any,
        "bool": bool,
        "dict": dict,
        "enumerate": enumerate,
        "float": float,
        "int": int,
        "isinstance": isinstance,
        "len": len,
        "list": list,
        "max": max,
        "min": min,
        "range": range,
        "round": round,
        "set": set,
        "sorted": sorted,
        "str": str,
        "sum": sum,
        "tuple": tuple,
        "zip": zip,
    }
    namespace: dict[str, Any] = {"__builtins__": safe_builtins}
    compiled = compile(code, "<llm_chart_code>", "exec")
    exec(compiled, namespace)
    render_fn = namespace.get("render_chart")
    if not callable(render_fn):
        return None
    output_path.parent.mkdir(parents=True, exist_ok=True)
    result = render_fn(records, str(output_path), context)
    chart_path = Path(result or output_path)
    return chart_path if chart_path.exists() else None


def restricted_chart_import(name: str, globals_: Any = None, locals_: Any = None, fromlist: Any = (), level: int = 0) -> Any:
    root = name.split(".")[0]
    if root not in CHART_CODE_ALLOWED_IMPORT_ROOTS:
        raise ImportError(f"Import is not allowed in chart code: {name}")
    return __import__(name, globals_, locals_, fromlist, level)


def validate_chart_spec(spec: dict[str, Any], columns: list[str]) -> dict[str, Any] | None:
    normalized_columns = {normalize_key(column): column for column in columns}

    def existing_column(value: Any) -> str:
        key = normalize_key(str(value))
        return normalized_columns.get(key, "")

    chart_type = normalize_chart_type(str(spec.get("chart_type", "")))
    transform = normalize_slug(str(spec.get("transform", "none") or "none"))
    if transform not in ALLOWED_CHART_TRANSFORMS:
        transform = "none"
    x = existing_column(spec.get("x", ""))
    y = existing_column(spec.get("y", ""))
    color = existing_column(spec.get("color", ""))
    text_field = existing_column(spec.get("text_field", ""))
    sort_by = existing_column(spec.get("sort_by", ""))
    if transform == "count_entity_mentions_in_text":
        if not text_field:
            return None
        x = x or "entity"
        y = y or "count"
        chart_type = "horizontal_bar" if chart_type in {"line", "area", "scatter"} else chart_type
    elif transform == "count_by_category":
        if not x:
            return None
        y = y or "count"
        chart_type = "horizontal_bar" if chart_type in {"line", "area", "scatter"} else chart_type
    elif chart_type not in {"histogram", "box"} and not (x and y):
        return None
    if chart_type in {"line", "area"} and x and not is_time_like_field(x):
        chart_type = "horizontal_bar"
    limit = spec.get("limit") or 25
    try:
        limit = max(2, min(50, int(limit)))
    except (TypeError, ValueError):
        limit = 25
    return {
        "chart_type": chart_type,
        "transform": transform,
        "x": x,
        "y": y,
        "color": color,
        "text_field": text_field,
        "entities": normalize_spec_entities(spec.get("entities", [])),
        "aggregation": normalize_slug(str(spec.get("aggregation", ""))),
        "title": str(spec.get("title", "")).strip(),
        "rationale": str(spec.get("rationale", "")).strip(),
        "sort_by": sort_by,
        "limit": limit,
    }


def normalize_spec_entities(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()][:12]
    if isinstance(value, str) and value.strip():
        return [part.strip() for part in re.split(r"[,|/]", value) if part.strip()][:12]
    return []


def apply_chart_transform(
    llm_spec: dict[str, Any],
    records: list[dict[str, Any]],
    output_contract: dict[str, Any] | None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    transform = normalize_slug(str(llm_spec.get("transform", "none") or "none"))
    rows = prune_empty_dataset([flatten_record(record) for record in records])
    metadata = {
        "transform": transform,
        "input_rows": len(rows),
        "output_rows": len(rows),
    }
    if not rows or transform == "none":
        return rows, metadata

    if transform == "count_entity_mentions_in_text":
        transformed = transform_count_entity_mentions_in_text(llm_spec, rows, output_contract)
    elif transform == "count_by_category":
        transformed = transform_count_by_category(llm_spec, rows)
    elif transform in {"average_by_category", "sum_by_category"}:
        transformed = transform_numeric_by_category(llm_spec, rows, transform)
    elif transform in {"latest_value_by_entity", "rank_by_metric"}:
        transformed = transform_rank_by_metric(llm_spec, rows)
    else:
        transformed = []

    metadata["output_rows"] = len(transformed)
    return (transformed or rows), metadata


def transform_count_entity_mentions_in_text(
    llm_spec: dict[str, Any],
    records: list[dict[str, Any]],
    output_contract: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    text_field = str(llm_spec.get("text_field", ""))
    if not text_field:
        return []
    entities = normalize_spec_entities(llm_spec.get("entities")) or normalize_spec_entities((output_contract or {}).get("entities"))
    if not entities:
        return []

    entity_terms = {entity: build_entity_terms([entity]) for entity in entities}
    counts = {entity: 0 for entity in entities}
    deduped = dedupe_records_for_transform(records)
    for record in deduped:
        text = str(record.get(text_field, "")).lower().replace("_", " ")
        if not text:
            continue
        matched_entity = first_entity_match(text, entity_terms)
        if matched_entity:
            counts[matched_entity] += 1

    return [
        {"entity": entity, "count": count}
        for entity, count in sorted(counts.items(), key=lambda item: item[1], reverse=True)
        if count > 0
    ]


def first_entity_match(text: str, entity_terms: dict[str, list[str]]) -> str:
    best_entity = ""
    best_position: int | None = None
    for entity, terms in entity_terms.items():
        positions = [text.find(term) for term in terms if term and text.find(term) >= 0]
        if not positions:
            continue
        position = min(positions)
        if best_position is None or position < best_position:
            best_entity = entity
            best_position = position
    return best_entity


def transform_count_by_category(llm_spec: dict[str, Any], records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    x_field = str(llm_spec.get("x", ""))
    if not x_field:
        return []
    counts: dict[str, int] = {}
    for record in dedupe_records_for_transform(records, preferred_fields=[x_field]):
        label = str(record.get(x_field, "")).strip()
        if not label:
            continue
        counts[label] = counts.get(label, 0) + 1
    return [
        {x_field: label, "count": count}
        for label, count in sorted(counts.items(), key=lambda item: item[1], reverse=True)
    ]


def transform_numeric_by_category(
    llm_spec: dict[str, Any],
    records: list[dict[str, Any]],
    transform: str,
) -> list[dict[str, Any]]:
    x_field = str(llm_spec.get("x", ""))
    y_field = str(llm_spec.get("y", ""))
    if not x_field or not y_field:
        return []
    groups: dict[str, list[float]] = {}
    for record in dedupe_records_for_transform(records, preferred_fields=[x_field, y_field]):
        label = str(record.get(x_field, "")).strip()
        value = to_float(record.get(y_field))
        if not label or value is None:
            continue
        groups.setdefault(label, []).append(value)
    rows: list[dict[str, Any]] = []
    for label, values in groups.items():
        metric = sum(values) / len(values) if transform == "average_by_category" else sum(values)
        rows.append({x_field: label, y_field: metric})
    return sorted(rows, key=lambda row: to_float(row.get(y_field)) or 0, reverse=True)


def transform_rank_by_metric(llm_spec: dict[str, Any], records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    y_field = str(llm_spec.get("y", ""))
    if not y_field:
        return []
    rows = [
        record
        for record in dedupe_records_for_transform(records, preferred_fields=[str(llm_spec.get("x", "")), y_field])
        if to_float(record.get(y_field)) is not None
    ]
    return sorted(rows, key=lambda row: to_float(row.get(y_field)) or 0, reverse=True)


def dedupe_records_for_transform(
    records: list[dict[str, Any]],
    *,
    preferred_fields: list[str] | None = None,
) -> list[dict[str, Any]]:
    seen: set[tuple[Any, ...]] = set()
    deduped: list[dict[str, Any]] = []
    preferred_fields = [field for field in (preferred_fields or []) if field]
    for record in records:
        if preferred_fields and any(has_value(record.get(field)) for field in preferred_fields):
            key = tuple(normalize_slug(str(record.get(field, ""))) for field in preferred_fields)
        else:
            key = tuple(
                (field, normalize_slug(str(value)))
                for field, value in sorted(record.items())
                if not field.startswith("_") and has_value(value)
            )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(record)
    return deduped


def chart_spec_from_llm_spec(llm_spec: dict[str, Any], records: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not llm_spec:
        return None
    chart_type = normalize_chart_type(str(llm_spec.get("chart_type", "bar")))
    x_field = str(llm_spec.get("x", ""))
    y_field = str(llm_spec.get("y", ""))
    if not x_field or not y_field:
        return None
    rows = prune_empty_dataset(records)
    sort_by = str(llm_spec.get("sort_by", ""))
    if sort_by:
        rows = sorted(rows, key=lambda row: to_float(row.get(sort_by)) or 0, reverse=True)
    points: list[dict[str, Any]] = []
    for row in rows:
        value = to_float(row.get(y_field))
        if value is None:
            continue
        label = str(row.get(x_field, "")).strip() or f"Row {len(points) + 1}"
        points.append({"label": label[:80], "value": value})
        if len(points) >= int(llm_spec.get("limit") or 25):
            break
    if len(points) < 2:
        return None
    return {
        "type": chart_type,
        "requested_type": chart_type,
        "label_field": x_field,
        "value_field": y_field,
        "group_field": llm_spec.get("color") or None,
        "chart_adjustment": None,
        "reason": llm_spec.get("rationale", ""),
        "title": llm_spec.get("title", ""),
        "points": points,
    }


def render_chart_with_engine(
    *,
    engine: str,
    question: str,
    records: list[dict[str, Any]],
    output_path: Path,
    output_contract: dict[str, Any] | None,
    chart_spec: dict[str, Any] | None,
) -> tuple[Path | None, dict[str, Any]]:
    """
    Render chart using an LLM-planned spec or fixed Matplotlib fallback.

    The LLM engine runs after final data is available, so it can choose a chart
    and a safe transform based on actual schema and rows. Rendering always uses
    deterministic Matplotlib templates.
    """
    metadata: dict[str, Any] = {
        "requested_engine": engine,
        "engine_used": None,
        "chart_path": None,
        "chart_code_path": None,
        "exists": False,
        "fallback_reason": "",
        "llm_chart_type": "",
        "llm_rationale": "",
        "transform": "",
        "transform_input_rows": 0,
        "transform_output_rows": 0,
    }
    if engine in {"llm", "llm_code"}:
        try:
            llm_spec = generate_chart_spec_with_llm(question, records, output_contract)
            chart_records, transform_metadata = apply_chart_transform(llm_spec or {}, records, output_contract)
            if engine == "llm_code" and llm_spec:
                chart_code = generate_chart_code_with_llm(question, chart_records, output_contract, llm_spec)
                if chart_code:
                    code_path = output_path.with_name(f"{output_path.stem}_code.py")
                    code_path.write_text(chart_code, encoding="utf-8")
                    is_valid, validation_error = validate_generated_chart_code(chart_code)
                    if is_valid:
                        chart_path = execute_generated_chart_code(
                            chart_code,
                            chart_records,
                            output_path,
                            {
                                "question": question,
                                "output_contract": output_contract or {},
                                "chart_spec": llm_spec,
                                "transform": transform_metadata,
                            },
                        )
                        if chart_path:
                            metadata.update(
                                {
                                    "engine_used": "llm_generated_code",
                                    "chart_path": chart_path,
                                    "chart_code_path": code_path,
                                    "exists": True,
                                    "llm_chart_type": llm_spec.get("chart_type", ""),
                                    "llm_rationale": llm_spec.get("rationale", ""),
                                    "transform": transform_metadata.get("transform", ""),
                                    "transform_input_rows": transform_metadata.get("input_rows", 0),
                                    "transform_output_rows": transform_metadata.get("output_rows", 0),
                                }
                            )
                            return chart_path, metadata
                        metadata["fallback_reason"] = "LLM-generated chart code executed but did not write a chart."
                    else:
                        metadata["fallback_reason"] = validation_error
                else:
                    metadata["fallback_reason"] = "LLM chart code was not generated."

            llm_chart_spec = chart_spec_from_llm_spec(llm_spec or {}, chart_records)
            chart_path = render_matplotlib_chart(llm_chart_spec, output_path)
            if chart_path and llm_spec:
                metadata.update(
                    {
                        "engine_used": "llm_spec_template",
                        "chart_path": chart_path,
                        "exists": True,
                        "llm_chart_type": llm_spec.get("chart_type", ""),
                        "llm_rationale": llm_spec.get("rationale", ""),
                        "chart_code_path": metadata.get("chart_code_path"),
                        "transform": transform_metadata.get("transform", ""),
                        "transform_input_rows": transform_metadata.get("input_rows", 0),
                        "transform_output_rows": transform_metadata.get("output_rows", 0),
                    }
                )
                return chart_path, metadata
            metadata["fallback_reason"] = "LLM chart spec was not generated or not renderable."
        except Exception as exc:
            metadata["fallback_reason"] = f"LLM chart spec rendering failed: {exc}"

    chart_path = render_matplotlib_chart(chart_spec, output_path)
    metadata.update(
        {
                    "engine_used": "fixed_matplotlib" if chart_path else None,
                    "chart_path": chart_path,
                    "chart_code_path": metadata.get("chart_code_path"),
                    "exists": bool(chart_path),
                }
            )
    return chart_path, metadata


def guess_output_name(url: str) -> str:
    cleaned = (
        url.replace("https://", "")
        .replace("http://", "")
        .replace("/", "_")
        .replace("?", "_")
        .replace("&", "_")
        .replace("=", "-")
    )
    return "".join(char if char.isalnum() or char in "._-" else "_" for char in cleaned)


def guess_name_from_text(text: str) -> str:
    cleaned = "".join(char.lower() if char.isalnum() else "_" for char in text)
    cleaned = "_".join(part for part in cleaned.split("_") if part)
    return cleaned[:80] or "research_output"


class DataCollectorVisualizerPipeline:
    """Production-style orchestration for collection, normalization, and chart output."""

    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.log: PipelineLogger | None = None

    def run(self) -> dict[str, Path]:
        if self.args.url:
            return self.run_url_collection()
        return self.run_auto_research()

    def run_url_collection(self) -> dict[str, Path]:
        """Collect from one supplied URL. Complexity is one AgentQL call plus O(R*C)."""
        direct_question = self.args.prompt or self.args.query or self.args.url
        config = PipelineConfig.from_args(self.args, guess_output_name(self.args.url))
        paths = OutputPaths.build(config.output_dir, config.base_name, with_answer=False)
        self.log = PipelineLogger(paths.log)

        with self._stage("infer_output_contract", "infer_output_contract_node", {"question": direct_question}) as stage:
            output_contract = infer_output_contract_node(direct_question, config.task_type)
            stage["output"] = output_contract

        with self._stage("agentql_extract_url", "collect_with_agentql", {"url": self.args.url}) as stage:
            result = collect_with_agentql(
                self.args.url,
                query=self.args.query,
                prompt=self.args.prompt,
                api_key=self.args.api_key,
                timeout=self.args.timeout,
                wait_for=self.args.wait_for,
                scroll_to_bottom=self.args.scroll_to_bottom,
                mode=self.args.mode,
            )
            stage["output"] = {"response_keys": list(result)[:12]}

        with self._stage("extract_normalize_prune", "collect_records_from_response/prune_empty_dataset", {"max_records": config.max_records}) as stage:
            raw_records = cap_records(collect_records_from_response(result), config.max_records)
            records = prune_empty_dataset(raw_records)
            summary = summarize_records(records)
            stage["output"] = {"raw_records": len(raw_records), "records": len(records), "fields": summary["fields"]}

        with self._stage("plan_chart", "plan_chart_node", {"force_chart": config.force_chart}) as stage:
            chart_spec = plan_chart_node(
                direct_question,
                records,
                force_chart=config.force_chart,
                output_contract=output_contract,
            )
            stage["output"] = chart_spec or {"chart": "not_generated"}

        with self._stage("render_chart", "render_matplotlib_chart", {"chart_path": paths.chart}) as stage:
            chart_image_path, chart_metadata = render_chart_with_engine(
                engine=self.args.chart_engine,
                question=direct_question,
                records=records,
                output_path=paths.chart,
                output_contract=output_contract,
                chart_spec=chart_spec,
            )
            stage["output"] = chart_metadata

        runtime_complexity = estimate_runtime_complexity(
            search_results=1,
            planned_columns=summary["field_count"],
            max_records=config.max_records,
        )
        result = {
            "mode": "url_collection",
            "output_contract": output_contract,
            "runtime_complexity": runtime_complexity,
            "chart_spec": chart_spec,
            "chart_metadata": chart_metadata,
            "agentql_response": result,
        }

        with self._stage("save_artifacts", "save_json/save_csv", {"json": paths.json, "csv": paths.csv}) as stage:
            save_json(result, paths.json)
            save_csv(records, paths.csv)
            stage["output"] = {"json": paths.json, "csv": paths.csv, "log": paths.log}
        return paths.as_printable(chart_image_path)

    def run_auto_research(self) -> dict[str, Path]:
        """
        Search then collect from multiple pages.

        Complexity: O(P) network page extractions and O(R*C*F) normalization,
        where P is --search-results, R is bounded by --max-records, C is planned
        columns, and F is flattened extracted fields.
        """
        research_question = self.args.research or self.args.prompt
        if not research_question:
            raise ValueError("Auto research needs a question.")

        config = PipelineConfig.from_args(self.args, guess_name_from_text(research_question))
        paths = OutputPaths.build(config.output_dir, config.base_name, with_answer=True)
        self.log = PipelineLogger(paths.log)

        with self._stage("infer_output_contract", "infer_output_contract_node", {"question": research_question}) as stage:
            output_contract = infer_output_contract_node(research_question, config.task_type)
            stage["output"] = output_contract

        with self._stage("plan_search_query", "_search_query/plan_search_query_node", {"question": research_question}) as stage:
            search_query = self._search_query(research_question, output_contract)
            stage["output"] = {"search_query": search_query}

        with self._stage("plan_columns", "plan_columns_node", {"custom_columns": self.args.columns}) as stage:
            planned_columns = plan_columns_node(
                research_question,
                custom_columns=self.args.columns,
                use_llm=not self.args.no_column_generator,
                output_contract=output_contract,
            )
            stage["output"] = {"planned_columns": planned_columns, "count": len(planned_columns)}

        with self._stage("serpapi_search", "search_web_serpapi", {"query": search_query, "num_results": self.args.search_results}) as stage:
            search_results = search_web_serpapi(
                search_query,
                api_key=self.args.serpapi_key,
                num_results=self.args.search_results,
            )
            stage["output"] = {"search_results": search_results}

        with self._stage("build_extraction_prompt", "_extraction_prompt/build_planned_extraction_prompt", {"columns": len(planned_columns)}) as stage:
            extraction_prompt = self._extraction_prompt(
                research_question,
                planned_columns,
                output_contract,
            )
            stage["output"] = {"prompt_chars": len(extraction_prompt)}

        with self._stage("agentql_collect_pages", "_collect_pages/collect_with_agentql", {"pages": len(search_results)}) as stage:
            page_results, raw_records = self._collect_pages(search_results, extraction_prompt)
            stage["output"] = {"page_results": page_results, "raw_records": len(raw_records)}

        with self._stage("normalize_prune_records", "normalize_records_to_columns/prune_empty_dataset", {"max_records": config.max_records}) as stage:
            raw_records = self._fallback_records(raw_records, search_results)
            raw_records = cap_records(raw_records, config.max_records)
            combined_records, schema_metadata = reconcile_records_to_schema(
                raw_records,
                planned_columns,
                output_contract=output_contract,
            )
            stage["output"] = {
                "raw_records": len(raw_records),
                "combined_records": len(combined_records),
                "fields": ordered_fieldnames(combined_records),
                "schema_strategy": schema_metadata["strategy"],
                "planned_coverage": schema_metadata["planned_coverage"],
                "recovered_fields": schema_metadata["recovered_fields"],
            }

        runtime_complexity = estimate_runtime_complexity(
            search_results=len(search_results),
            planned_columns=len(planned_columns),
            max_records=config.max_records,
        )

        with self._stage("synthesize_answer", "synthesize_answer_node", {"records": len(combined_records)}) as stage:
            answer_markdown = synthesize_answer_node(
                research_question,
                planned_columns=planned_columns,
                records=combined_records,
                raw_records=raw_records,
                search_results=search_results,
                output_contract=output_contract,
                runtime_complexity=runtime_complexity,
            )
            stage["output"] = {"answer_chars": len(answer_markdown)}

        with self._stage("plan_chart", "plan_chart_node", {"force_chart": config.force_chart}) as stage:
            chart_spec = plan_chart_node(
                research_question,
                combined_records,
                force_chart=config.force_chart,
                fallback_records=raw_records,
                search_results=search_results,
                output_contract=output_contract,
            )
            stage["output"] = chart_spec or {"chart": "not_generated"}

        with self._stage("render_chart", "render_chart_with_engine", {"chart_path": paths.chart, "engine": self.args.chart_engine}) as stage:
            chart_image_path, chart_metadata = render_chart_with_engine(
                engine=self.args.chart_engine,
                question=research_question,
                records=combined_records,
                output_path=paths.chart,
                output_contract=output_contract,
                chart_spec=chart_spec,
            )
            stage["output"] = chart_metadata

        with self._stage("save_artifacts", "save_json/save_csv/save_text", {"json": paths.json, "csv": paths.csv, "answer": paths.answer}) as stage:
            save_json(
                {
                    "mode": "auto_research",
                    "research_question": research_question,
                    "output_contract": output_contract,
                    "runtime_complexity": runtime_complexity,
                    "search_query": search_query,
                    "planned_columns": planned_columns,
                    "chart_spec": chart_spec,
                    "chart_metadata": chart_metadata,
                    "chart_path": str(chart_image_path) if chart_image_path else None,
                    "search_results": search_results,
                    "page_results": page_results,
                    "raw_combined_records": raw_records,
                    "combined_records": combined_records,
                    "answer_markdown": answer_markdown,
                },
                paths.json,
            )
            save_csv(combined_records, paths.csv)
            if paths.answer:
                save_text(answer_markdown, paths.answer)
            stage["output"] = {"json": paths.json, "csv": paths.csv, "answer": paths.answer, "log": paths.log}
        return paths.as_printable(chart_image_path)

    @contextmanager
    def _stage(
        self,
        name: str,
        location: str,
        inputs: dict[str, Any] | None = None,
    ) -> Iterator[dict[str, Any]]:
        if not self.log:
            yield {}
            return
        with self.log.stage(name, location=location, inputs=inputs) as stage:
            yield stage

    def _search_query(self, question: str, output_contract: dict[str, Any]) -> str:
        source_strategy = output_contract.get("source_strategy", {})
        if not isinstance(source_strategy, dict):
            source_strategy = {}
        return str(source_strategy.get("query", "")).strip() or plan_search_query_node(question)

    def _extraction_prompt(
        self,
        question: str,
        planned_columns: list[str],
        output_contract: dict[str, Any],
    ) -> str:
        if self.args.prompt:
            return (
                f"{self.args.prompt}\n\n"
                f"Domain: {output_contract.get('domain', 'general')}. "
                f"Task type: {output_contract.get('task_type', 'data_collection')}. "
                "Use these planned dataset columns whenever possible: "
                f"{', '.join(planned_columns)}."
            )
        return build_planned_extraction_prompt(question, planned_columns, output_contract)

    def _collect_pages(
        self,
        search_results: list[dict[str, Any]],
        extraction_prompt: str,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        page_results: list[dict[str, Any]] = []
        raw_records: list[dict[str, Any]] = []

        for search_result in search_results:
            url = search_result["url"]
            try:
                result = collect_with_agentql(
                    url,
                    prompt=extraction_prompt,
                    api_key=self.args.api_key,
                    timeout=self.args.timeout,
                    wait_for=self.args.wait_for,
                    scroll_to_bottom=self.args.scroll_to_bottom,
                    mode=self.args.mode,
                )
                page_records = collect_records_from_response(result)
                raw_records.extend(self._attach_source_metadata(page_records, search_result))
                page_results.append(
                    {
                        "search_result": search_result,
                        "status": "ok",
                        "record_count": len(page_records),
                        "agentql_response": result,
                    }
                )
            except Exception as exc:
                # One failed source should not fail the whole research job.
                page_results.append(
                    {
                        "search_result": search_result,
                        "status": "error",
                        "error": str(exc),
                    }
                )

        return page_results, raw_records

    @staticmethod
    def _attach_source_metadata(
        page_records: list[dict[str, Any]],
        search_result: dict[str, Any],
    ) -> list[dict[str, Any]]:
        return [
            {
                **record,
                "_source_title": search_result.get("title", ""),
                "_source_url": search_result.get("url", ""),
                "_source_snippet": search_result.get("snippet", ""),
            }
            for record in page_records
        ]

    @staticmethod
    def _fallback_records(
        raw_records: list[dict[str, Any]],
        search_results: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if raw_records:
            return raw_records
        return [
            {
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "snippet": item.get("snippet", ""),
                "position": item.get("position", ""),
                "source": item.get("source", ""),
            }
            for item in search_results
        ]


def run_collection(args: argparse.Namespace) -> dict[str, Path]:
    """Backward-compatible wrapper for URL collection mode."""
    return DataCollectorVisualizerPipeline(args).run_url_collection()


def run_auto_research(args: argparse.Namespace) -> dict[str, Path]:
    """Backward-compatible wrapper for auto research mode."""
    return DataCollectorVisualizerPipeline(args).run_auto_research()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Research, collect web data, and generate JSON, CSV, answer, and chart outputs."
    )
    parser.add_argument("--url", help="Public web page URL to extract from.")
    parser.add_argument(
        "--research",
        help="Research question. If used without --url, SerpAPI finds pages automatically.",
    )
    parser.add_argument("--query", help="AgentQL query to run.")
    parser.add_argument("--prompt", help="Natural language data extraction prompt.")
    parser.add_argument(
        "--columns",
        help="Comma-separated output columns. If omitted, columns are planned from the question.",
    )
    parser.add_argument(
        "--no-column-generator",
        action="store_true",
        help="Disable LLM-generated column planning and use local fallback rules.",
    )
    parser.add_argument("--api-key", help="AgentQL API key. Prefer AGENTQL_API_KEY env var.")
    parser.add_argument("--serpapi-key", help="SerpAPI key. Prefer SERPAPI_API_KEY env var.")
    parser.add_argument(
        "--search-results",
        type=int,
        default=3,
        help="Number of SerpAPI results to research when no URL is provided.",
    )
    parser.add_argument(
        "--max-records",
        type=int,
        default=100,
        help="Maximum records to keep for normalization, reporting, and chart planning.",
    )
    parser.add_argument(
        "--task-type",
        default="auto",
        help="Optional task hint, for example comparison, trend_analysis, ranking, or risk_analysis.",
    )
    parser.add_argument(
        "--chart",
        dest="chart",
        action="store_true",
        default=True,
        help="Generate a chart image. Enabled by default for production agent use.",
    )
    parser.add_argument(
        "--no-chart",
        dest="chart",
        action="store_false",
        help="Disable chart generation for this run.",
    )
    parser.add_argument(
        "--chart-engine",
        choices=["llm", "llm_code", "fixed"],
        default="llm_code",
        help=(
            "Chart renderer: llm plans a chart spec from final data; "
            "llm_code generates validated Python chart code for evaluation; "
            "fixed uses deterministic Matplotlib."
        ),
    )
    parser.add_argument("--output-dir", default="output", help="Folder for generated files.")
    parser.add_argument("--name", help="Base output filename without extension.")
    parser.add_argument("--title", default="AgentQL Data Collection", help="Output title used in generated artifacts.")
    parser.add_argument("--timeout", type=int, default=900, help="AgentQL timeout in seconds.")
    parser.add_argument("--wait-for", type=int, default=0, help="Seconds to wait before extracting.")
    parser.add_argument(
        "--scroll-to-bottom",
        action="store_true",
        help="Scroll to page bottom before extracting.",
    )
    parser.add_argument(
        "--mode",
        choices=["fast", "standard"],
        default="fast",
        help="AgentQL extraction mode.",
    )
    return parser


def fill_interactive_args(args: argparse.Namespace) -> argparse.Namespace:
    """Ask simple questions when the script is run without enough CLI input."""
    if not args.url and not args.research:
        print("Press Enter at Website URL to let SerpAPI search automatically.")
        args.url = input("Website URL: ").strip()

    if not args.url and not args.research:
        args.research = input("Research question: ").strip()

    if args.url and not args.query and not args.prompt:
        print("Ask what data you want to collect.")
        print("Example: get all blog posts with title, url, date, and author")
        question = input("Question: ").strip()
        args.prompt = question

    if args.research and not args.prompt:
        args.prompt = None

    if not args.name:
        custom_name = input("Output file name without extension, or press Enter: ").strip()
        if custom_name:
            args.name = custom_name

    return args


def main() -> None:
    load_dotenv_if_available()

    parser = build_parser()
    args = parser.parse_args()

    args = fill_interactive_args(args)

    if not args.url and not args.research:
        parser.error("Provide --url or --research, or enter a research question.")

    if args.url and not args.query and not args.prompt:
        parser.error("Provide either --query or --prompt.")

    paths = DataCollectorVisualizerPipeline(args).run()

    print("Data collection complete.")
    print(f"JSON: {paths['json']}")
    print(f"CSV:  {paths['csv']}")
    print(f"Log:  {paths['log']}")
    if "answer" in paths:
        print(f"Answer: {paths['answer']}")
    if "chart" in paths:
        print(f"Chart: {paths['chart']}")


if __name__ == "__main__":
    main()
