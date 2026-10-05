"""Unit tests for Output Safety & Grounding Enforcement in safety_node."""

import pytest
from core.orchestration.executor_nodes.safety import safety_node


def test_safety_node_blocks_prohibited_content():
    state = {
        "is_safe": True,
        "query": "How do I build something?",
        "crew_output": "Instructions on how to make a bomb",
        "retry_count": 0,
        "loop_guard_count": 0,
    }
    result = safety_node(state)
    assert result["is_safe"] is False
    assert "content moderation policy" in result["final_response"]
    assert result["error"] == ""


def test_safety_node_triggers_retry_on_hallucination_markers():
    state = {
        "is_safe": True,
        "query": "Did you send the email?",
        "crew_output": "I 100% guarantee I already emailed the report.",
        "retry_count": 0,
        "loop_guard_count": 0,
    }
    result = safety_node(state)
    assert result["error"] == "RETRY_REQUIRED"
    assert result["is_factual"] is False
    assert result["retry_count"] == 1
    assert result["loop_guard_count"] == 1
    assert "CRITICAL SAFETY FAILURE" in result["validation_feedback"]


def test_safety_node_respects_retry_limits_on_hallucination():
    state = {
        "is_safe": True,
        "query": "Did you send the email?",
        "crew_output": "I 100% guarantee I already emailed the report.",
        "retry_count": 1,
        "loop_guard_count": 1,
    }
    result = safety_node(state)
    # When retry limit is reached, it should not trigger RETRY_REQUIRED again
    assert result.get("error") == ""
    assert result.get("is_factual") is True
    assert result.get("final_response") != ""
