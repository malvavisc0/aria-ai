from __future__ import annotations

import asyncio
import socket
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock

import chainlit as cl
import httpx
import pytest

from aria.web import citations


class _FakeResp:
    """Duck-typed httpx streaming response."""

    def __init__(
        self,
        *,
        status: int = 200,
        body: bytes = b"",
        content_type: str | None = "text/html",
        url: str = "https://example.com/",
        location: str | None = None,
    ) -> None:
        self.status_code = status
        self._body = body
        self.url = url
        self.headers: dict[str, str] = {}
        if content_type:
            self.headers["content-type"] = content_type
        if location:
            self.headers["location"] = location

    @property
    def is_redirect(self) -> bool:
        return self.status_code in (301, 302, 303, 307, 308)

    async def aiter_bytes(self, chunk_size: int):
        for i in range(0, len(self._body), chunk_size):
            yield self._body[i : i + chunk_size]


class _FakeStream:
    def __init__(self, resp: _FakeResp) -> None:
        self._resp = resp

    async def __aenter__(self) -> _FakeResp:
        return self._resp

    async def __aexit__(self, *exc: object) -> bool:
        return False


class _FakeClient:
    """Duck-typed httpx.AsyncClient serving canned responses per URL."""

    def __init__(self, responses: dict[str, list[_FakeResp]]) -> None:
        self._responses = responses
        self.seen: list[str] = []

    async def __aenter__(self) -> _FakeClient:
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False

    def stream(self, method: str, url: str) -> _FakeStream:
        self.seen.append(url)
        if url not in self._responses:  # unreachable host → ConnectError
            raise httpx.ConnectError("boom")
        return _FakeStream(self._responses[url].pop(0))


@pytest.fixture
def mock_cl_elements(monkeypatch: pytest.MonkeyPatch) -> None:
    """Mock cl.Text/Pdf so elements don't need a Chainlit context."""
    for name in ("Text", "Pdf"):
        monkeypatch.setattr(cl, name, lambda **kw: SimpleNamespace(**kw))


@pytest.fixture
def allow_all_hosts(monkeypatch: pytest.MonkeyPatch) -> None:
    """Bypass DNS so fetch tests never touch the network."""
    monkeypatch.setattr(citations, "_is_public_http", AsyncMock(return_value=True))


def _as_client(fake: _FakeClient) -> httpx.AsyncClient:
    return cast(httpx.AsyncClient, fake)


