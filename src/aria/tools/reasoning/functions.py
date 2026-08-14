"""
Functional interface for reasoning tools.

This module provides standalone functions that wrap ReasoningSession methods
for use with LLM agent frameworks that expect function tools.

Each agent has ONE active reasoning session at a time, automatically managed
by the framework. This eliminates the need for agents to track session_id
parameters, solving the memory management problem inherent in LLM agents.
"""

import uuid
from typing import Any

from loguru import logger
from pydantic import BaseModel, Field

from aria.tools import Reason, safe_json, utc_timestamp
from aria.tools.decorators import log_tool_call

from . import registry
from .session import ReasoningSession

_DEFAULT_AGENT_ID = "aria"


# ---------------------------------------------------------------------------
# Explicit schema exposed to the LLM (mirrors ShellToolSchema pattern).
# ---------------------------------------------------------------------------


class ReasoningSchema(BaseModel):
    """Schema exposed to the LLM for the reasoning tool."""

    reason: str = Field(
        description=(
            "Required. Brief explanation of why you are calling this tool "
            "(e.g. 'Analyze tradeoffs between approach A and B')."
        )
    )
    action: str = Field(
        description=(
            "Action to perform: 'start' (new session), 'step' (add reasoning), "
            "'reflect' (examine a step), 'evaluate' (score session), "
            "'summary' (get summary), 'end' (close session)."
        )
    )
    content: str | None = Field(
        default=None,
        description=(
            "Reasoning content text. Required for 'step' and 'reflect' actions."
        ),
    )
    cognitive_mode: str | None = Field(
        default=None,
        description=(
            "Mode for the reasoning step: 'planning', 'analysis', "
            "'evaluation', 'synthesis', 'creative', 'reflection'."
        ),
    )
    reasoning_type: str | None = Field(
        default=None,
        description=(
            "Type of reasoning: 'deductive', 'inductive', 'abductive', "
            "'causal', 'probabilistic', 'analogical'."
        ),
    )
    evidence: list[str] | None = Field(
        default=None,
        description="List of supporting evidence strings for a step.",
    )
    confidence: float | None = Field(
        default=None,
        description="Confidence score 0.0-1.0 (default: 0.65).",
    )
    on_step: int | None = Field(
        default=None,
        description="Step number to reflect on (required for 'reflect' action).",
    )
    agent_id: str = Field(
        default=_DEFAULT_AGENT_ID,
        description="Auto-set. Do not provide.",
    )


def _ok(
    *,
    tool: str,
    reason: str,
    agent_id: str,
    session_id: str | None,
    data: dict[str, Any],
    timestamp: str | None = None,
) -> dict[str, Any]:
    return {
        "status": "success",
        "tool": tool,
        "reason": reason,
        "agent_id": agent_id,
        **({"session_id": session_id} if session_id is not None else {}),
        "timestamp": timestamp or utc_timestamp(),
        "data": data,
    }


def _err(
    *,
    tool: str,
    reason: str,
    agent_id: str,
    session_id: str | None,
    code: str,
    message: str,
    how_to_fix: str | None = None,
    recoverable: bool = False,
    timestamp: str | None = None,
) -> dict[str, Any]:
    err = {"code": code, "message": message, "recoverable": recoverable}
    if how_to_fix:
        err["how_to_fix"] = how_to_fix
    return {
        "status": "error",
        "tool": tool,
        "reason": reason,
        "agent_id": agent_id,
        **({"session_id": session_id} if session_id is not None else {}),
        "timestamp": timestamp or utc_timestamp(),
        "error": err,
    }


def _get_session(session_id: str, agent_id: str) -> ReasoningSession:
    """Get session from cache or load from database.

    Args:
        session_id: Session identifier
        agent_id: Agent identifier for multi-agent isolation

    Returns:
        ReasoningSession instance for the given ID

    Raises:
        ValueError: If the session does not exist
    """
    return registry.get_session(session_id, agent_id)


