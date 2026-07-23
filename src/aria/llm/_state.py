"""Workflow state types, reducers, and the StatefulAgentWorkflow class.

This module owns the shared-state machinery threaded through the agent
workflow: the :class:`WorkflowState` TypedDict, the :func:`state_reducer`
pure function, and :class:`StatefulAgentWorkflow` which wires them into
the LlamaIndex :class:`AgentWorkflow` run-loop.
"""

import copy
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

from aria.llm._compress import (
    SCRATCHPAD_PRESSURE_THRESHOLD,
    compress_tool_output,
)

# Cumulative tool output budget as fraction of context (chars).
# When total tool output within a turn exceeds this, even "small"
# outputs get compressed to prevent silent accumulation.
_CUMULATIVE_BUDGET_RATIO = 0.15  # 15% of context in chars


class ToolCallRecord(TypedDict):
    """A single tool invocation captured in the workflow state.

    Attributes:
        agent: Name of the agent that invoked the tool.
        tool: Name of the tool that was called.
        args: Keyword arguments passed to the tool.
        result: String representation of the tool's output.
        error: Error message if the tool raised an exception, else ``None``.
    """

    agent: str
    tool: str
    args: dict
    result: str
    error: str | None


class WorkflowState(TypedDict):
    """Minimal shared state threaded through the agent workflow.

    This dict is seeded into ``ctx.store`` by :func:`get_agent_workflow` via
    ``AgentWorkflow(initial_state=...)``. In this project, live updates are
    performed by :class:`StatefulAgentWorkflow`, which applies
    :func:`state_reducer` after every :class:`AgentOutput` and
    :class:`ToolCallResult` event so that the state reflects the latest
    activity within the current workflow context.

    Attributes:
        current_agent: Name of the agent that is currently active.
        tool_calls: Append-only log of every tool invocation during the run.
        last_error: Most recent tool error message, or ``None`` if the last
            tool call succeeded.
    """

    current_agent: str
    tool_calls: list[ToolCallRecord]
    last_error: str | None


def initial_workflow_state(root_agent: str) -> WorkflowState:
    """Return a fresh :class:`WorkflowState` for a new workflow run.

    Args:
        root_agent: Name of the root agent (used to seed ``current_agent``).

    Returns:
        A :class:`WorkflowState` with empty collections and no error.

    Example::

        state = initial_workflow_state("Aria")
        # WorkflowState(
        #     current_agent="Aria", tool_calls=[], last_error=None
        # )
    """
    return WorkflowState(
        current_agent=root_agent,
        tool_calls=[],
        last_error=None,
    )


def state_reducer(state: WorkflowState, ev: Any) -> WorkflowState:
    """Update *state* in response to a workflow event.

    This function is designed to be called after relevant events emitted by the
    :class:`AgentWorkflow` run loop. In this project it is invoked by
    :class:`StatefulAgentWorkflow` after agent-output and tool-result steps. It
    handles two event types:

    * :class:`AgentOutput` — updates ``current_agent``.
    * :class:`ToolCallResult` — appends a :class:`ToolCallRecord` to
      ``tool_calls`` and updates ``last_error``.

    All other event types are ignored and the state is returned unchanged.

    Args:
        state: The current workflow state dict (mutated in-place and returned).
        ev: Any event object emitted by the workflow.

    Returns:
        The updated :class:`WorkflowState`.

    Example::

        from llama_index.core.agent.workflow import AgentOutput

        state = initial_workflow_state("Aria")
        fake_output = AgentOutput(
            response=..., current_agent_name="Aria", tool_calls=[]
        )
        state = state_reducer(state, fake_output)
        assert state["current_agent"] == "Aria"
    """
    if isinstance(ev, AgentOutput):
        state["current_agent"] = ev.current_agent_name

    elif isinstance(ev, ToolCallResult):
        output = ev.tool_output
        is_error: bool = getattr(output, "is_error", False)
        raw_output: str = str(getattr(output, "content", output))

        record = ToolCallRecord(
            agent=state["current_agent"],
            tool=ev.tool_name,
            args=ev.tool_kwargs,
            result=raw_output,
            error=raw_output if is_error else None,
        )
        state["tool_calls"].append(record)
        state["last_error"] = record["error"]

    return state


