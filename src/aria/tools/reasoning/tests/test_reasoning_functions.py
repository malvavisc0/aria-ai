"""Tests for reasoning functions with persistence and multi-agent support."""

import json

import pytest

from aria.tools.reasoning import reasoning, registry
from aria.tools.reasoning.database import ReasoningDatabase
from aria.tools.scratchpad import scratchpad


@pytest.fixture
def test_agent_id():
    """Provide a test agent ID."""
    return "test_agent_123"


@pytest.fixture(autouse=True)
def test_db(test_tools_db):
    """Create a temporary reasoning database for testing.

    Depends on the shared ``test_tools_db`` fixture (defined in root
    ``conftest.py``) which handles temp-file creation and singleton
    resets.
    """
    test_reasoning_db = ReasoningDatabase()

    yield test_reasoning_db

    registry.clear_all()


def _result(call_result: str) -> dict:
    """Parse tool JSON-string response into a dict for assertions."""
    return json.loads(call_result)


def test_start_reasoning(test_agent_id, test_db):
    """Test starting a new reasoning session."""
    result = _result(
        reasoning("Testing reason", action="start", agent_id=test_agent_id)
    )
    assert result["status"] == "success"
    assert result["tool"] == "reasoning"
    assert result["reason"] == "Testing reason"
    assert result["agent_id"] == test_agent_id
    assert result["session_id"].startswith(f"{test_agent_id}_session_")
    assert result["data"]["action"] == "start"

    # Verify active session was created
    assert test_agent_id in registry.get_active_session_id(test_agent_id)

    # Clean up
    reasoning("Testing reason", action="end", agent_id=test_agent_id)


def test_start_reasoning_replaces_previous(test_agent_id, test_db):
    """Test that starting new session replaces previous one."""
    # Start first session
    reasoning("First analysis", action="start", agent_id=test_agent_id)
    reasoning(
        "First analysis",
        action="step",
        content="Step 1",
        agent_id=test_agent_id,
    )

    # Start second session (should replace first)
    reasoning("Second analysis", action="start", agent_id=test_agent_id)

    # Summary should show empty session (new one)
    summary = _result(reasoning("Check", action="summary", agent_id=test_agent_id))
    assert summary["status"] == "success"
    assert summary["data"]["steps_count"] == 0

    # Clean up
    reasoning("Testing reason", action="end", agent_id=test_agent_id)


def test_add_step_without_session(test_agent_id, test_db):
    """Test that adding a step without starting session raises error."""
    result = _result(
        reasoning(
            "Testing reason",
            action="step",
            content="Test step",
            agent_id=test_agent_id,
        )
    )

    assert result["status"] == "error"
    assert result["error"]["code"] == "NO_ACTIVE_SESSION"


def test_add_step_with_session(test_agent_id, test_db):
    """Test adding a step after starting session."""
    reasoning("Testing reason", action="start", agent_id=test_agent_id)
    result = _result(
        reasoning(
            "Testing reason",
            action="step",
            content="Analyzing the problem",
            agent_id=test_agent_id,
            cognitive_mode="analysis",
        )
    )

    assert result["status"] == "success"
    assert result["tool"] == "reasoning"
    assert result["data"]["step_id"] == 1
    assert result["data"]["content"] == "Analyzing the problem"
    assert result["data"]["action"] == "step"

    # Clean up
    reasoning("Testing reason", action="end", agent_id=test_agent_id)


def test_add_reflection_without_session(test_agent_id, test_db):
    """Test that adding reflection without session raises error."""
    result = _result(
        reasoning(
            "Testing reason",
            action="reflect",
            content="Test reflection",
            agent_id=test_agent_id,
        )
    )

    assert result["status"] == "error"
    assert result["error"]["code"] == "NO_ACTIVE_SESSION"


def test_add_reflection_with_session(test_agent_id, test_db):
    """Test adding reflection after starting session."""
    reasoning("Testing reason", action="start", agent_id=test_agent_id)
    result = _result(
        reasoning(
            "Testing reason",
            action="reflect",
            content="Need to verify assumptions",
            agent_id=test_agent_id,
        )
    )

    assert result["status"] == "success"
    assert result["tool"] == "reasoning"
    assert result["data"]["reflection_id"] == 1
    assert result["data"]["action"] == "reflect"

    # Clean up
    reasoning("Testing reason", action="end", agent_id=test_agent_id)


