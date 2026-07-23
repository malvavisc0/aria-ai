"""Read and write .env files while preserving comments and ordering."""

from __future__ import annotations

import re
from pathlib import Path

_LINE_RE = re.compile(
    r"^(?P<key>[A-Z_][A-Z0-9_]*)\s*=\s*(?P<value>[^#]*?)"
    r"(?:\s*#\s*(?P<comment>.*))?$"
)


def parse_dotenv(path: Path) -> tuple[dict[str, str], list[str]]:
    """Parse a .env file into ``(values, raw_lines)``.

    ``raw_lines`` preserves comments/blank lines for round-trip writes.
    """
    if not path.exists():
        return {}, []

    values: dict[str, str] = {}
    raw_lines: list[str] = []

    for line in path.read_text(encoding="utf-8").splitlines():
        raw_lines.append(line)
        match = _LINE_RE.match(line)
        if match:
            values[match.group("key")] = match.group("value").strip()

    return values, raw_lines


def _format_existing_line(key: str, new_value: str, comment: str | None) -> str:
    if comment:
        return f"{key} = {new_value}  # {comment}"
    return f"{key} = {new_value}"


def _replace_known_keys(
    raw_lines: list[str], values: dict[str, str]
) -> tuple[list[str], set[str]]:
    out: list[str] = []
    seen: set[str] = set()
    for line in raw_lines:
        match = _LINE_RE.match(line)
        if not match or match.group("key") not in values:
            out.append(line)
            continue
        key = match.group("key")
        seen.add(key)
        out.append(_format_existing_line(key, values[key], match.group("comment")))
    return out, seen


def _append_missing_keys(
    out: list[str], values: dict[str, str], seen: set[str]
) -> list[str]:
    missing = [k for k in values if k not in seen]
    if not missing:
        return out
    if out and out[-1].strip():
        out.append("")
    for key in missing:
        out.append(f"{key} = {values[key]}")
    return out


def write_dotenv(path: Path, values: dict[str, str], raw_lines: list[str]) -> None:
    """Write updated values into a .env while preserving structure.

    Existing key lines are updated in-place (comments stay), unknown lines are
    untouched, and missing keys from ``values`` are appended at the end.
    """
    out, seen = _replace_known_keys(raw_lines, values)
    out = _append_missing_keys(out, values, seen)
    path.write_text("\n".join(out) + "\n", encoding="utf-8")