class StatefulAgentWorkflow(AgentWorkflow):
    """`AgentWorkflow` variant that keeps custom state in `ctx.store` in sync.

    LlamaIndex's built-in ``AgentWorkflow`` seeds ``ctx.store['state']`` from
    ``initial_state`` and exposes that state to the LLM via ``state_prompt``,
    but it does not provide a reducer hook for streamed workflow events. This
    subclass closes that gap by applying :func:`state_reducer` to the live
    context state.

    A pristine copy of the initial state is kept in ``_state_template`` so
    that every new workflow run receives a fresh, un-mutated state —
    preventing cross-conversation leakage of accumulated tool-call records.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        # Store a deep copy that is never mutated, so each run can start
        # from a clean slate regardless of how many tool calls happened
        # in previous conversations.
        self._state_template: dict = copy.deepcopy(self.initial_state)

    async def _init_context(self, ctx: Any, ev: Any) -> None:
        """Initialise context with a *fresh* copy of the initial state.

        The parent ``_init_context`` sets ``ctx.store["state"]`` to
        ``self.initial_state`` — a single dict instance that is shared
        across all runs.  Because :func:`state_reducer` mutates that
        dict in-place (appending to ``tool_calls``), the state silently
        accumulates records from every previous conversation.

        Overriding here to deep-copy from the pristine ``_state_template``
        ensures each run starts with an empty ``tool_calls`` list.
        """
        await super()._init_context(ctx, ev)
        await ctx.store.set("state", copy.deepcopy(self._state_template))

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
            state = dict(initial_workflow_state(root_agent=self.root_agent))

        reduced_state = state_reducer(cast(WorkflowState, state), ev)
        await ctx.store.set("state", reduced_state)
        return reduced_state

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

        approx_tokens = sum(len(str(m.content or "")) // 4 for m in messages)
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
        approx_tokens = sum(len(str(m.content or "")) // 4 for m in ev.input)
        logger.info(
            f"run_agent_step: {msg_count} messages, "
            f"~{approx_tokens} tokens "
            f"(roles: {[m.role.value for m in ev.input[:5]]}...)"
        )

        try:
            output = await super().run_agent_step(ctx, ev)
        except Exception:
            raise
        await self.reduce_state(ctx, output)
        return await self._run_with_empty_response_fallback(ctx, ev, output)

    async def _get_cumulative_budget(self, ctx: Any) -> int:
        """Get the cumulative tool-output char budget for this turn."""
        try:
            from aria.config.api import Vllm as VllmConfig

            ctx_chars = VllmConfig.chat_context_size * 4
        except Exception:
            ctx_chars = 32768 * 4
        return int(ctx_chars * _CUMULATIVE_BUDGET_RATIO)

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

        # --- Record raw output in state BEFORE compression ---
        await self.reduce_state(ctx, result)

        # --- Compress tool output to control scratchpad growth ---
        output = result.tool_output
        if not output.is_error:
            raw_content = str(getattr(output, "content", ""))

            # Track cumulative tool output for budget enforcement.
            cumulative = await ctx.store.get("_turn_tool_chars", default=0)
            cumulative += len(raw_content)
            await ctx.store.set("_turn_tool_chars", cumulative)

            budget = await self._get_cumulative_budget(ctx)
            force = cumulative > budget

            compressed = compress_tool_output(raw_content, ev.tool_name)
            # If cumulative budget exceeded and normal compression
            # didn't trigger (output was "small"), force compression.
            if force and compressed == raw_content and len(raw_content) > 200:
                from aria.llm._compress import _get_thresholds

                t = _get_thresholds()
                h_size = t["head_chars"] // 2
                t_size = t["tail_chars"] // 2
                head = raw_content[:h_size]
                tail = raw_content[-t_size:]
                dropped = len(raw_content) - len(head) - len(tail)
                if dropped > 0:
                    compressed = (
                        head + f"\n\n[...budget-compressed — dropped "
                        f"{dropped:,} chars. Cumulative output "
                        f"({cumulative:,} chars) exceeds turn "
                        f"budget ({budget:,} chars).]" + tail
                    )

            if compressed != raw_content:
                output.raw_output = raw_content
                output.content = compressed

        return result


# Reuse base step metadata so overridden methods stay discoverable.
StatefulAgentWorkflow.run_agent_step._step_config = (  # type: ignore[assignment]
    AgentWorkflow.run_agent_step._step_config  # type: ignore[attr-defined]
)
StatefulAgentWorkflow.call_tool._step_config = (  # type: ignore[assignment]
    AgentWorkflow.call_tool._step_config  # type: ignore[attr-defined]
)
