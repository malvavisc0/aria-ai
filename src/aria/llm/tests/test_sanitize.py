"""Tests for aria.llm._sanitize — malformed tool-call argument recovery.

These lock in the safety net that cleans up malformed ``function.arguments``
before they reach vLLM.  The streaming generator stores raw args and defers
cleanup to :func:`_sanitize_messages` (next-turn replay) and
``get_tool_calls_from_response`` (same-turn execution), so these tests pin
that cleanup path rather than the generator.
"""

from __future__ import annotations

import json

from llama_index.core.base.llms.types import (
    ChatMessage,
    MessageRole,
    ToolCallBlock,
)

from aria.llm._sanitize import (
    _sanitize_messages,
    _sanitize_tool_call_args,
)

_MALFORMED_INPUTS = [
    '{"reason": "partial',  # truncated, no closing quote/brace
    '{"a": 1} {"b": 2}',  # two concatenated JSON objects
    '{"a": 1} trailing garbage',  # trailing non-JSON
    "hello world",  # pure non-JSON text
    "",  # empty
]


class TestSanitizeToolCallArgs:
    """Malformed JSON arguments must recover to a JSON-safe dict, never raise."""

    def test_returns_dict_for_every_malformed_input(self) -> None:
        for raw in _MALFORMED_INPUTS:
            result = _sanitize_tool_call_args(raw)
            assert isinstance(result, dict)
            # The recovered value must itself be JSON-serialisable.
            json.dumps(result)

    def test_valid_dict_passes_through(self) -> None:
        obj = {"reason": "do work", "count": 3}
        assert _sanitize_tool_call_args(obj) is obj

    def test_valid_string_is_parsed(self) -> None:
        assert _sanitize_tool_call_args('{"reason": "ok"}') == {"reason": "ok"}


class TestSanitizeMessagesReplaySafety:
    """A stored message with malformed tool kwargs must be sanitised on replay."""

    def _message(self, tool_kwargs: str) -> ChatMessage:
        return ChatMessage(
            role=MessageRole.ASSISTANT,
            blocks=[
                ToolCallBlock(
                    tool_call_id="t1",
                    tool_kwargs=tool_kwargs,
                    tool_name="ax",
                )
            ],
        )

    def test_malformed_tool_kwargs_becomes_valid_json(self) -> None:
        msg = self._message('{"reason": "partial')
        sanitized = _sanitize_messages([msg])

        block = sanitized[0].blocks[0]
        assert isinstance(block, ToolCallBlock)
        assert isinstance(block.tool_kwargs, str)
        json.loads(block.tool_kwargs)  # must not raise on replay

    def test_concatenated_objects_becomes_valid_json(self) -> None:
        msg = self._message('{"a": 1} {"b": 2}')
        sanitized = _sanitize_messages([msg])

        block = sanitized[0].blocks[0]
        assert isinstance(block, ToolCallBlock)
        assert isinstance(block.tool_kwargs, str)
        # Must be valid JSON so vLLM's replay json.loads() cannot crash; the
        # exact recovery (first object) is not the guarantee under test.
        json.loads(block.tool_kwargs)

    def test_clean_message_is_unchanged(self) -> None:
        msg = self._message('{"reason": "ok", "family": "mcp"}')
        sanitized = _sanitize_messages([msg])

        assert sanitized[0] is msg
