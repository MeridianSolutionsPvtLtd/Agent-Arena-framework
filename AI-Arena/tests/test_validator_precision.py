"""Focused tests for Validator Evidence inclusion and grounding precision."""

import json
from unittest.mock import MagicMock, patch
import pytest
from core.orchestration.executor_nodes.validator import validation_node, _get_precision_instructions


def test_validator_includes_step_outputs_evidence_in_llm_prompt():
    state = {
        "query": "Find the revenue for Q3",
        "plan": "Step 1: Extract financial report",
        "structured_plan": [{"step": 1, "task": "Extract report", "tool": "extract_data_from_file"}],
        "crew_output": "Q3 Revenue was $5.2 Million.",
        "retry_count": 0,
        "loop_guard_count": 0,
        "step_outputs": [
            {
                "step": 1,
                "task": "Extract report",
                "role": "Financial Analyst",
                "output": "Financial Statement Q3: Revenue $5.2M, Expenses $3.1M.",
            }
        ],
    }

    mock_llm_response = json.dumps({
        "is_aligned": True,
        "alignment_score": 0.95,
        "missing_elements": [],
        "issues": [],
        "checklist_results": {},
        "feedback": "Great work."
    })

    with patch("core.orchestration.executor_nodes.validator._get_crewai_llm") as mock_get_llm:
        mock_llm_instance = MagicMock()
        mock_llm_instance.call.return_value = mock_llm_response
        mock_get_llm.return_value = mock_llm_instance

        result = validation_node(state)

        assert result["is_factual"] is True
        assert mock_llm_instance.call.called
        prompt_sent = mock_get_llm.return_value.call.call_args[0][0][0]["content"]

        assert "RETRIEVED TOOL EVIDENCE (Source of Truth):" in prompt_sent
        assert "Step 1 (Extract report):" in prompt_sent
        assert "Revenue $5.2M" in prompt_sent


def test_validator_detects_unsupported_factual_claim():
    state = {
        "query": "What was the Q3 profit?",
        "plan": "Step 1: Check report",
        "structured_plan": [{"step": 1, "task": "Check report", "tool": "extract_data_from_file"}],
        "crew_output": "Q3 Profit was $999 Million (completely unsupported claim).",
        "retry_count": 0,
        "loop_guard_count": 0,
        "step_outputs": [
            {
                "step": 1,
                "task": "Check report",
                "role": "Analyst",
                "output": "Q3 Profit: $12.5M",
            }
        ],
        "agent_config": {"validator_config": {"min_score": 0.7}},
    }

    mock_rejection = json.dumps({
        "is_aligned": False,
        "alignment_score": 0.2,
        "missing_elements": [],
        "issues": ["Profit $999M contradicts tool evidence of $12.5M"],
        "checklist_results": {},
        "feedback": "Correct the profit number to match retrieved evidence."
    })

    with patch("core.orchestration.executor_nodes.validator._get_crewai_llm") as mock_get_llm:
        mock_llm_instance = MagicMock()
        mock_llm_instance.call.return_value = mock_rejection
        mock_get_llm.return_value = mock_llm_instance

        result = validation_node(state)

        assert result["error"] == "RETRY_REQUIRED"
        assert result["is_factual"] is False
        assert "Correct the profit number" in result["validation_feedback"]


def test_validator_evidence_is_bounded_and_truncated():
    huge_tool_output = "X" * 5000
    state = {
        "query": "Analyze data",
        "plan": "Step 1: Extract data",
        "structured_plan": [{"step": 1, "task": "Extract data", "tool": "extract_data_from_file"}],
        "crew_output": "Analysis complete.",
        "retry_count": 0,
        "loop_guard_count": 0,
        "step_outputs": [
            {
                "step": 1,
                "task": "Extract data",
                "role": "Analyst",
                "output": huge_tool_output,
            }
        ],
    }

    mock_pass = json.dumps({
        "is_aligned": True,
        "alignment_score": 0.9,
        "missing_elements": [],
        "issues": [],
        "checklist_results": {},
        "feedback": "OK"
    })

    with patch("core.orchestration.executor_nodes.validator._get_crewai_llm") as mock_get_llm:
        mock_llm_instance = MagicMock()
        mock_llm_instance.call.return_value = mock_pass
        mock_get_llm.return_value = mock_llm_instance

        validation_node(state)

        prompt_sent = mock_get_llm.return_value.call.call_args[0][0][0]["content"]
        assert "[truncated]" in prompt_sent
        # Confirm prompt doesn't contain the full 5000 X's
        assert "X" * 1500 not in prompt_sent


