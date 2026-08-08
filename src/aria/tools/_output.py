"""Shared tool output persistence helpers.

Tools that produce large output write it to a file under ``BASE_DIR`` and
return the path, so the agent can read it in chunks via ``read_file``.

This module owns the file layout, naming convention, and retention cleanup
so individual tools don't reimplement the same pattern.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta
from pathlib import Path

from aria.tools.constants import BASE_DIR

# Retention: files older than this are pruned on each write.
_RETENTION_DAYS = 7


def write_tool_output(tool: str, suffix: str, content: str) -> str:
    """Write *content* to a timestamped file and return the path.

    Args:
        tool: Tool name (used as subdirectory under ``BASE_DIR``).
        suffix: Filename suffix (e.g. ``"stdout"``).
        content: Text to persist.

    Returns:
        Absolute path to the written file.
    """
    output_dir = BASE_DIR / f"{tool}_output"
    output_dir.mkdir(parents=True, exist_ok=True)

    digest = hashlib.sha1(
        f"{datetime.now().isoformat()}{len(content)}".encode("utf-8")
    ).hexdigest()[:8]
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = output_dir / f"{ts}_{suffix}_{digest}.txt"
    path.write_text(content, encoding="utf-8")

    _cleanup_old_files(output_dir)
    return str(path)


def _cleanup_old_files(directory: Path, days: int = _RETENTION_DAYS) -> None:
    """Delete files in *directory* older than *days*.

    Runs inline after each write — cheap because the directory only
    contains files from a single tool and the stat call is fast.
    """
    cutoff = datetime.now() - timedelta(days=days)
    for file in directory.iterdir():
        if file.is_file():
            mtime = datetime.fromtimestamp(file.stat().st_mtime)
            if mtime < cutoff:
                file.unlink(missing_ok=True)
