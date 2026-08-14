"""Turn LLM answer text into Chainlit render elements.

This module handles the conversion of agent answer text into Chainlit
renderable elements (images, PDFs, text files, etc.).

Remote URLs are never handed to the frontend as ``url=`` (except images,
which ``<img>`` loads without CORS): the data layer stores external URLs
verbatim, so the browser would have to fetch them — CORS blocks most hosts
and permissive hosts dump raw HTML into the side panel. Cited URLs are
fetched server-side (see ``citations``) and attached by content.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, NamedTuple
from urllib.parse import urlsplit

import chainlit as cl

from aria.web.citations import MAX_CITATIONS, build_citation_elements


class CitationRef(NamedTuple):
    """A URL cited in the answer.

    ``name`` is the markdown link text when present and not itself a URL
    (e.g. "CachyOS wiki page"), else None.
    """

    name: str | None
    url: str


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
LINK_RE = re.compile(r"\[([^\]]*)\]\(([^)]+)\)")

# Any bare http(s) URL in the answer is a citation candidate — models cite
# sources as bare/bare-bold URLs at least as often as markdown links.
# Parentheses are allowed in the match (Wikipedia-style URLs); trailing
# unbalanced ones are trimmed at cleanup.
BARE_URL_RE = re.compile(r"https?://[^\s<>\[\]\"'`]+")

# Fenced code blocks: URLs inside are documentation examples, not
# citations — excluded from the bare pass. (Inline backtick spans stay
# eligible: backticked URLs were always citation candidates.)
FENCE_RE = re.compile(r"```[\s\S]*?```")

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


def _link_name(raw: str) -> str | None:
    """Normalize markdown link text for use as an element name."""
    name = " ".join(raw.split())
    if not name or name.startswith(("http://", "https://", "/")):
        return None
    return name[:80]


def _fallback_name(url: str) -> str:
    """Element name from the URL path segment, else its hostname."""
    parts = urlsplit(url)
    return Path(parts.path).name or parts.hostname or url


def _trim_bare_url(text: str, match: re.Match[str]) -> str:
    """Clean a bare-URL regex match of surrounding markdown/punctuation.

    Sentence punctuation is trimmed first (it may follow an emphasis
    wrapper: ``**url**.``), ``**url**``/``__url__``/``*url*`` wrappers are
    stripped only when the opening marker precedes the match (so legit
    trailing ``*``/``_`` survive), and a trailing ``)`` is removed only
    while parentheses are unbalanced (preserving Wikipedia-style URLs).
    """
    url = match.group(0).rstrip(".,;:!?")
    for marker in ("**", "__", "*"):
        if text[
            max(0, match.start() - len(marker)) : match.start()
        ] == marker and url.endswith(marker):
            url = url[: -len(marker)]
            break
    while url.endswith(")") and url.count(")") > url.count("("):
        url = url[:-1]
    return url


def extract_renderable_items(text: str) -> tuple[list[str], list[CitationRef]]:
    """Extract local paths and remote URLs from agent answer text.

    Only matches paths that are unambiguous — i.e. backtick-wrapped, inside
    a markdown link, or on their own line. Bare paths embedded in prose are
    ignored to avoid false positives. Every http(s) URL in the answer
    (markdown link, backtick-wrapped, or bare) is a citation candidate.

    Returns:
        ``(paths, refs)`` — local file paths (expanded) and remote URLs as
        ``CitationRef`` (markdown links carry their link text as ``name``).
        Only paths that exist on disk are returned.
    """
    raw_targets: list[CitationRef] = []

    # 1. Markdown links [text](target) — first, so their link text wins
    #    the name when a bare/duplicate match follows.
    for m in LINK_RE.finditer(text):
        raw_targets.append(CitationRef(_link_name(m.group(1)), m.group(2)))

    # 2. Backtick-wrapped or standalone paths
    for m in BACKTICK_PATH_RE.finditer(text):
        raw_targets.append(CitationRef(None, m.group(1)))
    for m in STANDALONE_PATH_RE.finditer(text):
        raw_targets.append(CitationRef(None, m.group(1)))

    # 3. Bare URLs anywhere in the answer (fenced code blocks excluded —
    #    URLs there are documentation examples, not citations).
    bare_text = FENCE_RE.sub(" ", text)
    for m in BARE_URL_RE.finditer(bare_text):
        raw_targets.append(CitationRef(None, _trim_bare_url(bare_text, m)))

    paths: list[str] = []
    refs: list[CitationRef] = []
    seen: set[str] = set()
    for ref in raw_targets:
        target = ref.url
        if target in seen:
            continue
        seen.add(target)
        if target.startswith(("http://", "https://")):
            refs.append(ref)
        else:
            expanded = str(Path(target).expanduser())
            if Path(expanded).is_file():
                paths.append(expanded)
    return paths, refs


def sources_footer(names: list[str]) -> str:
    """Trailing ``**Sources:**`` line giving one chainlit reference chip
    per citation element (chips render where a side element's name occurs
    in the message text — here, exactly once, in this footer)."""
    return "\n\n**Sources:** " + " · ".join(names) if names else ""


def _local_element(path: str) -> Any:
    """Chainlit element for a local file, chosen by extension."""
    ext = Path(path).suffix.lower()
    name = Path(path).name
    if ext in _IMAGE_EXTS:
        return cl.Image(name=name, path=path, display="inline")
    if ext in _PDF_EXTS:
        return cl.Pdf(name=name, path=path, display="side")
    if ext in _TEXT_EXTS:
        return cl.Text(
            name=name, path=path, display="side", language=LANG_MAP.get(ext, "")
        )
    return cl.File(name=name, path=path, display="side")


async def create_render_elements(
    paths: list[str], refs: list[CitationRef]
) -> tuple[list[Any], list[str]]:
    """Build Chainlit elements for the given paths and refs.

    - Local images → ``cl.Image`` inline; PDFs → ``cl.Pdf``; text/code →
      ``cl.Text`` (with language hint); anything else → ``cl.File``
    - Remote image URLs → ``cl.Image`` inline (``<img>`` has no CORS issue)
    - Other remote URLs → fetched server-side and attached by content
      (capped at ``MAX_CITATIONS``; see ``citations``)

    Returns ``(elements, citation_names)`` — the citation element names,
    for building a ``**Sources:**`` footer via :func:`sources_footer`.
    """
    elements: list[Any] = [_local_element(p) for p in paths]
    citations: list[tuple[str, str]] = []
    for ref in refs:
        ext = Path(ref.url.split("?")[0]).suffix.lower()
        if ext in _IMAGE_EXTS:
            name = ref.name or _fallback_name(ref.url)
            elements.append(cl.Image(name=name, url=ref.url, display="inline"))
        elif len(citations) < MAX_CITATIONS:
            citations.append((ref.name or _fallback_name(ref.url), ref.url))
    citation_elements = await build_citation_elements(citations)
    elements.extend(citation_elements)
    names = [getattr(e, "name", "") for e in citation_elements]
    return elements, [n for n in names if n]
