"""Canonical path definitions for all Aria runtime directories.

All runtime-managed data lives under ``~/.aria`` by default.  The layout
is::

    ~/.aria/
    ├── workspace/   agent-facing workspace (file tool BASE_DIR)
    │   └── uploads/ user-uploaded files (raw + converted markdown)
    ├── bin/         downloaded binaries (lightpanda, docling shim, etc.)
    ├── venvs/       isolated tool venvs (vllm, docling)
    ├── logs/        all runtime logs (debug, tool-calls, vllm, processes, workers)
    ├── models/      downloaded model files
    ├── db/          sqlite, chromadb
    ├── storage/     local file storage (Chainlit elements)
    ├── workers/     worker agent state
    └── ...

The ``ARIA_HOME`` environment variable can override the root
(``~/.aria``) for advanced or containerised deployments.
"""

import os
import sys
from pathlib import Path

_ARIA_HOME = Path(os.environ.get("ARIA_HOME", Path.home() / ".aria")).resolve()


class Data:
    """Root of all Aria runtime data."""

    path = _ARIA_HOME


class Workspace:
    """Agent-facing workspace root (file tools default directory)."""

    path = _ARIA_HOME / "workspace"


class Bin:
    """Downloaded binaries managed by Aria."""

    path = _ARIA_HOME / "bin"


class Venvs:
    """Isolated Python virtual environments managed by Aria.

    Heavy tool stacks that would pollute Aria's own dependency tree
    (e.g. vLLM's CUDA/PyTorch wheels) are installed here instead of
    into Aria's ``.venv``.  Aria never imports these tools — it only
    shells out to the isolated interpreter.
    """

    path = _ARIA_HOME / "venvs"
    vllm = path / "vllm"
    docling = path / "docling"


class Debug:
    """Runtime log files."""

    path = _ARIA_HOME / "logs"
    logs_path = path / "debug.log"
    startup_error_path = path / "startup-error.txt"


# Shared loguru sink format for debug.log — the GUI and web processes
# write to the same file, so their formats must stay identical for the
# Logs tab parser.
LOG_FORMAT = "{time:YYYY-MM-DD HH:mm:ss} - {level} - {name}.{function} : {message}"


class Storage:
    """Local file storage for Chainlit elements."""

    path = _ARIA_HOME / "storage"


class DB:
    """Database files (SQLite, ChromaDB)."""

    path = _ARIA_HOME / "db"


class Models:
    """Downloaded model files and caches."""

    path = _ARIA_HOME / "models"


class Knowledge:
    """User-curated documents directory for the knowledge hub (mini-RAG)."""

    path = _ARIA_HOME / "knowledge"


def get_augmented_path() -> str:
    """Return ``PATH`` with ``~/.aria/bin`` and the current venv bin prepended.

    Used by shell tools, process tools, and server managers to ensure
    Aria-managed binaries are discoverable in every subprocess.
    """
    paths: list[str] = []

    # Aria-managed binaries — create dir so downloads always have a target
    Bin.path.mkdir(parents=True, exist_ok=True)
    paths.append(str(Bin.path))

    # Current Python environment's bin directory
    python_bin = os.path.join(sys.prefix, "Scripts" if os.name == "nt" else "bin")
    if os.path.isdir(python_bin):
        paths.append(python_bin)

    # Existing PATH
    paths.append(os.environ.get("PATH", ""))

    return os.pathsep.join(paths)


def get_augmented_env() -> dict[str, str]:
    """Return a copy of ``os.environ`` with an augmented ``PATH``."""
    env = dict(os.environ)
    env["PATH"] = get_augmented_path()
    return env
