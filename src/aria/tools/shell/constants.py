"""Shell execution constants.

This module provides timeout limits and command whitelists for safe
shell command execution.
"""

import os
from pathlib import Path

from aria.config.folders import Workspace

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
