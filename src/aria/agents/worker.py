"""Headless worker agent for executing seeded task plans."""

from llama_index.core.agent import FunctionAgent
from llama_index.core.llms import LLM
from loguru import logger

from aria.agents.instructions import load_agent_instructions
from aria.tools.registry import get_tools


class WorkerAgent(FunctionAgent):
    """Background terminal executor with no conversation memory."""

    @staticmethod
    def get_system_prompt(
        extras: str | None = None,
        output_dir: str | None = None,
    ) -> str:
        base = load_agent_instructions(
            agent_name="worker",
            extras=extras,
            base_sections=["core", "failure"],
        )
        if output_dir:
            base += (
                f"\n\n## Output Directory\nWrite all deliverables to: `{output_dir}`"
            )
        return base

    @classmethod
    def get_instructions(cls) -> str:
        """Return the full system prompt as the agent would see it at runtime.

        Composes core + tools + failure base sections with worker-specific
        markdown and the runtime extras (date, OS, restricted builtins,
        agent ID) that ``get_worker_agent`` generates via
        ``get_instructions_extras``.

        Returns:
            The complete system prompt string.
        """
        from aria.llm import get_instructions_extras

        extras = get_instructions_extras(agent_name="worker")
        return cls.get_system_prompt(extras=extras)


def get_worker_agent(
    llm: LLM,
    extras: str | None = None,
    output_dir: str | None = None,
) -> WorkerAgent:
    """Create a WorkerAgent with plan, scratchpad, file, and ax tools."""
    from aria.tools.registry import CORE, FILES, WORKER_AX

    tools = get_tools([CORE, FILES, WORKER_AX])

    logger.debug(f"Creating WorkerAgent with {len(tools)} tools")

    return WorkerAgent(
        name="Worker",
        description="Background worker for complex tasks.",
        tools=tools,
        llm=llm,
        system_prompt=WorkerAgent.get_system_prompt(
            extras=extras, output_dir=output_dir
        ),
        streaming=False,
        verbose=False,
    )