def test_validator_falls_back_to_blackboard_when_step_outputs_missing():
    state = {
        "query": "Check order status",
        "plan": "Step 1: Fetch status",
        "structured_plan": [{"step": 1, "task": "Fetch status", "tool": "web_search"}],
        "crew_output": "Order status is Shipped.",
        "retry_count": 0,
        "loop_guard_count": 0,
        "blackboard": {"order_status_key": "Order #441 status: Shipped via FedEx"},
    }

    mock_pass = json.dumps({
        "is_aligned": True,
        "alignment_score": 0.9,
        "missing_elements": [],
        "issues": [],
        "checklist_results": {},
        "feedback": "OK"
    })

    with patch("core.orchestration.executor_nodes.validator._get_crewai_llm") as mock_get_llm:
        mock_llm_instance = MagicMock()
        mock_llm_instance.call.return_value = mock_pass
        mock_get_llm.return_value = mock_llm_instance

        validation_node(state)

        prompt_sent = mock_get_llm.return_value.call.call_args[0][0][0]["content"]
        assert "RETRIEVED TOOL EVIDENCE (Source of Truth):" in prompt_sent
        assert "[order_status_key]: Order #441 status: Shipped via FedEx" in prompt_sent


def test_validator_audits_retry_count_1_valid_response_passes():
    state = {
        "query": "Generate report",
        "plan": "Step 1: Generate report",
        "structured_plan": [{"step": 1, "task": "Generate report", "tool": "generate_report"}],
        "crew_output": "Report generated successfully with verified data.",
        "retry_count": 1,
        "loop_guard_count": 1,
        "step_outputs": [{"step": 1, "task": "Generate report", "output": "Report Data verified"}],
    }

    mock_pass = json.dumps({
        "is_aligned": True,
        "alignment_score": 0.92,
        "missing_elements": [],
        "issues": [],
        "checklist_results": {},
        "feedback": "Corrected successfully."
    })

    with patch("core.orchestration.executor_nodes.validator._get_crewai_llm") as mock_get_llm:
        mock_llm_instance = MagicMock()
        mock_llm_instance.call.return_value = mock_pass
        mock_get_llm.return_value = mock_llm_instance

        result = validation_node(state)

        assert mock_llm_instance.call.called
        assert result["is_factual"] is True
        assert result.get("error") == ""


def test_validator_audits_retry_count_1_invalid_response_records_failure():
    state = {
        "query": "Generate report",
        "plan": "Step 1: Generate report",
        "structured_plan": [{"step": 1, "task": "Generate report", "tool": "generate_report"}],
        "crew_output": "Still missing required vendor list.",
        "retry_count": 1,
        "loop_guard_count": 1,
        "step_outputs": [{"step": 1, "task": "Generate report", "output": "Incomplete"}],
    }

    mock_fail = json.dumps({
        "is_aligned": False,
        "alignment_score": 0.3,
        "missing_elements": ["Vendor list missing"],
        "issues": ["Report incomplete on retry"],
        "checklist_results": {},
        "feedback": "Include vendor list."
    })

    with patch("core.orchestration.executor_nodes.validator._get_crewai_llm") as mock_get_llm:
        mock_llm_instance = MagicMock()
        mock_llm_instance.call.return_value = mock_fail
        mock_get_llm.return_value = mock_llm_instance

        result = validation_node(state)

        assert mock_llm_instance.call.called
        assert result["is_factual"] is False
        assert result["error"] == "RETRY_REQUIRED"
        assert result["retry_count"] == 2
        assert result["loop_guard_count"] == 2


def test_validator_skips_when_retry_count_reaches_2():
    state = {
        "query": "Generate report",
        "plan": "Step 1: Generate report",
        "structured_plan": [{"step": 1, "task": "Generate report", "tool": "generate_report"}],
        "crew_output": "Any response",
        "retry_count": 2,
        "loop_guard_count": 2,
    }

    with patch("core.orchestration.executor_nodes.validator._get_crewai_llm") as mock_get_llm:
        result = validation_node(state)

        assert not mock_get_llm.called
        assert result["is_factual"] is True


# ─────────────────────────────────────────────────────────────────────────────
# Phase 2: Validator Precision – _get_precision_instructions unit tests
# ─────────────────────────────────────────────────────────────────────────────


def test_precision_helper_returns_lenient_for_low_min_score():
    """min_score 0.2 (20%) must produce LENIENT instructions."""
    instructions = _get_precision_instructions(0.2)
    assert "LENIENT (Tolerant Review)" in instructions
    assert "STANDARD" not in instructions
    assert "STRICT" not in instructions


def test_precision_helper_returns_standard_for_moderate_min_score():
    """min_score 0.6 (60%) must produce STANDARD instructions."""
    instructions = _get_precision_instructions(0.6)
    assert "STANDARD (Balanced Review)" in instructions
    assert "LENIENT" not in instructions
    assert "STRICT" not in instructions


def test_precision_helper_returns_strict_for_high_min_score():
    """min_score 0.8 (80%) must produce STRICT instructions."""
    instructions = _get_precision_instructions(0.8)
    assert "STRICT (High-Precision Audit)" in instructions
    assert "LENIENT" not in instructions
    assert "VERY STRICT" not in instructions


