"""Shell execution constants.

This module provides platform detection, timeout limits, and command
whitelists for safe shell command execution.
"""

import os
import platform
from pathlib import Path

from aria.config.folders import Workspace

CURRENT_OS = platform.system().lower()  # windows, linux, darwin
IS_WINDOWS = CURRENT_OS == "windows"
IS_MACOS = CURRENT_OS == "darwin"
IS_LINUX = CURRENT_OS == "linux"


def detect_shell() -> str:
    """Detect the default shell for the current platform.

    Returns:
        The shell name: "powershell", "cmd", "bash", or "zsh".
    """
    if IS_WINDOWS:
        # Check for PowerShell vs CMD
        if os.environ.get("PSMODULEPATH"):
            return "powershell"
        return "cmd"
    elif IS_MACOS:
        return os.environ.get("SHELL", "/bin/zsh")
    else:  # Linux and others
        return os.environ.get("SHELL", "/bin/bash")


SHELL = detect_shell()

MAX_OUTPUT_SIZE = (
    32 * 1024
)  # 32KB — capped further by MAX_TOOL_OUTPUT_CHARS in tool_success_response
MAX_LINE_LENGTH = 10000

BLOCKED_COMMANDS = [
    # System shutdown/reboot — works without root on many desktop systems
    "shutdown",
    "reboot",
    "halt",
    "poweroff",
    # Raw disk operations — can destroy data on accessible devices
    "mkfs",
    "dd",
    "shred",
    "wipe",
    # Package managers — agents must not install/remove packages silently
    "pip",
    "pip3",
    "apt",
    "apt-get",
    "yum",
    "dnf",
    "pacman",
    # Privilege escalation — agents must not attempt to gain root
    "sudo",
    "su",
    "doas",
    "pkexec",
]

# Default working directory for shell commands — the agent workspace.
BASE_DIR = Path(os.environ.get("TOOLS_DATA_FOLDER", str(Workspace.path))).resolve()
BASE_DIR.mkdir(parents=True, exist_ok=True)
