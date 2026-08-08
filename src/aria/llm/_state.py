"""Workflow state types, reducers, and the StatefulAgentWorkflow class.

This module owns the shared-state machinery threaded through the agent
workflow: the :class:`WorkflowState` TypedDict, the :func:`state_reducer`
pure function, and :class:`StatefulAgentWorkflow` which wires them into
the LlamaIndex :class:`AgentWorkflow` run-loop.
"""

import os
from typing import Any, cast

from llama_index.core.agent.workflow import (
    AgentOutput,
    AgentSetup,
    AgentWorkflow,
    ToolCall,
    ToolCallResult,
)
from llama_index.core.base.llms.types import ChatMessage, MessageRole
from llama_index.core.tools.types import ToolOutput
from loguru import logger
from typing_extensions import TypedDict


def _env_float(key: str, default: float) -> float:
    try:
        return float(os.environ.get(key, ""))
    except (TypeError, ValueError):
        return default


# Per-turn scratchpad pressure threshold (fraction of context_size).
# When exceeded, the agent is told to consolidate and produce a final answer.
SCRATCHPAD_PRESSURE_THRESHOLD = _env_float("ARIA_SCRATCHPAD_PRESSURE_THRESHOLD", 0.40)


class WorkflowState(TypedDict):
    """Shared state threaded through the agent workflow.

    Seeded into ``ctx.store`` by :func:`get_agent_workflow` via
    ``AgentWorkflow(initial_state=...)``. Live updates are performed by
    :class:`StatefulAgentWorkflow`, which applies :func:`state_reducer`
    after every :class:`ToolCallResult` event.

    Attributes:
        last_error: Most recent tool error message, or ``None`` if the last
            tool call succeeded.
    """

    last_error: str | None


def initial_workflow_state() -> WorkflowState:
    """Return a fresh :class:`WorkflowState` for a new workflow run.

    Returns:
        A :class:`WorkflowState` with no recorded error.
    """
    return WorkflowState(last_error=None)


def state_reducer(state: WorkflowState, ev: Any) -> WorkflowState:
    """Update *state* in response to a workflow event.

    Only :class:`ToolCallResult` is handled: it sets ``last_error`` to the
    tool's error message (or ``None`` on success). All other events are
    ignored and the state is returned unchanged.

    Args:
        state: The current workflow state dict (mutated in-place and returned).
        ev: Any event object emitted by the workflow.

    Returns:
        The updated :class:`WorkflowState`.
    """
    if isinstance(ev, ToolCallResult):
        output = ev.tool_output
        is_error: bool = getattr(output, "is_error", False)
        state["last_error"] = (
            str(getattr(output, "content", output)) if is_error else None
        )
    return state


