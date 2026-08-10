"""Utility functions for agents instructions.

This module provides shared utility functions used across multiple agents
to reduce code duplication and ensure consistent behavior.
"""

import re
from pathlib import Path

INSTRUCTIONS_DIR = Path(__file__).parent
BASE_SECTIONS_DIR = INSTRUCTIONS_DIR / "base"

# All available base section names, in load order.
ALL_BASE_SECTIONS: list[str] = [
    "core",
    "tools",
    "failure",
]

# Matches any remaining ``{{KEY}}`` placeholder after substitution.
_PLACEHOLDER_RE = re.compile(r"\{\{[^}]+\}\}")


def load_agent_instructions(
    agent_name: str,
    extras: str | None = None,
    variables: dict[str, str] | None = None,
    base_sections: list[str] | None = None,
) -> str:
    """Load agent instructions from a markdown file.

    Assembly order: agent identity first, then shared base sections,
    then runtime extras. This ensures the model knows *who* it is
    before absorbing operational rules.

    Args:
        agent_name: The name of the agent, used to find the instruction file
            (e.g., "aria", "prompt_enhancer").
        extras: Additional instructions to append to the prompt.
            Defaults to empty string.
        variables: Optional mapping used for ``{{KEY}}`` template
            substitution in loaded instruction content.
            Defaults to None.
        base_sections: Which modular base sections to include.
            Each entry must be a name from ``ALL_BASE_SECTIONS``
            (e.g. ``["core", "tools"]``).
            ``None`` loads every section (backward-compatible default).

    Returns:
        The system prompt as a string.

    Example:
        >>> prompt = load_agent_instructions("aria", "Focus on brevity")
        >>> prompt = load_agent_instructions("prompt_enhancer")
        >>> prompt = load_agent_instructions(
        ...     "worker", base_sections=["core", "tools"]
        ... )
    """
    parts = []

    instructions_path = INSTRUCTIONS_DIR / f"{agent_name}.md"
    if instructions_path.exists():
        # Agent identity and persona first
        with open(instructions_path, encoding="utf-8") as file:
            parts.append(file.read())

        # Then shared operational rules
        if agent_name != "base":
            sections_to_load = (
                base_sections if base_sections is not None else ALL_BASE_SECTIONS
            )
            for section in sections_to_load:
                section_path = BASE_SECTIONS_DIR / f"{section}.md"
                if section_path.exists():
                    with open(section_path, encoding="utf-8") as file:
                        parts.append(file.read())

    # Substitute {{KEY}} on identity + base sections only (before extras are
    # appended) so runtime-context text is never subject to variable
    # replacement.
    resident = "\n\n".join(parts)
    if variables:
        for key, value in variables.items():
            resident = resident.replace(f"{{{{{key}}}}}", value)

    # Fail loudly on unresolved placeholders rather than shipping a literal
    # ``{{TYPO}}`` into a live prompt.
    unresolved = _PLACEHOLDER_RE.findall(resident)
    if unresolved:
        raise ValueError(
            f"Unresolved instruction placeholders: {unresolved}. "
            f"Provide them via the 'variables' argument."
        )

    if extras:
        return resident + f"\n\n## Runtime Context\n\n{extras}"
    return resident
