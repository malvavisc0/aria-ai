"""Turn LLM answer text into Chainlit render elements.

This module handles the conversion of agent answer text into Chainlit
renderable elements (images, PDFs, text files, etc.).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import chainlit as cl

# Backtick-wrapped paths: `~/foo.md` or `/tmp/bar.py`
BACKTICK_PATH_RE = re.compile(
    r"`((?:~/|/)[^`]+\."
    r"(?:md|txt|rst|py|js|ts|json|csv|html?|css|ya?ml|toml|xml|log|sh|tex"
    r"|sql|go|rs|c|cpp|java|rb"
    r"|png|jpe?g|gif|webp|svg|pdf|wav|mp3|mp4))`"
)

# Paths on their own line (optionally after a label like "File:" or "Path:").
STANDALONE_PATH_RE = re.compile(
    r"^\s*(?:\w[\w\s]*:\s*)?((?:~/|/)\S+\."
    r"(?:md|txt|rst|py|js|ts|json|csv|html?|css|ya?ml|toml|xml|log|sh|tex"
    r"|sql|go|rs|c|cpp|java|rb"
    r"|png|jpe?g|gif|webp|svg|pdf|wav|mp3|mp4))\s*$",
    re.MULTILINE,
)

# Markdown link targets: [text](path-or-url)
LINK_RE = re.compile(r"\[[^\]]*\]\(([^)]+)\)")

# Backtick-wrapped or standalone URLs ending in a renderable extension.
BACKTICK_URL_RE = re.compile(
    r"`(https?://[^`]+\.(?:png|jpe?g|gif|webp|svg|pdf|md|txt))`"
)
STANDALONE_URL_RE = re.compile(
    r"^\s*(https?://\S+\.(?:png|jpe?g|gif|webp|svg|pdf|md|txt))\s*$",
    re.MULTILINE,
)

_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"}
_PDF_EXTS = {".pdf"}
_TEXT_EXTS = {
    ".md",
    ".txt",
    ".rst",
    ".py",
    ".js",
    ".ts",
    ".json",
    ".csv",
    ".yaml",
    ".yml",
    ".toml",
    ".xml",
    ".log",
    ".sh",
    ".css",
    ".html",
    ".htm",
    ".tex",
    ".sql",
    ".go",
    ".rs",
    ".c",
    ".cpp",
    ".java",
    ".rb",
}

# Language hint for cl.Text per extension (for syntax highlighting).
LANG_MAP: dict[str, str] = {
    ".py": "python",
    ".js": "javascript",
    ".ts": "typescript",
    ".json": "json",
    ".csv": "csv",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "toml",
    ".xml": "xml",
    ".sh": "bash",
    ".css": "css",
    ".html": "html",
    ".htm": "html",
    ".tex": "latex",
    ".sql": "sql",
    ".go": "go",
    ".rs": "rust",
    ".c": "c",
    ".cpp": "cpp",
    ".java": "java",
    ".rb": "ruby",
}


def extract_renderable_items(text: str) -> tuple[list[str], list[str]]:
    """Extract local paths and remote URLs from agent answer text.

    Only matches paths/URLs that are unambiguous — i.e. backtick-wrapped,
    inside a markdown link, or on their own line. Bare paths embedded in
    prose are ignored to avoid false positives.

    Returns:
        ``(paths, urls)`` — local file paths (expanded) and remote URLs.
        Only paths that exist on disk are returned.
    """
    raw_targets: list[str] = []

    # 1. Markdown links [text](target)
    for m in LINK_RE.finditer(text):
        raw_targets.append(m.group(1))

    # 2. Backtick-wrapped paths/URLs
    for m in BACKTICK_PATH_RE.finditer(text):
        raw_targets.append(m.group(1))
    for m in BACKTICK_URL_RE.finditer(text):
        raw_targets.append(m.group(1))

    # 3. Standalone paths/URLs on their own line
    for m in STANDALONE_PATH_RE.finditer(text):
        raw_targets.append(m.group(1))
    for m in STANDALONE_URL_RE.finditer(text):
        raw_targets.append(m.group(1))

    paths: list[str] = []
    urls: list[str] = []
    seen: set[str] = set()
    for target in raw_targets:
        clean = target.strip("`").rstrip(".,;:!?)")
        if clean in seen:
            continue
        seen.add(clean)
        if clean.startswith(("http://", "https://")):
            urls.append(clean)
        else:
            expanded = str(Path(clean).expanduser())
            if Path(expanded).is_file():
                paths.append(expanded)
    return paths, urls


def create_render_elements(paths: list[str], urls: list[str]) -> list[Any]:
    """Build Chainlit elements for the given paths and URLs.

    - Images (.png/.jpg/…) → ``cl.Image``
    - PDFs → ``cl.Pdf``
    - Text/code files → ``cl.Text`` (with language hint)
    - Anything else → ``cl.File`` (download button)
    """
    elements: list[Any] = []
    for p in paths:
        ext = Path(p).suffix.lower()
        name = Path(p).name
        if ext in _IMAGE_EXTS:
            elements.append(cl.Image(name=name, path=p, display="inline"))
        elif ext in _PDF_EXTS:
            elements.append(cl.Pdf(name=name, path=p, display="side"))
        elif ext in _TEXT_EXTS:
            elements.append(
                cl.Text(
                    name=name, path=p, display="side", language=LANG_MAP.get(ext, "")
                )
            )
        else:
            elements.append(cl.File(name=name, path=p, display="side"))
    for u in urls:
        ext = Path(u.split("?")[0]).suffix.lower()
        name = Path(u).name or u
        if ext in _IMAGE_EXTS:
            elements.append(cl.Image(name=name, url=u, display="inline"))
        elif ext in _PDF_EXTS:
            elements.append(cl.Pdf(name=name, url=u, display="side"))
        else:
            elements.append(cl.Text(name=name, url=u, display="side"))
    return elements