def test_scratchpad_with_session(test_agent_id, test_db):
    """Test using scratchpad after starting session."""
    reasoning("Testing reasoning", action="start", agent_id=test_agent_id)

    # Set a value
    result = _result(
        scratchpad(
            "Testing reason",
            "key1",
            agent_id=test_agent_id,
            value="value1",
            operation="set",
        )
    )
    assert result["status"] == "success"
    assert result["data"]["tool"] == "set"
    assert result["data"]["key"] == "key1"
    assert result["data"]["value"] == "value1"

    # Get the value
    result = _result(
        scratchpad(
            "Testing reason",
            "key1",
            agent_id=test_agent_id,
            operation="get",
        )
    )
    assert result["status"] == "success"
    assert result["data"]["tool"] == "get"
    assert result["data"]["value"] == "value1"

    # Clean up
    reasoning("Testing reason", action="end", agent_id=test_agent_id)


def test_evaluate_without_session(test_agent_id, test_db):
    """Test that evaluating without session raises error."""
    result = _result(
        reasoning("Testing reason", action="evaluate", agent_id=test_agent_id)
    )
    assert result["status"] == "error"
    assert result["error"]["code"] == "NO_ACTIVE_SESSION"


def test_evaluate_with_session(test_agent_id, test_db):
    """Test evaluating after starting session."""
    reasoning("Testing reason", action="start", agent_id=test_agent_id)
    reasoning(
        "Testing reason",
        action="step",
        content="Step 1",
        agent_id=test_agent_id,
    )

    result = _result(
        reasoning("Testing reason", action="evaluate", agent_id=test_agent_id)
    )
    assert result["status"] == "success"
    assert result["tool"] == "reasoning"
    assert result["data"]["steps_count"] == 1
    assert result["data"]["action"] == "evaluate"

    # Clean up
    reasoning("Testing reason", action="end", agent_id=test_agent_id)


def test_summary_without_session(test_agent_id, test_db):
    """Test that getting summary without session raises error."""
    result = _result(
        reasoning("Testing reason", action="summary", agent_id=test_agent_id)
    )
    assert result["status"] == "error"
    assert result["error"]["code"] == "NO_ACTIVE_SESSION"


def test_summary_with_session(test_agent_id, test_db):
    """Test getting summary after starting session."""
    reasoning("Testing reason", action="start", agent_id=test_agent_id)
    reasoning(
        "Testing reason",
        action="step",
        content="Step 1",
        agent_id=test_agent_id,
    )

    result = _result(
        reasoning("Testing reason", action="summary", agent_id=test_agent_id)
    )
    assert result["status"] == "success"
    assert result["data"]["steps_count"] == 1
    assert result["data"]["action"] == "summary"

    # Clean up
    reasoning("Testing reason", action="end", agent_id=test_agent_id)


def test_end_reasoning(test_agent_id, test_db):
    """Test ending a session."""
    reasoning("Testing reason", action="start", agent_id=test_agent_id)
    result = _result(reasoning("Testing reason", action="end", agent_id=test_agent_id))
    assert result["status"] == "success"
    assert result["tool"] == "reasoning"
    assert result["data"]["action"] == "end"

    # Verify it's gone from active sessions
    assert registry.get_active_session_id(test_agent_id) is None

    # Verify tools fail now
    result = _result(
        reasoning("Testing reason", action="summary", agent_id=test_agent_id)
    )
    assert result["status"] == "error"
    assert result["error"]["code"] == "NO_ACTIVE_SESSION"


def test_end_nonexistent_session(test_agent_id, test_db):
    """Test ending when no active session exists."""
    result = _result(reasoning("Testing reason", action="end", agent_id=test_agent_id))
    assert result["status"] == "error"
    assert result["error"]["code"] == "NO_ACTIVE_SESSION"


