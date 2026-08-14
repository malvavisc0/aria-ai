"""UI-related constants/helpers for displaying tool activity."""

from __future__ import annotations

import re

import chainlit as cl
from chainlit.context import context
from llama_index.core.agent.workflow import ToolCall


def _current_parent_id() -> str | None:
    """Return the id of the current Chainlit run step (e.g. on_message).

    Nesting thinking/tool steps under this id makes them render above the
    assistant answer in the timeline instead of as disconnected top-level
    entries.
    """
    parent = context.current_step
    return parent.id if parent else None


async def send_tool_step(event: ToolCall) -> cl.Step:
    """Create + send a tool Step for a ToolCall event.

    Populates ``step.input`` with the tool-call kwargs (so the collapsed
    step shows what was asked) and stores ``tool_id`` in ``metadata`` so
    the matching ``ToolCallResult`` can fill ``step.output``.
    """
    label = _step_label_from_tool_call(event)
    tool_name = (event.tool_name or "").strip() or "tool"
    step = _make_tool_step(label, tool_name)
    step.parent_id = _current_parent_id()
    step.input = event.tool_kwargs or {}
    if event.tool_id:
        step.metadata = {"tool_id": event.tool_id}
    await step.send()
    return step


async def send_thinking_step() -> cl.Step:
    """Create + persist a collapsed 'Thinking' step for one reasoning segment."""
    step = cl.Step(
        name="Thinking",
        type="run",
        default_open=False,
        auto_collapse=True,
        show_input=False,
    )
    step.parent_id = _current_parent_id()
    await step.send()
    return step


def _step_label_from_tool_call(event: ToolCall) -> str:
    """Best-effort label for a tool call.

    Label preference: `reason`, else tool name.
    """

    tool_name = (event.tool_name or "").strip() or "<unknown_tool>"
    tool_kwargs = event.tool_kwargs or {}
    label = tool_kwargs.get("reason", None)

    if isinstance(label, str):
        label = label.strip()
        # Models sometimes wrap the whole reason in quotes — a
        # serialization artifact, never intentional labeling.
        if len(label) >= 2 and label.startswith('"') and label.endswith('"'):
            label = label[1:-1].strip()
    else:
        label = tool_name

    return label


def _make_tool_step(label: str, tool_name: str = "tool") -> cl.Step:
    """Create a tool Step with the current UI preferences.

    Uses a sanitized name for the step to ensure compatibility with
    Chainlit's avatar system (which requires names matching the pattern
    ^[a-zA-Z0-9_ .-]+$).

    The step name is used for both display and avatar lookup. We strip
    non-ASCII characters from the label to make it avatar-compatible
    while preserving the descriptive reason text.

    Args:
        label: The display label (e.g., "Reading file...")
        tool_name: The tool name for fallback (e.g., "read_file")

    Returns:
        A configured cl.Step instance
    """
    # Strip non-ASCII characters for avatar compatibility
    # Chainlit's avatar endpoint requires: ^[a-zA-Z0-9_ .-]+$
    # Keep ASCII letters, numbers, spaces, underscores, dots, and hyphens
    safe_label = re.sub(r"[^\x00-\x7F]+", "", label).strip()

    # If stripping leaves nothing, fall back to tool name
    if not safe_label:
        safe_label = tool_name.replace("-", "_")

    return cl.Step(
        name=safe_label,
        type="tool",
        show_input=False,
        default_open=False,
    )