@log_tool_call
def reasoning(
    reason: Reason,
    action: str,
    content: str | None = None,
    cognitive_mode: str | None = None,
    reasoning_type: str | None = None,
    evidence: list[str] | None = None,
    confidence: float | None = None,
    on_step: int | None = None,
    agent_id: str = _DEFAULT_AGENT_ID,
) -> str:
    """Structured reasoning: start → step → reflect → evaluate → end.

    Actions: start, step, reflect, evaluate, summary, end.

    Returns:
        JSON string with action result and session status.
    """
    if action is None:
        return safe_json(
            _err(
                tool="reasoning",
                reason=reason,
                agent_id=agent_id,
                session_id=None,
                code="MISSING_ACTION",
                message="The 'action' parameter is required.",
                how_to_fix=(
                    "Provide the 'action' parameter: "
                    "start, step, reflect, evaluate, summary, end"
                ),
                recoverable=True,
            )
        )

    action = action.lower().strip()

    if action == "start":
        result = _action_start(reason, agent_id)
    elif action == "step":
        result = _action_step(
            reason,
            agent_id,
            content,
            cognitive_mode,
            reasoning_type,
            evidence,
            confidence,
        )
    elif action == "reflect":
        result = _action_reflect(reason, agent_id, content, on_step)
    elif action == "evaluate":
        result = _action_evaluate(reason, agent_id)
    elif action == "summary":
        result = _action_summary(reason, agent_id)
    elif action == "end":
        result = _action_end(reason, agent_id)
    else:
        result = _err(
            tool="reasoning",
            reason=reason,
            agent_id=agent_id,
            session_id=None,
            code="INVALID_ACTION",
            message=(
                f"Unknown action '{action}'. Valid actions: "
                "start, step, reflect, evaluate, summary, end"
            ),
            how_to_fix=(
                "Use one of the valid actions: "
                "start, step, reflect, evaluate, summary, end"
            ),
            recoverable=True,
        )

    return safe_json(result)


def _action_start(reason: str, agent_id: str) -> dict[str, Any]:
    """Start a new reasoning session."""
    session_id = f"{agent_id}_session_{uuid.uuid4().hex[:12]}"

    # If agent already has active session, we'll mark it inactive AFTER
    # successfully creating the new session to avoid losing active session
    # on creation failure (atomic replacement).
    old_session_id = registry.get_active_session_id(agent_id)

    session = ReasoningSession(session_id=session_id, agent_id=agent_id)
    session.set_database(registry.get_db())
    session.persist_metadata()

    if old_session_id is not None:
        logger.info(
            f"Replacing active session {old_session_id} with {session_id} "
            f"for agent '{agent_id}'"
        )
        registry.get_db().delete_session(old_session_id, agent_id)

    logger.success(f"Started reasoning session for agent '{agent_id}'")
    now = utc_timestamp()
    session.persist_tool_event(
        tool_name="reasoning",
        reason=reason,
        timestamp=now,
        payload={"action": "start"},
    )
    return _ok(
        tool="reasoning",
        reason=reason,
        agent_id=agent_id,
        session_id=session_id,
        timestamp=now,
        data={
            "message": "Reasoning session started successfully",
            "action": "start",
        },
    )


def _action_step(
    reason: str,
    agent_id: str,
    content: str | None,
    cognitive_mode: str | None,
    reasoning_type: str | None,
    evidence: list[str] | None,
    confidence: float | None,
) -> dict[str, Any]:
    """Add a reasoning step."""
    if content is None:
        return _err(
            tool="reasoning",
            reason=reason,
            agent_id=agent_id,
            session_id=None,
            code="MISSING_CONTENT",
            message="The 'content' parameter is required for 'step' action.",
            how_to_fix="Provide the 'content' parameter with your reasoning.",
            recoverable=True,
        )

    session_id = registry.get_active_session_id(agent_id)
    if session_id is None:
        return _err(
            tool="reasoning",
            reason=reason,
            agent_id=agent_id,
            session_id=None,
            code="NO_ACTIVE_SESSION",
            message=f"No active reasoning session for agent '{agent_id}'.",
            how_to_fix="Call reasoning with action='start' first.",
            recoverable=True,
        )

    try:
        session = _get_session(session_id, agent_id)
        step = session.add_step(
            reason=reason,
            content=content,
            cognitive_mode=cognitive_mode or "analysis",
            reasoning_type=reasoning_type or "deductive",
            evidence=evidence,
            confidence=confidence if confidence is not None else 0.65,
        )
        return _ok(
            tool="reasoning",
            reason=reason,
            agent_id=agent_id,
            session_id=session_id,
            timestamp=step.get("timestamp"),
            data={**step, "action": "step"},
        )
    except Exception as exc:
        logger.exception("reasoning step failed")
        return _err(
            tool="reasoning",
            reason=reason,
            agent_id=agent_id,
            session_id=session_id,
            code="INTERNAL_ERROR",
            message=str(exc),
        )