def test_full_workflow(test_agent_id, test_db):
    """Test a complete reasoning workflow."""
    # Start session
    reasoning("Testing reason", action="start", agent_id=test_agent_id)

    # Add steps
    reasoning(
        "Testing reason",
        action="step",
        content="Identified the problem",
        agent_id=test_agent_id,
        cognitive_mode="analysis",
    )
    reasoning(
        "Testing reason",
        action="step",
        content="Formulated hypothesis",
        agent_id=test_agent_id,
        cognitive_mode="synthesis",
    )

    # Add reflection
    reasoning(
        "Testing reason",
        action="reflect",
        content="Should verify assumptions",
        agent_id=test_agent_id,
    )

    # Use scratchpad
    scratchpad(
        "Testing reason",
        "hypothesis",
        agent_id=test_agent_id,
        value="Auth token issue",
        operation="set",
    )

    # Evaluate
    result = _result(
        reasoning("Testing reason", action="evaluate", agent_id=test_agent_id)
    )
    assert result["status"] == "success"
    assert result["data"]["steps_count"] == 2
    assert result["data"]["reflections_count"] == 1

    # Get summary
    summary = _result(
        reasoning("Testing reason", action="summary", agent_id=test_agent_id)
    )
    assert summary["status"] == "success"
    assert summary["data"]["steps_count"] == 2
    assert summary["data"]["reflections_count"] == 1

    # Clean up
    reasoning("Testing reason", action="end", agent_id=test_agent_id)


def test_multi_agent_isolation(test_db):
    """Test that different agents have isolated sessions."""
    agent_1 = "agent_1"
    agent_2 = "agent_2"

    # Both agents start sessions
    reasoning("Testing reason", action="start", agent_id=agent_1)
    reasoning("Testing reason", action="start", agent_id=agent_2)

    # Add different steps
    reasoning(
        "Testing reason",
        action="step",
        content="Agent 1 step",
        agent_id=agent_1,
    )
    reasoning(
        "Testing reason",
        action="step",
        content="Agent 2 step",
        agent_id=agent_2,
    )

    # Verify isolation
    summary_1 = _result(reasoning("Testing reason", action="summary", agent_id=agent_1))
    summary_2 = _result(reasoning("Testing reason", action="summary", agent_id=agent_2))

    # Both should have 1 step
    assert summary_1["data"]["steps_count"] == 1
    assert summary_2["data"]["steps_count"] == 1

    # End one session
    reasoning("Testing reason", action="end", agent_id=agent_1)

    # Agent 2's session should still exist
    summary_2_after = _result(
        reasoning("Testing reason", action="summary", agent_id=agent_2)
    )
    assert summary_2_after["data"]["steps_count"] == 1

    # Agent 1's session should be gone
    result = _result(reasoning("Testing reason", action="summary", agent_id=agent_1))
    assert result["status"] == "error"
    assert result["error"]["code"] == "NO_ACTIVE_SESSION"

    # Clean up remaining session
    reasoning("Testing reason", action="end", agent_id=agent_2)


def test_persistence_across_restart(test_agent_id, test_db):
    """Test that sessions survive cache clearing."""
    # Create and populate session
    reasoning("Testing reason", action="start", agent_id=test_agent_id)
    reasoning(
        "Testing reason",
        action="step",
        content="Step 1",
        agent_id=test_agent_id,
    )
    reasoning(
        "Testing reason",
        action="reflect",
        content="Reflection 1",
        agent_id=test_agent_id,
    )
    scratchpad(
        "Testing reason",
        "key1",
        agent_id=test_agent_id,
        value="value1",
        operation="set",
    )

    # Simulate restart boundary: registry is DB-backed (no in-memory cache)

    # Verify data still accessible (loaded from database)
    summary = _result(
        reasoning("Testing reason", action="summary", agent_id=test_agent_id)
    )
    assert summary["status"] == "success"
    assert summary["data"]["steps_count"] == 1
    assert summary["data"]["reflections_count"] == 1

    # Verify scratchpad persisted
    result = _result(
        scratchpad(
            "Testing reason",
            "key1",
            agent_id=test_agent_id,
            operation="get",
        )
    )
    assert result["status"] == "success"
    assert result["data"]["value"] == "value1"

    # Clean up
    reasoning("Testing reason", action="end", agent_id=test_agent_id)