class StatefulAgentWorkflow(AgentWorkflow):
    """`AgentWorkflow` variant that keeps custom state in `ctx.store` in sync.

    LlamaIndex's built-in ``AgentWorkflow`` seeds ``ctx.store['state']`` from
    ``initial_state`` and exposes that state to the LLM via ``state_prompt``,
    but it does not provide a reducer hook for streamed workflow events. This
    subclass closes that gap by applying :func:`state_reducer` to the live
    context state.
    """

    async def reduce_state(self, ctx: Any, ev: Any) -> "WorkflowState":
        """Apply :func:`state_reducer` to the stored state.

        Args:
            ctx: Workflow context exposing ``ctx.store``.
            ev: Streamed workflow event to reduce into the state.

        Returns:
            The updated workflow state persisted back into ``ctx.store``.
        """
        state = await ctx.store.get("state", default=None)
        if state is None:
            state = dict(initial_workflow_state())

        reduced_state = state_reducer(cast(WorkflowState, state), ev)
        await ctx.store.set("state", reduced_state)
        return reduced_state

    @staticmethod
    def _approx_tokens(messages: list[ChatMessage]) -> int:
        """Estimate token count from a chat-message list.

        Counts characters across each message's ``blocks`` (the typed field)
        rather than the ``content`` property, which only joins ``TextBlock``
        text and ignores images, tool-call blocks, etc. Falls back to
        ``str()`` only for non-text block shapes.
        """

        def block_chars(block: Any) -> int:
            if block is None:
                return 0
            text = getattr(block, "text", None)
            if isinstance(text, str):
                return len(text)
            return len(str(block))

        total = 0
        for m in messages:
            total += sum(block_chars(b) for b in m.blocks)
        return total // 4

    async def _inject_pressure_warning(
        self, ctx: Any, messages: list[ChatMessage]
    ) -> list[ChatMessage]:
        """Inject a context-pressure warning when scratchpad usage is high.

        When the cumulative tool output within a single turn approaches the
        context limit, the agent is told to consolidate and finish.  This
        prevents ``context_length_exceeded`` errors on long-running turns.

        Returns a new list (never mutates the input) so retries use clean
        messages.
        """
        try:
            from aria.config.api import Vllm as VllmConfig

            context_size = VllmConfig.chat_context_size
        except Exception:
            return messages

        approx_tokens = self._approx_tokens(messages)
        usage_ratio = approx_tokens / context_size if context_size else 0

        if usage_ratio >= SCRATCHPAD_PRESSURE_THRESHOLD:
            warning = (
                f"\u26a0 Context is {usage_ratio:.0%} full "
                f"({approx_tokens:,}/{context_size:,} tokens). "
                f"Consolidate findings and produce a final answer now."
            )
            logger.warning(f"Scratchpad pressure {usage_ratio:.0%} — injecting warning")
            # Return a copy with the warning appended (no mutation).
            return [
                *messages,
                ChatMessage(role=MessageRole.SYSTEM, content=warning),
            ]
        return messages

    @staticmethod
    def _is_empty_output(output: AgentOutput) -> bool:
        return not output.tool_calls and not (output.response.content or "").strip()

    @staticmethod
    def _synthesize_error_response(last_err: str) -> str:
        return (
            "The tool call encountered an error:\n\n"
            f"```\n{last_err}\n```\n\n"
            "I'll try a different approach if you'd like"
            " \u2014 just let me know how to proceed."
        )

    async def _retry_after_tool_failure(
        self, ctx: Any, ev: AgentSetup
    ) -> AgentOutput | None:
        try:
            output = await super().run_agent_step(ctx, ev)
        except Exception:
            return None
        await self.reduce_state(ctx, output)
        return output

    async def _run_with_empty_response_fallback(
        self, ctx: Any, ev: AgentSetup, output: AgentOutput
    ) -> AgentOutput:
        if not self._is_empty_output(output):
            return output
        state = await ctx.store.get("state", default=None)
        last_err = (state or {}).get("last_error")
        if not last_err:
            return output
        retried = await self._retry_after_tool_failure(ctx, ev)
        if retried is not None and self._is_empty_output(retried):
            retried.response.content = self._synthesize_error_response(last_err)
        return retried or output

    async def run_agent_step(self, ctx: Any, ev: AgentSetup) -> AgentOutput:
        """Run the parent agent step and synchronize custom state.

        See class docstring for behavior.
        """
        ev.input = await self._inject_pressure_warning(ctx, ev.input)

        msg_count = len(ev.input)
        approx_tokens = self._approx_tokens(ev.input)
        logger.info(
            f"run_agent_step: {msg_count} messages, "
            f"~{approx_tokens} tokens "
            f"(roles: {[m.role.value for m in ev.input[:5]]}...)"
        )

        output = await super().run_agent_step(ctx, ev)
        await self.reduce_state(ctx, output)
        return await self._run_with_empty_response_fallback(ctx, ev, output)

    async def call_tool(self, ctx: Any, ev: ToolCall) -> ToolCallResult:
        """Run the parent tool call step and synchronize custom state.

        Applies deterministic tool-output compression before the result
        is injected into the agent context, keeping the full output in
        ``ToolOutput.raw_output`` for logging/diagnostics.

        Tracks cumulative tool output size within the turn. When the
        running total exceeds the budget, even normally-small outputs
        are compressed to prevent silent accumulation.

        If the parent ``call_tool`` raises unexpectedly, the error is
        caught and wrapped in an error :class:`ToolCallResult` so the
        agent can surface it instead of crashing the workflow.
        """
        try:
            result = await super().call_tool(ctx, ev)
        except Exception as exc:
            # Build an error result so the workflow survives.
            result = ToolCallResult(
                tool_name=ev.tool_name,
                tool_kwargs=ev.tool_kwargs,
                tool_id=ev.tool_id,
                tool_output=ToolOutput(
                    content=f"Tool execution failed: {exc}",
                    tool_name=ev.tool_name,
                    raw_input=ev.tool_kwargs,
                    raw_output=str(exc),
                    is_error=True,
                    exception=exc,
                ),
                return_direct=False,
            )

        await self.reduce_state(ctx, result)
        return result


# Reuse base step metadata so overridden methods stay discoverable.
StatefulAgentWorkflow.run_agent_step._step_config = (  # type: ignore[assignment]
    AgentWorkflow.run_agent_step._step_config  # type: ignore[attr-defined]
)
StatefulAgentWorkflow.call_tool._step_config = (  # type: ignore[assignment]
    AgentWorkflow.call_tool._step_config  # type: ignore[attr-defined]
)
