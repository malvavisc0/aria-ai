"""Subprocess entry point for worker agent execution.

This module is invoked as ``python -m aria.cli.worker._runner`` by the
``aria worker spawn`` CLI command. It initializes an LLM client, creates
a WorkerAgent, runs the prompt autonomously, and writes results to disk.
"""

import argparse
import asyncio
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

from loguru import logger

PLAN_SECTION_TEMPLATE = """
## Execution Plan
You have plan {plan_id} registered under agent_id "{agent_id}".
Work through its steps IN ORDER using the plan tool:
first plan(action="get", execution_id="{plan_id}", agent_id="{agent_id}"), then for each step
plan(action="update", execution_id="{plan_id}", step_id=<id>, status="in_progress") before acting,
and plan(action="update", execution_id="{plan_id}", step_id=<id>, status="completed", result="<summary>") after.
On an unrecoverable step, set status="failed" with the reason in result.
"""


def _update_audit(worker_id: str, updates: dict):
    from aria.config.folders import Data
    from aria.server.process_utils import load_state, save_state

    path = Data.path / "workers" / f"{worker_id}.json"
    audit = load_state(path)
    audit.update(updates)
    save_state(path, audit)


def _build_prompt(args) -> str:
    prompt = args.prompt
    if args.reason:
        prompt += f"\n\nReason for delegation: {args.reason}"
    if args.expected:
        prompt += f"\n\nExpected deliverable: {args.expected}"
    if args.instructions:
        prompt += f"\n\nAdditional instructions: {args.instructions}"
    prompt += PLAN_SECTION_TEMPLATE.format(
        plan_id=args.plan_id, agent_id=args.worker_id
    )
    return prompt


def _settle_steps(plan_id: str, mode: str, exc: Exception | None = None) -> None:
    """Settle plan steps to terminal states at worker exit so the panel
    never lies.

    mode ∈ {"completed", "failed"}. "completed" flips every
    pending/in_progress step to completed. "failed" marks the
    in_progress step — else the first pending step (best-effort
    attribution: the crashed step is approximated, not detected) — as
    failed with result=str(exc). Early-returns if load_plan(plan_id) is
    None. Crash-path safe: only PlannerDatabase() is used (a fresh
    session on the singleton engine; no workflow session in scope);
    do not add a session parameter.
    """
    from aria.tools.planner.database import PlannerDatabase

    db = PlannerDatabase()
    plan = db.load_plan(plan_id)
    if plan is None:
        return
    if mode == "completed":
        for step in plan["steps"]:
            if step["status"] in {"pending", "in_progress"}:
                db.update_step(plan_id, step["id"], status="completed")
        return
    target = next(
        (s for s in plan["steps"] if s["status"] == "in_progress"),
        next((s for s in plan["steps"] if s["status"] == "pending"), None),
    )
    if target is not None:
        db.update_step(plan_id, target["id"], status="failed", result=str(exc))


def _process_event(event, tool_calls: list[dict], result_state: list[str]) -> None:
    from llama_index.core.agent.workflow import AgentOutput, ToolCall

    if isinstance(event, ToolCall):
        tool_calls.append(
            {
                "tool": event.tool_name,
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )
    elif isinstance(event, AgentOutput) and event.response:
        content = getattr(event.response, "content", "")
        if content:
            result_state[0] = content


def _record_failure(worker_id: str, exc: Exception, plan_id: str) -> None:
    logger.exception(f"Worker {worker_id} failed: {exc}")
    _update_audit(
        worker_id,
        {
            "status": "failed",
            "completed_at": datetime.now(UTC).isoformat(),
            "error": str(exc),
        },
    )
    _settle_steps(plan_id, "failed", exc=exc)


def _record_completion(
    worker_id: str,
    result_text: str,
    result_file: Path,
    tool_calls: list[dict],
    plan_id: str,
) -> None:
    _update_audit(
        worker_id,
        {
            "status": "completed",
            "completed_at": datetime.now(UTC).isoformat(),
            "result": result_text[:2000],
            "result_file": str(result_file),
            "tool_calls": tool_calls,
        },
    )
    _settle_steps(plan_id, "completed")
    logger.info(f"Worker {worker_id} completed")


async def _run(args):
    from llama_index.core.agent.workflow import AgentOutput, AgentWorkflow
    from llama_index.core.memory import Memory

    from aria.agents.worker import get_worker_agent
    from aria.config.models import Chat as ChatConfig
    from aria.config.models import Embeddings as EmbeddingsConfig
    from aria.llm import get_chat_llm, get_instructions_extras

    worker_id = args.worker_id
    output_dir = Path(args.output_dir)

    from aria.config.folders import Debug

    logs_dir = Debug.path / "workers"
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_file = logs_dir / f"{worker_id}.log"
    logger.add(str(log_file), rotation="10 MB", level="DEBUG")
    logger.info(f"Worker {worker_id} starting (PID {os.getpid()})")

    _update_audit(worker_id, {"started_at": datetime.now(UTC).isoformat()})

    try:
        llm = get_chat_llm(api_base=ChatConfig.api_url, model=ChatConfig.model)
        extras = get_instructions_extras(agent_name="worker")
        agent = get_worker_agent(llm=llm, extras=extras, output_dir=str(output_dir))

        memory = Memory.from_defaults(
            session_id=worker_id, token_limit=EmbeddingsConfig.token_limit
        )

        workflow = AgentWorkflow(agents=[agent], root_agent=agent.name)
        handler = workflow.run(
            user_msg=_build_prompt(args),
            memory=memory,
            max_iterations=ChatConfig.max_iteration,
        )

        tool_calls: list[dict] = []
        result_state: list[str] = [""]

        async for event in handler.stream_events():
            _process_event(event, tool_calls, result_state)

        final = await handler
        if isinstance(final, AgentOutput) or hasattr(final, "response"):
            content = getattr(getattr(final, "response", None), "content", "")
            if content:
                result_state[0] = content

        result_text = result_state[0]
        result_file = output_dir / "result.md"
        result_file.write_text(result_text)

        _record_completion(
            worker_id, result_text, result_file, tool_calls, args.plan_id
        )

    except Exception as e:
        _record_failure(worker_id, e, args.plan_id)
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker-id", required=True)
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--reason", default=None)
    parser.add_argument("--expected", default=None)
    parser.add_argument("--instructions", default=None)
    parser.add_argument("--plan-id", required=True)
    asyncio.run(_run(parser.parse_args()))


if __name__ == "__main__":
    main()
