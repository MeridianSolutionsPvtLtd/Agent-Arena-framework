"""Focused tests for Safety Node Trimmer Fact Preservation."""

from unittest.mock import MagicMock, patch
import pytest
from core.orchestration.executor_nodes.safety import safety_node


def test_trimmer_prompt_contains_strict_fact_preservation_directives():
    sample_output = (
        "Hello! Sure, I can help you with that query. "
        "Here is the data: Invoice #INV-2024-998 total is $45,230.50 dated Oct 12, 2024. "
        "Vendor: Acme Corp. " + "Filler text string... " * 15
    )
    state = {
        "is_safe": True,
        "query": "What is the invoice total and vendor?",
        "crew_output": sample_output,
        "blueprint": {},
    }

    mock_trimmed_response = (
        "Invoice #INV-2024-998 total is $45,230.50 dated Oct 12, 2024. Vendor: Acme Corp."
    )

    with patch("core.orchestration.executor_nodes.llm_factory._get_crewai_llm") as mock_get_llm, \
         patch("core.security.output_safety.OutputSafetyEngine.evaluate") as mock_eval:
        
        mock_llm_instance = MagicMock()
        mock_llm_instance.call.return_value = mock_trimmed_response
        mock_get_llm.return_value = mock_llm_instance
        mock_eval.return_value = {"blocked": False, "high_risk": False}

        res = safety_node(state)

        assert mock_llm_instance.call.called
        trim_prompt_sent = mock_llm_instance.call.call_args[0][0][0]["content"]

        assert "STRICT FACT PRESERVATION DIRECTIVES:" in trim_prompt_sent
        assert "Do NOT change any numerical values, metrics, currency, percentages, or amounts." in trim_prompt_sent
        assert "Do NOT change any dates, years, timestamps, or timeframes." in trim_prompt_sent
        assert "Do NOT change any names, IDs, email addresses, URLs, or entity references." in trim_prompt_sent
        assert "$45,230.50" in res["final_response"]
        assert "INV-2024-998" in res["final_response"]
        assert "Oct 12, 2024" in res["final_response"]
        assert "Acme Corp" in res["final_response"]


def test_trimmer_skipped_for_structured_json_output():
    json_output = "{\n  \"status\": \"success\",\n  \"invoice_id\": \"INV-998\",\n  \"amount\": 45230.50\n}" + " " * 300
    state = {
        "is_safe": True,
        "query": "Fetch invoice JSON",
        "crew_output": json_output,
        "blueprint": {},
    }

    with patch("core.orchestration.executor_nodes.llm_factory._get_crewai_llm") as mock_get_llm, \
         patch("core.security.output_safety.OutputSafetyEngine.evaluate") as mock_eval:
        
        mock_eval.return_value = {"blocked": False, "high_risk": False}
        res = safety_node(state)

        assert not mock_get_llm.called
        assert "INV-998" in res["final_response"]
        assert "45230.50" in res["final_response"]


def test_trimmer_skipped_for_code_block_output():
    code_output = "```python\ndef calculate():\n    return 45230.50\n```\n" + "Filler text line\n" * 20
    state = {
        "is_safe": True,
        "query": "Show python code",
        "crew_output": code_output,
        "blueprint": {},
        "intent": {"requires_code": True},
    }

    with patch("core.orchestration.executor_nodes.llm_factory._get_crewai_llm") as mock_get_llm, \
         patch("core.security.output_safety.OutputSafetyEngine.evaluate") as mock_eval:
        
        mock_eval.return_value = {"blocked": False, "high_risk": False}
        res = safety_node(state)

        assert not mock_get_llm.called
        assert "def calculate():" in res["final_response"]