def _action_reflect(
    reason: str,
    agent_id: str,
    content: str | None,
    on_step: int | None,
) -> dict[str, Any]:
    """Add a reflection."""
    if content is None:
        return _err(
            tool="reasoning",
            reason=reason,
            agent_id=agent_id,
            session_id=None,
            code="MISSING_CONTENT",
            message=("The 'content' parameter is required for 'reflect' action."),
            how_to_fix="Provide the 'content' parameter with your reflection.",
            recoverable=True,
        )

    session_id = registry.get_active_session_id(agent_id)
    if session_id is None:
        return _err(
            tool="reasoning",
            reason=reason,
            agent_id=agent_id,
            session_id=None,
            code="NO_ACTIVE_SESSION",
            message=f"No active reasoning session for agent '{agent_id}'.",
            how_to_fix="Call reasoning with action='start' first.",
            recoverable=True,
        )

    try:
        session = _get_session(session_id, agent_id)
        refl = session.add_reflection(
            reason=reason,
            reflection=content,
            on_step=on_step,
        )
        return _ok(
            tool="reasoning",
            reason=reason,
            agent_id=agent_id,
            session_id=session_id,
            timestamp=refl.get("timestamp"),
            data={**refl, "action": "reflect"},
        )
    except Exception as exc:
        logger.exception("reasoning reflect failed")
        return _err(
            tool="reasoning",
            reason=reason,
            agent_id=agent_id,
            session_id=session_id,
            code="INTERNAL_ERROR",
            message=str(exc),
        )


def _action_evaluate(reason: str, agent_id: str) -> dict[str, Any]:
    """Evaluate reasoning quality."""
    session_id = registry.get_active_session_id(agent_id)
    if session_id is None:
        return _err(
            tool="reasoning",
            reason=reason,
            agent_id=agent_id,
            session_id=None,
            code="NO_ACTIVE_SESSION",
            message=f"No active reasoning session for agent '{agent_id}'.",
            how_to_fix="Call reasoning with action='start' first.",
        )

    try:
        session = _get_session(session_id, agent_id)
        evaluation = session.evaluate(reason=reason)
        return _ok(
            tool="reasoning",
            reason=reason,
            agent_id=agent_id,
            session_id=session_id,
            timestamp=evaluation.get("timestamp"),
            data={**evaluation, "action": "evaluate"},
        )
    except Exception as exc:
        logger.exception("reasoning evaluate failed")
        return _err(
            tool="reasoning",
            reason=reason,
            agent_id=agent_id,
            session_id=session_id,
            code="INTERNAL_ERROR",
            message=str(exc),
        )


def _action_summary(reason: str, agent_id: str) -> dict[str, Any]:
    """Get session summary."""
    session_id = registry.get_active_session_id(agent_id)
    if session_id is None:
        return _err(
            tool="reasoning",
            reason=reason,
            agent_id=agent_id,
            session_id=None,
            code="NO_ACTIVE_SESSION",
            message=f"No active reasoning session for agent '{agent_id}'.",
            how_to_fix="Call reasoning with action='start' first.",
        )

    try:
        session = _get_session(session_id, agent_id)
        summary = session.summary(reason=reason)
        return _ok(
            tool="reasoning",
            reason=reason,
            agent_id=agent_id,
            session_id=session_id,
            timestamp=summary.get("timestamp"),
            data={**summary, "action": "summary"},
        )
    except Exception as exc:
        logger.exception("reasoning summary failed")
        return _err(
            tool="reasoning",
            reason=reason,
            agent_id=agent_id,
            session_id=session_id,
            code="INTERNAL_ERROR",
            message=str(exc),
        )


def _action_end(reason: str, agent_id: str) -> dict[str, Any]:
    """End the reasoning session."""
    session_id = registry.get_active_session_id(agent_id)
    if session_id is None:
        return _err(
            tool="reasoning",
            reason=reason,
            agent_id=agent_id,
            session_id=None,
            code="NO_ACTIVE_SESSION",
            message=f"No active reasoning session for agent '{agent_id}'.",
        )

    now = utc_timestamp()
    try:
        # If we can still resolve the session, emit an audit event.
        session = registry.get_session(session_id, agent_id)
        session.persist_tool_event(
            tool_name="reasoning",
            reason=reason,
            timestamp=now,
            payload={"action": "end"},
        )
    except Exception:
        # Ending should still succeed even if session can't be loaded.
        logger.debug(f"Could not persist reasoning end tool event for {session_id}")

    # Mark inactive in persistence store
    registry.get_db().delete_session(session_id, agent_id)

    logger.info(f"Ended reasoning session for agent '{agent_id}'")
    return _ok(
        tool="reasoning",
        reason=reason,
        agent_id=agent_id,
        session_id=session_id,
        timestamp=now,
        data={
            "message": "Reasoning session ended successfully",
            "action": "end",
        },
    )


__all__ = [
    "reasoning",
]
