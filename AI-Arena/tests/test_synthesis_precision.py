"""Focused tests for Synthesizer Precision and Empty Tool Data Handling."""

import json
from unittest.mock import MagicMock, patch
import pytest
from core.orchestration.executor_nodes.execution import _synthesize_final_answer


def test_synthesizer_empty_search_result_instructs_not_found():
    query = "Find 2026 tax form for XYZ Corp"
    step_outputs = [
        {
            "step": 1,
            "task": "Search 2026 tax form for XYZ Corp",
            "role": "Search Specialist",
            "output": json.dumps({"query": "2026 tax form XYZ Corp", "results": []}),
        }
    ]

    mock_llm_response = (
        "I could not find the 2026 tax form for XYZ Corp in the available web search sources."
    )

    with patch("litellm.completion") as mock_completion:
        mock_res = MagicMock()
        mock_res.choices[0].message.content = mock_llm_response
        mock_completion.return_value = mock_res

        result = _synthesize_final_answer(query, step_outputs)

        assert mock_completion.called
        prompt_sent = mock_completion.call_args[1]["messages"][0]["content"]

        assert "NO DATA HALLUCINATION FOR EMPTY TOOL RESULTS:" in prompt_sent
        assert "could not find the 2026 tax form" in result.lower()


def test_synthesizer_empty_file_extraction_does_not_invent_facts():
    query = "Summarize the attached quarterly report"
    step_outputs = [
        {
            "step": 1,
            "task": "Extract data from report.pdf",
            "role": "Document Reader",
            "output": "File Type: PDF, Text Preview: [empty document]",
        }
    ]

    mock_llm_response = (
        "The attached document report.pdf appears to be empty, so no quarterly report data could be extracted."
    )

    with patch("litellm.completion") as mock_completion:
        mock_res = MagicMock()
        mock_res.choices[0].message.content = mock_llm_response
        mock_completion.return_value = mock_res

        result = _synthesize_final_answer(query, step_outputs)

        assert mock_completion.called
        prompt_sent = mock_completion.call_args[1]["messages"][0]["content"]

        assert "NO DATA HALLUCINATION FOR EMPTY TOOL RESULTS:" in prompt_sent
        assert "empty" in result.lower() or "not" in result.lower()


def test_synthesizer_tool_failure_preserves_failure_handling():
    query = "Run security audit"
    step_outputs = [
        {
            "step": 1,
            "task": "Execute Pre-Flight Safety Check",
            "role": "Security Specialist",
            "output": "[Error: Pre-Flight Safety Check Failed: Unauthorized endpoint]",
        }
    ]

    mock_llm_response = (
        "❌ **Task Failed**: Pre-Flight Safety Check Failed due to an unauthorized endpoint."
    )

    with patch("litellm.completion") as mock_completion:
        mock_res = MagicMock()
        mock_res.choices[0].message.content = mock_llm_response
        mock_completion.return_value = mock_res

        result = _synthesize_final_answer(query, step_outputs)

        assert mock_completion.called
        prompt_sent = mock_completion.call_args[1]["messages"][0]["content"]

        assert "NO COVER-UPS:" in prompt_sent
        assert "Failed" in result or "failed" in result


def test_synthesizer_useful_tool_result_uses_evidence_normally():
    query = "Find Apple Q3 revenue"
    step_outputs = [
        {
            "step": 1,
            "task": "Search Apple Q3 revenue",
            "role": "Researcher",
            "output": json.dumps({
                "results": [{"title": "Apple Earnings", "url": "https://apple.com/news", "snippet": "Apple Q3 revenue was $85.8 Billion."}]
            }),
        }
    ]

    mock_llm_response = "Apple Q3 revenue reached $85.8 Billion according to company earnings."

    with patch("litellm.completion") as mock_completion:
        mock_res = MagicMock()
        mock_res.choices[0].message.content = mock_llm_response
        mock_completion.return_value = mock_res

        result = _synthesize_final_answer(query, step_outputs)

        assert "$85.8 Billion" in result


def test_synthesizer_mixed_tool_results_uses_available_useful_data():
    query = "Get company profile and 2030 predictions"
    step_outputs = [
        {
            "step": 1,
            "task": "Search company profile",
            "role": "Researcher",
            "output": "Acme Corp founded in 1995 with 500 employees.",
        },
        {
            "step": 2,
            "task": "Search 2030 predictions",
            "role": "Future Analyst",
            "output": json.dumps({"results": []}),
        },
    ]

    mock_llm_response = (
        "Acme Corp was founded in 1995 and has 500 employees. "
        "However, no predictions for 2030 were found in the available search data."
    )

    with patch("litellm.completion") as mock_completion:
        mock_res = MagicMock()
        mock_res.choices[0].message.content = mock_llm_response
        mock_completion.return_value = mock_res

        result = _synthesize_final_answer(query, step_outputs)

        assert "Acme Corp" in result
        assert "no predictions" in result.lower() or "not found" in result.lower()