class TestIsPublicHttp:
    def _resolve_to(self, monkeypatch: pytest.MonkeyPatch, *ips: str) -> None:
        infos = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 0)) for ip in ips]
        monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: infos)

    async def test_rejects_loopback(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._resolve_to(monkeypatch, "127.0.0.1")
        assert not await citations._is_public_http("http://localhost:9090/v1")

    async def test_rejects_private_ranges(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        for ip in ("10.1.2.3", "192.168.0.1", "172.16.5.5", "169.254.0.1", "0.0.0.0"):
            self._resolve_to(monkeypatch, ip)
            assert not await citations._is_public_http("http://internal/")

    async def test_rejects_mixed_resolution(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._resolve_to(monkeypatch, "93.184.216.34", "192.168.1.1")
        assert not await citations._is_public_http("http://sneaky.example/")

    async def test_accepts_public_ip(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._resolve_to(monkeypatch, "93.184.216.34")
        assert await citations._is_public_http("https://example.com/page")

    async def test_rejects_nat64_embedded_private(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """64:ff9b::/96 passes is_global but embeds an IPv4 — check the embed."""
        self._resolve_to(monkeypatch, "64:ff9b::7f00:1")  # embeds 127.0.0.1
        assert not await citations._is_public_http("http://nat64-sneaky/")

    async def test_accepts_nat64_embedded_global(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._resolve_to(monkeypatch, "64:ff9b::808:808")  # embeds 8.8.8.8
        assert await citations._is_public_http("http://nat64-public/")

    async def test_rejects_non_http_scheme(self) -> None:
        assert not await citations._is_public_http("ftp://example.com/file")

    async def test_rejects_unresolvable_host(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _raise(*args: object, **kwargs: object) -> None:
            raise socket.gaierror("nope")

        monkeypatch.setattr(socket, "getaddrinfo", _raise)
        assert not await citations._is_public_http("http://does-not-exist.invalid/")


class TestFetch:
    async def test_success_returns_body_and_content_type(
        self, allow_all_hosts: None
    ) -> None:
        client = _FakeClient({"https://example.com/": [_FakeResp(body=b"<h1>Hi</h1>")]})
        fetched = await citations._fetch(_as_client(client), "https://example.com/")
        assert fetched == ("https://example.com/", b"<h1>Hi</h1>", "text/html")

    async def test_non_200_returns_none(self, allow_all_hosts: None) -> None:
        client = _FakeClient({"https://example.com/": [_FakeResp(status=404)]})
        assert (
            await citations._fetch(_as_client(client), "https://example.com/") is None
        )

    async def test_redirects_are_followed(self, allow_all_hosts: None) -> None:
        client = _FakeClient(
            {
                "https://a.com/": [
                    _FakeResp(
                        status=301, location="https://b.com/page", url="https://a.com/"
                    )
                ],
                "https://b.com/page": [_FakeResp(body=b"ok", url="https://b.com/page")],
            }
        )
        fetched = await citations._fetch(_as_client(client), "https://a.com/")
        assert fetched is not None
        assert client.seen == ["https://a.com/", "https://b.com/page"]

    async def test_redirect_to_private_host_blocked(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        guard = AsyncMock(side_effect=[True, False])
        monkeypatch.setattr(citations, "_is_public_http", guard)
        client = _FakeClient(
            {
                "https://a.com/": [
                    _FakeResp(
                        status=302,
                        location="http://localhost:9090/",
                        url="https://a.com/",
                    )
                ]
            }
        )
        assert await citations._fetch(_as_client(client), "https://a.com/") is None

    async def test_private_host_never_streamed(self) -> None:
        """The SSRF guard runs before any request is made."""
        client = _FakeClient({})
        assert (
            await citations._fetch(
                _as_client(client), "http://localhost:9090/v1/models"
            )
            is None
        )
        assert client.seen == []

    async def test_oversized_body_returns_none(self, allow_all_hosts: None) -> None:
        client = _FakeClient(
            {
                "https://example.com/big": [
                    _FakeResp(body=b"x" * (citations._MAX_BODY_BYTES + 1))
                ]
            }
        )
        assert (
            await citations._fetch(_as_client(client), "https://example.com/big")
            is None
        )


class TestBuildCitationElements:
    async def test_html_becomes_markdown_text(
        self,
        mock_cl_elements: None,
        allow_all_hosts: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            citations.httpx,
            "AsyncClient",
            lambda **kw: _FakeClient(
                {"https://example.com/": [_FakeResp(body=b"<h1>Title</h1><p>body</p>")]}
            ),
        )
        elements = await citations.build_citation_elements(
            [("my source", "https://example.com/")]
        )
        assert len(elements) == 1
        assert elements[0].name == "my source"
        assert elements[0].display == "side"
        # language must stay unset — a language hint turns the element
        # into a code-fenced source view instead of rendered markdown.
        assert getattr(elements[0], "language", None) in (None, "")
        assert "Title" in elements[0].content
        assert "<h1>" not in elements[0].content

    async def test_plain_text_passthrough(
        self,
        mock_cl_elements: None,
        allow_all_hosts: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            citations.httpx,
            "AsyncClient",
            lambda **kw: _FakeClient(
                {
                    "https://example.com/notes.txt": [
                        _FakeResp(body=b"hello world", content_type="text/plain")
                    ]
                }
            ),
        )
        elements = await citations.build_citation_elements(
            [("notes.txt", "https://example.com/notes.txt")]
        )
        assert len(elements) == 1
        assert elements[0].content == "hello world"

    async def test_pdf_content_type_becomes_cl_pdf(
        self,
        mock_cl_elements: None,
        allow_all_hosts: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            citations.httpx,
            "AsyncClient",
            lambda **kw: _FakeClient(
                {
                    "https://example.com/doc": [
                        _FakeResp(body=b"%PDF-1.4", content_type="application/pdf")
                    ]
                }
            ),
        )
        elements = await citations.build_citation_elements(
            [("doc", "https://example.com/doc")]
        )
        assert len(elements) == 1
        assert elements[0].content == b"%PDF-1.4"
        assert elements[0].display == "side"

    async def test_pdf_by_extension_with_octet_stream(
        self,
        mock_cl_elements: None,
        allow_all_hosts: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            citations.httpx,
            "AsyncClient",
            lambda **kw: _FakeClient(
                {
                    "https://example.com/doc.pdf": [
                        _FakeResp(
                            body=b"%PDF-1.4",
                            content_type="application/octet-stream",
                            url="https://example.com/doc.pdf",
                        )
                    ]
                }
            ),
        )
        elements = await citations.build_citation_elements(
            [("doc.pdf", "https://example.com/doc.pdf")]
        )
        assert len(elements) == 1

    async def test_unsupported_type_is_skipped(
        self,
        mock_cl_elements: None,
        allow_all_hosts: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            citations.httpx,
            "AsyncClient",
            lambda **kw: _FakeClient(
                {
                    "https://example.com/blob": [
                        _FakeResp(body=b"zip", content_type="application/zip")
                    ]
                }
            ),
        )
        assert (
            await citations.build_citation_elements([("b", "https://example.com/blob")])
            == []
        )

    async def test_failures_are_skipped_and_order_kept(
        self,
        mock_cl_elements: None,
        allow_all_hosts: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            citations.httpx,
            "AsyncClient",
            lambda **kw: _FakeClient(
                {
                    "https://a.com/": [_FakeResp(status=500, url="https://a.com/")],
                    "https://b.com/": [
                        _FakeResp(body=b"<p>B</p>", url="https://b.com/")
                    ],
                    "https://c.com/": [
                        _FakeResp(body=b"<p>C</p>", url="https://c.com/")
                    ],
                }
            ),
        )

        elements = await citations.build_citation_elements(
            [
                ("a", "https://a.com/"),
                ("gone", "https://gone.example/"),
                ("b", "https://b.com/"),
                ("c", "https://c.com/"),
            ]
        )
        assert [e.name for e in elements] == ["b", "c"]

    async def test_html_site_chrome_is_dropped(
        self,
        mock_cl_elements: None,
        allow_all_hosts: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Nav/sidebar chrome outside <article>/<main> must not be kept."""
        page = (
            b"<html><head><title>T</title></head><body>"
            b"<nav>Sign in Menu junk</nav>"
            b"<article><h1>Real content</h1></article>"
            b"</body></html>"
        )
        monkeypatch.setattr(
            citations.httpx,
            "AsyncClient",
            lambda **kw: _FakeClient({"https://example.com/": [_FakeResp(body=page)]}),
        )
        elements = await citations.build_citation_elements(
            [("e", "https://example.com/")]
        )
        assert len(elements) == 1
        assert "Real content" in elements[0].content
        assert "Sign in" not in elements[0].content

    async def test_relative_links_and_images_are_absolutized(
        self,
        mock_cl_elements: None,
        allow_all_hosts: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Relative src/href must resolve against the page URL, not chainlit's."""
        page = (
            b'<html><body><article><img src="/assets/logo.svg">'
            b'<a href="/docs/intro">docs</a>'
            b'<a href="#section">skip</a></article></body></html>'
        )
        monkeypatch.setattr(
            citations.httpx,
            "AsyncClient",
            lambda **kw: _FakeClient(
                {
                    "https://example.com/blog/post": [
                        _FakeResp(body=page, url="https://example.com/blog/post")
                    ]
                }
            ),
        )
        elements = await citations.build_citation_elements(
            [("post", "https://example.com/blog/post")]
        )
        content = elements[0].content
        assert "https://example.com/assets/logo.svg" in content
        assert "https://example.com/docs/intro" in content
        assert "](/assets/" not in content
        assert "](#section)" in content

    async def test_page_title_becomes_element_name(
        self,
        mock_cl_elements: None,
        allow_all_hosts: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        page = (
            b"<html><head><title>Switch desktop | CachyOS</title></head>"
            b"<body><article><h1>Content</h1></article></body></html>"
        )
        monkeypatch.setattr(
            citations.httpx,
            "AsyncClient",
            lambda **kw: _FakeClient({"https://example.com/": [_FakeResp(body=page)]}),
        )
        elements = await citations.build_citation_elements(
            [("url-slug", "https://example.com/")]
        )
        assert elements[0].name == "Switch desktop | CachyOS"

    async def test_no_title_keeps_provided_name(
        self,
        mock_cl_elements: None,
        allow_all_hosts: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            citations.httpx,
            "AsyncClient",
            lambda **kw: _FakeClient(
                {
                    "https://example.com/": [
                        _FakeResp(body=b"<article><p>x</p></article>")
                    ]
                }
            ),
        )
        elements = await citations.build_citation_elements(
            [("switch_desktop", "https://example.com/")]
        )
        assert elements[0].name == "switch_desktop"

    async def test_long_title_is_capped(
        self,
        mock_cl_elements: None,
        allow_all_hosts: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        page = (
            b"<html><head><title>"
            + b"t" * 120
            + b"</title></head><body><p>x</p></body></html>"
        )
        monkeypatch.setattr(
            citations.httpx,
            "AsyncClient",
            lambda **kw: _FakeClient({"https://example.com/": [_FakeResp(body=page)]}),
        )
        elements = await citations.build_citation_elements(
            [("x", "https://example.com/")]
        )
        assert len(elements[0].name) <= 70

    async def test_empty_page_body_is_skipped(
        self,
        mock_cl_elements: None,
        allow_all_hosts: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            citations.httpx,
            "AsyncClient",
            lambda **kw: _FakeClient({"https://example.com/": [_FakeResp(body=b"  ")]}),
        )
        assert (
            await citations.build_citation_elements([("e", "https://example.com/")])
            == []
        )

    async def test_conversion_error_is_silent(
        self,
        mock_cl_elements: None,
        allow_all_hosts: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A conversion exception must skip the citation, never raise."""
        monkeypatch.setattr(
            citations.httpx,
            "AsyncClient",
            lambda **kw: _FakeClient(
                {"https://example.com/": [_FakeResp(body=b"<html>poison</html>")]}
            ),
        )
        monkeypatch.setattr(
            citations,
            "markdownify",
            lambda _: 1 / 0,  # raises on conversion
        )
        assert (
            await citations.build_citation_elements([("e", "https://example.com/")])
            == []
        )

    async def test_overall_deadline_skips_slow_fetch(
        self,
        mock_cl_elements: None,
        allow_all_hosts: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A hanging fetch is cancelled by the overall per-citation deadline."""

        async def _hang(client: object, url: str) -> None:
            await asyncio.sleep(60)

        monkeypatch.setattr(citations, "_fetch", _hang)
        monkeypatch.setattr(citations, "_DEADLINE", 0.05)
        monkeypatch.setattr(
            citations.httpx, "AsyncClient", lambda **kw: _FakeClient({})
        )
        assert (
            await citations.build_citation_elements([("e", "https://example.com/")])
            == []
        )
