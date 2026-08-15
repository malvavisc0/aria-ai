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

from aria.tools.worker.results import (
    build_manifest,
    settle_unfinished_step,
    write_manifest,
)

PLAN_SECTION_TEMPLATE = """
<system_controlled_execution_plan>
You have plan {plan_id} registered under agent_id "{agent_id}".
Work through its steps IN ORDER using the plan tool:
first plan(action="get", execution_id="{plan_id}", agent_id="{agent_id}"), then for each step
plan(action="update", execution_id="{plan_id}", step_id=<id>, status="in_progress") before acting,
and plan(action="update", execution_id="{plan_id}", step_id=<id>, status="completed", result="<summary>") after.
On an unrecoverable step, set status="failed" with the reason in result.
</system_controlled_execution_plan>
"""


def _update_audit(worker_id: str, updates: dict):
    from aria.config.folders import Data
    from aria.server.process_utils import load_state, save_state

    path = Data.path / "workers" / f"{worker_id}.json"
    audit = load_state(path)
    audit.update(updates)
    save_state(path, audit)


def _build_prompt(args) -> str:
    sections = ["<delegated_task>\n" + args.prompt + "\n</delegated_task>"]
    if args.reason:
        sections.append(
            "<delegation_reason>\n" + args.reason + "\n</delegation_reason>"
        )
    if args.expected:
        sections.append(
            "<expected_deliverable>\n" + args.expected + "\n</expected_deliverable>"
        )
    if args.instructions:
        sections.append(
            "<additional_task_constraints>\n"
            + args.instructions
            + "\n</additional_task_constraints>"
        )
    sections.append(
        PLAN_SECTION_TEMPLATE.format(plan_id=args.plan_id, agent_id=args.worker_id)
    )
    return "\n\n".join(sections)


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


def _record_failure(
    worker_id: str,
    exc: Exception,
    plan_id: str,
    report_path: Path,
    started_at: str,
) -> None:
    logger.exception(f"Worker {worker_id} failed: {exc}")
    settle_unfinished_step(plan_id, str(exc))
    manifest = build_manifest(
        worker_id=worker_id,
        plan_id=plan_id,
        status="failed",
        summary="Worker execution failed before the task was completed.",
        report_path=report_path,
        started_at=started_at,
        error=str(exc),
    )
    manifest_path = report_path.with_name("result.json")
    write_manifest(manifest_path, manifest)
    _update_audit(
        worker_id,
        {
            "status": "failed",
            "completed_at": datetime.now(UTC).isoformat(),
            "error": str(exc),
            "result_file": str(report_path),
            "result_manifest": str(manifest_path),
        },
    )


def _record_completion(
    worker_id: str,
    result_text: str,
    result_file: Path,
    tool_calls: list[dict],
    plan_id: str,
    started_at: str,
) -> None:
    manifest = build_manifest(
        worker_id=worker_id,
        plan_id=plan_id,
        status="completed",
        summary=result_text,
        report_path=result_file,
        started_at=started_at,
    )
    manifest_file = result_file.with_name("result.json")
    write_manifest(manifest_file, manifest)
    _update_audit(
        worker_id,
        {
            "status": manifest.status,
            "completed_at": datetime.now(UTC).isoformat(),
            "result": result_text[:2000],
            "result_file": str(result_file),
            "result_manifest": str(manifest_file),
            "completed_steps": manifest.completed_steps,
            "total_steps": manifest.total_steps,
            "warnings": manifest.warnings,
            "error": manifest.error,
            "tool_calls": tool_calls,
        },
    )
    logger.info(f"Worker {worker_id} {manifest.status}")


async def _run(args):
    from llama_index.core.agent.workflow import AgentOutput, AgentWorkflow
    from llama_index.core.memory import Memory

    from aria.agents.worker import get_worker_agent
    from aria.config.models import Chat as ChatConfig
    from aria.config.models import Embeddings as EmbeddingsConfig
    from aria.llm import get_chat_llm, get_instructions_extras
    from aria.tools.execution_context import ExecutionContext, set_execution_context

    worker_id = args.worker_id
    set_execution_context(ExecutionContext(role="worker", worker_id=worker_id))
    output_dir = Path(args.output_dir)

    from aria.config.folders import Debug

    logs_dir = Debug.path / "workers"
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_file = logs_dir / f"{worker_id}.log"
    logger.add(str(log_file), rotation="10 MB", level="DEBUG")
    logger.info(f"Worker {worker_id} starting (PID {os.getpid()})")

    started_at = datetime.now(UTC).isoformat()
    _update_audit(worker_id, {"started_at": started_at})
    result_file = output_dir / "result.md"

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
        result_file.write_text(result_text)

        _record_completion(
            worker_id, result_text, result_file, tool_calls, args.plan_id, started_at
        )

    except Exception as e:
        _record_failure(worker_id, e, args.plan_id, result_file, started_at)
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