def test_session_data_integrity(test_agent_id, test_db):
    """Test that all session data is correctly persisted and loaded."""
    # Create session with comprehensive data
    reasoning("Testing reason", action="start", agent_id=test_agent_id)

    # Add multiple steps with evidence and biases
    reasoning(
        "Testing reason",
        action="step",
        content="First analysis",
        agent_id=test_agent_id,
        cognitive_mode="analysis",
        reasoning_type="deductive",
        evidence=["Evidence 1", "Evidence 2"],
        confidence=0.8,
    )

    reasoning(
        "Testing reason",
        action="step",
        content="Second synthesis",
        agent_id=test_agent_id,
        cognitive_mode="synthesis",
        reasoning_type="inductive",
        evidence=["Evidence 3"],
        confidence=0.7,
    )

    # Add reflection
    reasoning(
        "Testing reason",
        action="reflect",
        content="Important reflection",
        agent_id=test_agent_id,
        on_step=1,
    )

    # Add scratchpad items (now stored independently of reasoning sessions)
    scratchpad(
        "Testing reason",
        "hypothesis",
        agent_id=test_agent_id,
        value="Test hypothesis",
        operation="set",
    )

    # DB-backed lookup should still load persisted session data

    # Verify reasoning data is intact
    summary = _result(
        reasoning("Testing reason", action="summary", agent_id=test_agent_id)
    )
    assert summary["status"] == "success"
    assert summary["data"]["steps_count"] == 2
    assert summary["data"]["reflections_count"] == 1
    # Scratchpad is now decoupled — not counted in reasoning summary
    assert summary["data"]["scratchpad_items_count"] == 0

    # Verify scratchpad data is independently accessible
    result = _result(
        scratchpad(
            "Testing reason",
            "hypothesis",
            agent_id=test_agent_id,
            operation="get",
        )
    )
    assert result["status"] == "success"
    assert result["data"]["value"] == "Test hypothesis"

    # Clean up
    reasoning("Testing reason", action="end", agent_id=test_agent_id)


def test_invalid_action(test_agent_id, test_db):
    """Test that an invalid action returns an error."""
    result = _result(
        reasoning("Testing reason", action="invalid", agent_id=test_agent_id)
    )
    assert result["status"] == "error"
    assert result["error"]["code"] == "INVALID_ACTION"


def test_add_step_with_invalid_cognitive_mode_defaults(test_agent_id, test_db):
    """An invalid cognitive_mode defaults to 'analysis'."""
    reasoning("Testing reason", action="start", agent_id=test_agent_id)
    result = _result(
        reasoning(
            "Testing reason",
            action="step",
            content="Testing with invalid mode",
            cognitive_mode="invalid_mode",
            reasoning_type="deductive",
            confidence=0.8,
            agent_id=test_agent_id,
        )
    )
    assert result["status"] == "success"
    assert result["data"]["cognitive_mode"] == "analysis"
    reasoning("Testing reason", action="end", agent_id=test_agent_id)


def test_add_step_with_invalid_reasoning_type_defaults(test_agent_id, test_db):
    """An invalid reasoning_type defaults to 'deductive'."""
    reasoning("Testing reason", action="start", agent_id=test_agent_id)
    result = _result(
        reasoning(
            "Testing reason",
            action="step",
            content="Testing with invalid type",
            cognitive_mode="analysis",
            reasoning_type="invalid_type",
            confidence=0.8,
            agent_id=test_agent_id,
        )
    )
    assert result["status"] == "success"
    assert result["data"]["reasoning_type"] == "deductive"
    reasoning("Testing reason", action="end", agent_id=test_agent_id)


def test_bias_detection_on_overconfident_step(test_agent_id, test_db):
    """Steps with overconfident language get biases_detected populated."""
    reasoning("Testing reason", action="start", agent_id=test_agent_id)
    result = _result(
        reasoning(
            "Testing reason",
            action="step",
            content="This definitely proves my point",
            evidence=["Obviously this is correct"],
            confidence=0.9,
            agent_id=test_agent_id,
        )
    )
    assert result["status"] == "success"
    assert len(result["data"]["biases_detected"]) > 0
    reasoning("Testing reason", action="end", agent_id=test_agent_id)


def test_evaluate_with_low_confidence_recommends_evidence(test_agent_id, test_db):
    """evaluate flags low average confidence with a recommendation."""
    reasoning("Testing reason", action="start", agent_id=test_agent_id)
    reasoning(
        "Testing reason",
        action="step",
        content="Step 1",
        confidence=0.5,
        agent_id=test_agent_id,
    )
    reasoning(
        "Testing reason",
        action="step",
        content="Step 2",
        confidence=0.55,
        agent_id=test_agent_id,
    )
    result = _result(
        reasoning("Testing reason", action="evaluate", agent_id=test_agent_id)
    )
    assert result["status"] == "success"
    assert any("Low confidence" in r for r in result["data"]["recommendations"])
    reasoning("Testing reason", action="end", agent_id=test_agent_id)
