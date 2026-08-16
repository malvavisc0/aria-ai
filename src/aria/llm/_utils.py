"""Miscellaneous utility helpers for agent identity and instruction context."""

import os
import platform
import uuid
from datetime import datetime
from pathlib import Path

from loguru import logger

from aria.config.api import Lightpanda
from aria.config.api import Vllm as VllmConfig
from aria.config.folders import Workspace
from aria.config.models import Chat as ChatConfig


def _default_shell() -> str:
    """Return the user's configured default shell name."""
    shell_path = os.environ.get("SHELL")
    if not shell_path:
        try:
            import pwd

            shell_path = pwd.getpwuid(os.getuid()).pw_shell
        except (ImportError, KeyError):
            return "unknown"
    return Path(shell_path).name or "unknown"


def _gpu_line() -> str | None:
    """Return a compact GPU summary, or None when no NVIDIA GPU is detected."""
    from aria.helpers.nvidia import detect_gpus_with_details

    gpus = detect_gpus_with_details()
    if not gpus:
        return None
    devices = ", ".join(
        f"{gpu.name} ({gpu.total_memory / 1024:g} GiB VRAM)" for gpu in gpus
    )
    return f"- **GPU**: {devices}"


def generate_agent_id(agent_name: str) -> str:
    """Generate a unique, human-readable identifier for an agent.

    The generated ID is deterministic in shape but random in value:

    ``{agent_name}_{8-hex-chars}``

    Args:
        agent_name: Prefix identifying the agent.

    Returns:
        A unique agent ID string.
        Example: ``"aria_1a2b3c4d"``.
    """
    return f"{agent_name}_{uuid.uuid4().hex[:8]}"


def get_instructions_extras(agent_name: str, add_agent_id: bool = True) -> str:
    """
    Generates a formatted string containing additional information for
    instructions.

    This provides the agent with runtime context:
    - Current date and time with the system's timezone
    - Host operating system name and version
    - Default shell and workspace directory
    - Detected NVIDIA GPUs
    - Vision and browser availability
    - Output-token and tool-call limits
    - A unique ID generated for the agent (if add_agent_id is True)
    - Managed binaries on $PATH, and a hint for venv CLI extras

    Args:
        agent_name (str): The name of the agent, used for generating a unique
            agent ID.
        add_agent_id (bool): Whether to include the unique agent ID in the
            output string. Defaults to True.

    Returns:
        str: A formatted string containing the current date, time, timezone,
            host information, and optionally agent ID.
    """

    def _ordinal_suffix(day: int) -> str:
        # 11th, 12th, 13th are special-cased.
        if 11 <= (day % 100) <= 13:
            return "th"
        return {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")

    timestamp = datetime.now()
    host = f"{platform.system()} {platform.release()}"

    day = timestamp.day
    date_str = (
        f"{timestamp.strftime('%B')} {day}{_ordinal_suffix(day)} {timestamp.year}"
    )

    tz = timestamp.astimezone().tzinfo

    shell_name = _default_shell()

    # Include generation token budget so the model is aware of its limit.
    max_tok = VllmConfig.max_tokens

    # Include iteration budget so the agent can self-regulate tool usage.
    max_iter = ChatConfig.max_iteration

    # Vision support — so the agent knows if it can analyze images.
    vision = VllmConfig.vision_enabled

    # Browser availability — so the agent knows if browser tools work.
    browser = Lightpanda.is_available()

    # Workspace path so agents know their default operating directory
    workspace_path = str(Workspace.path)

    lines: list[str] = [
        "Runtime context (internal reference — do not reproduce it in replies):",
        "",
        f"- **Date**: {date_str} {timestamp.strftime('%H:%M')} ({tz})",
        f"- **System OS**: {host}",
        f"- **Shell**: {shell_name}",
        f"- **Workspace**: `{workspace_path}` (default directory for file and shell operations)",
    ]
    gpu_line = _gpu_line()
    if gpu_line:
        lines.append(gpu_line)
    lines.extend(
        [
            f"- **Vision Support**: {'yes' if vision else 'no'} | **Browser Access**: {'yes' if browser else 'no'}",
            f"- **Limits**: {max_tok} output tokens, {max_iter} tool calls per response",
        ]
    )
    if add_agent_id:
        lines.append(f"- **Agent ID**: {generate_agent_id(agent_name)}")

    for line in (_managed_binaries_line(), _venv_line()):
        if line:
            lines.append(line)

    return "\n".join(lines)


def _managed_binaries_line() -> str | None:
    """Return a bullet listing Aria-managed binaries, or None on IO error.

    The binaries directory is created during init; this only reads it.
    """
    from aria.config.folders import Bin

    bin_path = Bin.path
    try:
        if not bin_path.exists():
            return None
        installed = sorted(
            f.name
            for f in bin_path.iterdir()
            if f.is_file() and not f.name.startswith(".")
        )
    except OSError as e:
        logger.warning(f"Failed to list managed binaries: {e}")
        return None

    listing = f" — {', '.join(installed)}" if installed else ""
    return f"- **Managed binaries**: `{bin_path}` (on $PATH){listing}"


def _venv_line() -> str | None:
    """Return the venv-CLIs hint bullet, or None when no venv extras exist.

    The full categorized list stays on demand: available via
    ``ax check extras``.
    """
    from aria.cli.extras import venv_extras_available

    try:
        if venv_extras_available():
            return (
                "- **Venv CLIs**: extra CLI tools are installed in the active "
                "venv — list via `ax check extras`."
            )
    except OSError as e:
        logger.warning(f"Failed to list venv extras: {e}")
    return None
