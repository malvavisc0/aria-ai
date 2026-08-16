"""Prompt Enhancer Agent

This module defines a specialized agent for enhancing and optimizing prompts
to maximize effectiveness when interacting with AI systems. The agent applies
prompt engineering best practices to improve clarity, specificity, and overall
quality of user prompts.
"""

from llama_index.core.agent import FunctionAgent
from llama_index.core.llms import LLM
from pydantic import BaseModel, Field

from aria.agents.instructions import load_agent_instructions


class PromptEnhancementResult(BaseModel):
    """Data model for storing prompt enhancement results.

    This model captures both the original prompt and its enhanced version,
    along with a rationale explaining the enhancement decisions made.
    """

    original: str = Field(description="Exact user input (unchanged)")
    enhanced: str = Field(description="Improved version of the prompt")
    rationale: str = Field(
        description="One paragraph explaining changes (with no formatting)"
    )


class PromptEnhancerAgent(FunctionAgent):
    """
    A specialized agent for enhancing prompts for better AI responses.

    This agent extends FunctionAgent to provide prompt engineering
    capabilities including clarity improvement, context enrichment, and
    structural optimization. It transforms basic prompts into well-crafted
    instructions that elicit higher quality responses from AI systems.
    """

    @staticmethod
    def get_system_prompt(extras: str = "") -> str:
        """
        Return the system prompt for the Prompt Enhancer Agent.

        Args:
            extras (str): Additional instructions to append to the system
                         prompt. Defaults to empty string.

        Returns:
            str: The complete system prompt with guidelines and best practices
        """
        return load_agent_instructions(
            "prompt_enhancer",
            extras,
            base_sections=[],
        )

    @classmethod
    def get_instructions(cls) -> str:
        """Return the full system prompt as the agent would see it at runtime.

        Uses the shared ``get_instructions_extras`` helper but strips
        sections irrelevant to the enhancer (managed binaries, venv
        commands) since it never executes commands.

        Returns:
            The complete system prompt string.
        """
        from aria.llm import get_instructions_extras

        extras = cls._strip_irrelevant_extras(
            get_instructions_extras(agent_name="prompt_enhancer")
        )
        return cls.get_system_prompt(extras=extras)

    @staticmethod
    def _strip_irrelevant_extras(extras: str) -> str:
        """Remove runtime context lines the enhancer doesn't need.

        Strips the managed-binaries and venv-CLIs bullets since the prompt
        enhancer never executes commands.
        """
        import re

        pattern = re.compile(
            r"^- \*\*(?:Managed binaries|Venv CLIs)\*\*:.*\n?", re.MULTILINE
        )
        return pattern.sub("", extras).strip()


def get_agent(
    llm: LLM,
) -> PromptEnhancerAgent:
    """Create a prompt enhancer agent with the given LLM.

    Uses ``get_instructions_extras`` to inject full runtime context
    (date, OS, shell, workspace, vision, browser, max tokens, max
    iterations, agent ID, managed binaries, venv commands).

    Args:
        llm: The language model to use for the agent.

    Returns:
        A configured PromptEnhancerAgent instance.
    """
    from aria.llm import get_instructions_extras

    tools = []

    agent = PromptEnhancerAgent(
        name="Prompt Enhancer",
        description=(
            "Specialized in enhancing prompts for better AI responses. "
            "Improves clarity, specificity, and effectiveness of prompts "
            "using prompt engineering best practices."
        ),
        tools=tools,
        llm=llm,
        system_prompt=PromptEnhancerAgent.get_system_prompt(
            extras=PromptEnhancerAgent._strip_irrelevant_extras(
                get_instructions_extras(agent_name="prompt_enhancer")
            )
        ),
        streaming=False,
        verbose=False,
        output_cls=PromptEnhancementResult,
    )

    return agent
