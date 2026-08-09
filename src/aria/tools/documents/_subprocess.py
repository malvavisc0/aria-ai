"""Subprocess bridge to the isolated pdf-vlm worker. Never imports docling."""

import json
import subprocess
from pathlib import Path
from typing import Any

from aria.config.folders import Bin


def convert(
    pdf_path: Path,
    *,
    output_path: Path,
    model_id: str,
    device: str,
    max_pages: int,
    timeout: int,
) -> dict[str, Any]:
    """Run the pdf-vlm worker to convert *pdf_path* to markdown.

    Returns the worker's JSON result (``{"ok": bool, ...}``) or an error
    dict. Never imports heavy deps.
    """
    shim = Bin.path / "pdf-vlm"
    if not shim.exists():
        return {"ok": False, "error": "pdf-vlm worker not installed"}
    cmd = [
        str(shim),
        "convert",
        "--input",
        str(pdf_path),
        "--output",
        str(output_path),
        "--model",
        model_id,
        "--device",
        device,
        "--max-pages",
        str(max_pages),
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"timeout after {timeout}s"}
    if proc.returncode != 0:
        # The worker may have printed a JSON error dict on a failing exit
        # (e.g. max-pages exceeded); surface its `error` instead of the blob.
        parsed = _parse_stdout(proc.stdout)
        if parsed is not None:
            return {"ok": False, "error": parsed.get("error", proc.stdout.strip())}
        return {"ok": False, "error": (proc.stderr or proc.stdout).strip()}
    parsed = _parse_stdout(proc.stdout)
    if parsed is None:
        return {"ok": False, "error": f"worker returned non-JSON: {proc.stdout[:200]}"}
    return parsed


def _parse_stdout(raw: str) -> dict[str, Any] | None:
    """Parse the last JSON object from worker stdout.

    ML libraries (docling, torch, HF Hub) may print warnings/progress to
    stdout. We scan backwards for the last line that looks like a JSON
    object so incidental output before the result is tolerated.
    """
    for line in reversed(raw.strip().splitlines()):
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            return obj
    return None
