"""Manual terminal trace for the governed web_search implementation.

Usage:
    .venv/Scripts/python.exe scripts/web_search_trace.py "latest electric vehicle developments"

This calls the tool directly. It does not create an agent thread, write MongoDB,
or invoke summarization/report generation.
"""

from __future__ import annotations

import json
import logging
import pathlib
import sys
import time

# Allow direct execution from PowerShell without requiring PYTHONPATH.
PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from core.tools.web_search import web_search


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s - %(message)s",
)
logger = logging.getLogger("web_search_trace")


def main() -> int:
    query = " ".join(sys.argv[1:]).strip()
    if not query:
        print("Usage: python scripts/web_search_trace.py \"your search question\"")
        return 2

    logger.info("User question: %s", query)
    started = time.perf_counter()
    raw = web_search._run(query=query, action="search", max_results=5, strict_mode=True)
    elapsed = time.perf_counter() - started

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        logger.error("Tool returned non-JSON output: %s", raw[:500])
        return 1

    results = payload.get("results") or []
    logger.info("Provider: %s", payload.get("provider", "unknown"))
    logger.info("Final provider query: %s", payload.get("query", ""))
    logger.info("Result count: %d", len(results))
    logger.info("Elapsed seconds: %.2f", elapsed)

    for index, result in enumerate(results, start=1):
        logger.info(
            "Result %d | title=%r | url=%s | preview_chars=%d | content_chars=%d",
            index,
            result.get("title", ""),
            result.get("url", ""),
            len(result.get("content_preview") or ""),
            len(result.get("content") or ""),
        )

    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0 if payload.get("error") is None else 1


if __name__ == "__main__":
    raise SystemExit(main())