def test_precision_helper_returns_very_strict_for_max_min_score():
    """min_score 1.0 (100%) must produce VERY STRICT instructions."""
    instructions = _get_precision_instructions(1.0)
    assert "VERY STRICT (Zero-Tolerance Audit)" in instructions
    assert "LENIENT" not in instructions


def test_validator_prompt_contains_precision_band_and_band_persists_on_retry():
    """
    Integration test: the precision instructions must appear in the prompt
    that validation_node sends to the LLM, and must remain consistent even
    when called again at retry_count=1 / loop_guard_count=1 (re-validation).
    """
    base_state = {
        "query": "Generate a procurement report",
        "plan": "Step 1: Fetch data",
        "structured_plan": [{"step": 1, "task": "Fetch data", "tool": "extract_data_from_file"}],
        "crew_output": "Report complete with procurement summary.",
        "step_outputs": [{"step": 1, "task": "Fetch data", "output": "Procurement data: $5000 PO #123"}],
        "agent_config": {"validator_config": {"min_score": 0.9}},
    }

    mock_pass = json.dumps({
        "is_aligned": True,
        "alignment_score": 0.95,
        "missing_elements": [],
        "issues": [],
        "checklist_results": {},
        "feedback": "Good work.",
    })

    # ── First call (initial validation) ──
    state_initial = {**base_state, "retry_count": 0, "loop_guard_count": 0}
    with patch("core.orchestration.executor_nodes.validator._get_crewai_llm") as mock_get_llm:
        mock_llm_instance = MagicMock()
        mock_llm_instance.call.return_value = mock_pass
        mock_get_llm.return_value = mock_llm_instance

        result = validation_node(state_initial)

        assert result["is_factual"] is True
        prompt_sent = mock_llm_instance.call.call_args[0][0][0]["content"]
        # 0.9 falls in the VERY STRICT band
        assert "VERY STRICT (Zero-Tolerance Audit)" in prompt_sent
        assert "LENIENT" not in prompt_sent

    # ── Second call (re-validation after first retry) ──
    state_retry = {**base_state, "retry_count": 1, "loop_guard_count": 1}
    with patch("core.orchestration.executor_nodes.validator._get_crewai_llm") as mock_get_llm2:
        mock_llm_instance2 = MagicMock()
        mock_llm_instance2.call.return_value = mock_pass
        mock_get_llm2.return_value = mock_llm_instance2

        result2 = validation_node(state_retry)

        assert result2["is_factual"] is True
        prompt_sent2 = mock_llm_instance2.call.call_args[0][0][0]["content"]
        # Precision level must be identical on re-validation
        assert "VERY STRICT (Zero-Tolerance Audit)" in prompt_sent2


# ─────────────────────────────────────────────────────────────────────────────
# Phase 3: Validator Precision – exact boundary-value tests
# ─────────────────────────────────────────────────────────────────────────────

import pytest  # already imported above; repeated import is harmless but we keep it explicit here

@pytest.mark.parametrize("min_score,expected_band,absent_bands", [
    # LENIENT band boundaries
    (0.10, "LENIENT (Tolerant Review)",          ["STANDARD", "STRICT (High-Precision", "VERY STRICT"]),
    (0.35, "LENIENT (Tolerant Review)",          ["STANDARD", "STRICT (High-Precision", "VERY STRICT"]),
    # STANDARD band boundaries
    (0.36, "STANDARD (Balanced Review)",         ["LENIENT", "STRICT (High-Precision", "VERY STRICT"]),
    (0.65, "STANDARD (Balanced Review)",         ["LENIENT", "STRICT (High-Precision", "VERY STRICT"]),
    # STRICT band boundaries
    (0.66, "STRICT (High-Precision Audit)",      ["LENIENT", "STANDARD", "VERY STRICT"]),
    (0.85, "STRICT (High-Precision Audit)",      ["LENIENT", "STANDARD", "VERY STRICT"]),
    # VERY STRICT band boundaries
    (0.86, "VERY STRICT (Zero-Tolerance Audit)", ["LENIENT", "STANDARD", "STRICT (High-Precision"]),
    (1.00, "VERY STRICT (Zero-Tolerance Audit)", ["LENIENT", "STANDARD", "STRICT (High-Precision"]),
])
def test_precision_boundary_values(min_score, expected_band, absent_bands):
    """
    Phase 3 boundary test: each exact boundary value must resolve to the
    correct precision band and must NOT contain any other band's label.
    Production code (validator.py) is NOT modified by this test.
    """
    instructions = _get_precision_instructions(min_score)
    assert expected_band in instructions, (
        f"min_score={min_score}: expected band '{expected_band}' not found in:\n{instructions}"
    )
    for absent in absent_bands:
        assert absent not in instructions, (
            f"min_score={min_score}: unexpected band fragment '{absent}' found in:\n{instructions}"
        )
