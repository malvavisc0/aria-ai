"""Fetch cited URLs server-side and build content-backed side-panel elements.

Chainlit's SQLAlchemy data layer stores external ``url=`` verbatim (no
mirroring), so the browser must fetch it — CORS blocks most hosts (red
"error occurred while loading the content" boxes) and permissive hosts dump
raw HTML into the side panel. Content-backed elements are instead uploaded
to local storage and served same-origin, which always renders.

Fetches happen here, server-side, with an SSRF guard: only public http(s)
hosts are fetched, and redirect targets are re-validated. Any failure
(timeout, non-200, oversized body, private host, unsupported content type)
skips the citation silently — the answer's markdown link stays clickable.
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import re
import socket
from typing import Any
from urllib.parse import urljoin, urlsplit

import chainlit as cl
import httpx
from bs4 import BeautifulSoup
from markdownify import markdownify

logger = logging.getLogger(__name__)

MAX_CITATIONS = 5
_MAX_BODY_BYTES = 5 * 1024 * 1024
_MAX_TEXT_CHARS = 30_000
_MAX_REDIRECTS = 5
_DEADLINE = 10.0  # overall per-citation budget: DNS + redirects + body
_TIMEOUT = httpx.Timeout(8.0, connect=3.0)
_HEADERS = {"User-Agent": "aria-ai/1.0 (citation fetch)"}
_CHARSET_RE = re.compile(r"charset=([\w.-]+)", re.IGNORECASE)
_NAT64_WELL_KNOWN = ipaddress.ip_network("64:ff9b::/96")


async def build_citation_elements(refs: list[tuple[str, str]]) -> list[Any]:
    """Fetch each ``(name, url)`` ref and return content-backed elements.

    Order follows ``refs``; failed fetches are dropped silently.
    """
    async with httpx.AsyncClient(
        timeout=_TIMEOUT, headers=_HEADERS, follow_redirects=False
    ) as client:
        results = await asyncio.gather(*(_build_one(client, n, u) for n, u in refs))
    return [element for element in results if element is not None]


async def _build_one(client: httpx.AsyncClient, name: str, url: str) -> Any | None:
    """Fetch one ref and convert it to an element, or None on any failure.

    Every failure mode — fetch, deadline, conversion, element construction —
    degrades to None: a broken citation must never lose the answer it cites.
    """
    try:
        fetched = await asyncio.wait_for(_fetch(client, url), timeout=_DEADLINE)
        if fetched is None:
            logger.debug(f"Citation fetch failed for {url}")
            return None
        return await _to_element(name, *fetched)
    except Exception as exc:
        logger.debug(f"Citation skipped for {url}: {exc}")
        return None


async def _fetch(client: httpx.AsyncClient, url: str) -> tuple[str, bytes, str] | None:
    """GET ``url`` following up to 5 redirects; each hop is re-validated.

    Returns ``(final_url, body, content_type)`` or None when the URL is not
    fetchable (non-public host, bad status, body over the size cap).
    """
    for _ in range(_MAX_REDIRECTS + 1):
        if not await _is_public_http(url):
            return None
        async with client.stream("GET", url) as resp:
            if resp.is_redirect:
                location = resp.headers.get("location")
                if not location:
                    return None
                url = urljoin(str(resp.url), location)
                continue
            if resp.status_code != 200:
                return None
            body = bytearray()
            async for chunk in resp.aiter_bytes(65536):
                body.extend(chunk)
                if len(body) > _MAX_BODY_BYTES:
                    return None
            return str(resp.url), bytes(body), resp.headers.get("content-type", "")
    return None


async def _is_public_http(url: str) -> bool:
    """True only for http(s) URLs whose hostname resolves to global IPs."""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return False
    try:
        infos = await asyncio.to_thread(socket.getaddrinfo, parts.hostname, None)
    except socket.gaierror:
        return False
    addrs = {str(info[4][0]) for info in infos}
    try:
        return bool(addrs) and all(_ip_is_global(a) for a in addrs)
    except ValueError:
        return False


def _ip_is_global(addr: str) -> bool:
    """True for globally routable addresses, NAT64-embedded private IPv4 excluded."""
    ip = ipaddress.ip_address(addr)
    if ip in _NAT64_WELL_KNOWN:
        return ipaddress.ip_address(ip.packed[-4:]).is_global
    return ip.is_global


async def _to_element(
    name: str, url: str, body: bytes, content_type: str
) -> Any | None:
    """Map a fetched body to a Pdf or Text element by content type."""
    ct = content_type.split(";", 1)[0].strip().lower()
    pdf_by_extension = urlsplit(url).path.lower().endswith(".pdf")
    if ct == "application/pdf" or (
        pdf_by_extension and ct in ("application/octet-stream", "")
    ):
        return cl.Pdf(name=name, content=body, display="side")
    if ct == "text/html":
        # markdownify is sync CPU-bound work; keep it off the event loop.
        text, title = await asyncio.to_thread(_parse_html, body, content_type, url)
        name = title or name
    elif ct.startswith("text/"):
        text = _decode(body, content_type)
    else:
        return None
    return _text_element(name, text)


def _parse_html(body: bytes, content_type: str, url: str) -> tuple[str, str | None]:
    """Convert a web page to (main-content markdown, page title).

    ``<article>``/``<main>`` isolates the substance (README, wiki page) from
    site chrome — nav menus, sign-in links, sidebars — that otherwise fills
    the citation panel and renders as stray indented code blocks. The
    ``<title>`` makes a far better element name than a URL path segment.
    Relative ``href``/``src`` are absolutized against ``url``.
    """
    soup = BeautifulSoup(_decode(body, content_type), "html.parser")
    title = " ".join(soup.title.get_text(" ", strip=True).split()) if soup.title else ""
    if len(title) > 70:
        title = title[:69].rstrip() + "…"
    main = soup.find("article") or soup.find("main") or soup.body or soup
    _absolutize_links(main, url)
    return markdownify(str(main)), title or None


def _absolutize_links(main: Any, url: str) -> None:
    """Resolve relative href/src against the page URL, in place.

    Otherwise they point at the chainlit host and 404 in the side panel.
    """
    for tag in main.find_all(["a", "img"]):
        attr = "href" if tag.name == "a" else "src"
        value = tag.get(attr, "")
        if (
            isinstance(value, str)
            and value
            and not value.startswith(("#", "data:", "mailto:"))
        ):
            tag[attr] = urljoin(url, value)


def _decode(body: bytes, content_type: str) -> str:
    """Decode bytes using the charset from the content-type header."""
    match = _CHARSET_RE.search(content_type)
    try:
        encoding = match.group(1) if match else "utf-8"
        return body.decode(encoding, errors="replace")
    except LookupError:
        return body.decode("utf-8", errors="replace")


def _text_element(name: str, text: str) -> Any | None:
    """Build a markdown Text element; empty results are skipped."""
    text = text.strip()
    if not text:
        return None
    if len(text) > _MAX_TEXT_CHARS:
        text = text[:_MAX_TEXT_CHARS] + "\n\n…"
    # No language hint: chainlit wraps content in a code fence when
    # ``language`` is set (source view); without it the markdown renders.
    return cl.Text(name=name, content=text, display="side")
