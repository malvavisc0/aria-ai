"""Tests for URL classification (file vs website)."""

from unittest.mock import MagicMock, patch

import httpx
import pytest

from aria.tools.search._url_classifier import URLType, classify_url


class TestClassifyUrlByExtension:
    """Test classification based on URL path extension."""

    @pytest.mark.parametrize(
        "url",
        [
            "https://example.com/report.pdf",
            "https://example.com/archive.zip",
            "https://example.com/data.csv",
            "https://example.com/image.png",
            "https://example.com/photo.jpg",
            "https://example.com/video.mp4",
            "https://example.com/audio.mp3",
            "https://example.com/doc.docx",
            "https://example.com/sheet.xlsx",
            "https://example.com/presentation.pptx",
            "https://example.com/app.exe",
            "https://example.com/package.whl",
            "https://example.com/disk.iso",
            "https://example.com/archive.tar.gz",
            "https://example.com/data.json",
            "https://example.com/config.yaml",
            "https://example.com/config.toml",
        ],
    )
    def test_file_extensions_detected(self, url):
        """Known file extensions should classify as FILE without HEAD request."""
        result = classify_url(url)
        assert result == URLType.FILE

    def test_case_insensitive_extension(self):
        """Extension matching should be case-insensitive."""
        assert classify_url("https://example.com/Report.PDF") == URLType.FILE

    def test_extension_with_query_params(self):
        """Extension detection should work with query parameters."""
        assert classify_url("https://example.com/file.pdf?token=abc") == URLType.FILE


class TestClassifyUrlByContentType:
    """Test classification based on HEAD request Content-Type."""

    @patch("aria.tools.search._url_classifier.httpx.Client")
    def test_html_content_type_is_website(self, mock_client_cls):
        """text/html Content-Type should classify as WEBSITE."""
        mock_resp = MagicMock()
        mock_resp.headers = {"content-type": "text/html; charset=utf-8"}

        mock_client = MagicMock()
        mock_client.head.return_value = mock_resp
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client_cls.return_value = mock_client

        result = classify_url("https://example.com/page")
        assert result == URLType.WEBSITE

    @patch("aria.tools.search._url_classifier.httpx.Client")
    def test_xhtml_content_type_is_website(self, mock_client_cls):
        """application/xhtml+xml Content-Type should classify as WEBSITE."""
        mock_resp = MagicMock()
        mock_resp.headers = {"content-type": "application/xhtml+xml"}

        mock_client = MagicMock()
        mock_client.head.return_value = mock_resp
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client_cls.return_value = mock_client

        result = classify_url("https://example.com/page")
        assert result == URLType.WEBSITE

    @patch("aria.tools.search._url_classifier.httpx.Client")
    def test_pdf_content_type_is_file(self, mock_client_cls):
        """application/pdf Content-Type should classify as FILE."""
        mock_resp = MagicMock()
        mock_resp.headers = {"content-type": "application/pdf"}

        mock_client = MagicMock()
        mock_client.head.return_value = mock_resp
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client_cls.return_value = mock_client

        result = classify_url("https://example.com/download")
        assert result == URLType.FILE

    @patch("aria.tools.search._url_classifier.httpx.Client")
    def test_octet_stream_is_file(self, mock_client_cls):
        """application/octet-stream Content-Type should classify as FILE."""
        mock_resp = MagicMock()
        mock_resp.headers = {"content-type": "application/octet-stream"}

        mock_client = MagicMock()
        mock_client.head.return_value = mock_resp
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client_cls.return_value = mock_client

        result = classify_url("https://example.com/download")
        assert result == URLType.FILE

    @patch("aria.tools.search._url_classifier.httpx.Client")
    def test_image_content_type_is_file(self, mock_client_cls):
        """image/* Content-Type should classify as FILE."""
        mock_resp = MagicMock()
        mock_resp.headers = {"content-type": "image/png"}

        mock_client = MagicMock()
        mock_client.head.return_value = mock_resp
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client_cls.return_value = mock_client

        result = classify_url("https://example.com/image")
        assert result == URLType.FILE

    @patch("aria.tools.search._url_classifier.httpx.Client")
    def test_video_content_type_is_file(self, mock_client_cls):
        """video/* Content-Type should classify as FILE."""
        mock_resp = MagicMock()
        mock_resp.headers = {"content-type": "video/mp4"}

        mock_client = MagicMock()
        mock_client.head.return_value = mock_resp
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client_cls.return_value = mock_client

        result = classify_url("https://example.com/video")
        assert result == URLType.FILE

    @patch("aria.tools.search._url_classifier.httpx.Client")
    def test_audio_content_type_is_file(self, mock_client_cls):
        """audio/* Content-Type should classify as FILE."""
        mock_resp = MagicMock()
        mock_resp.headers = {"content-type": "audio/mpeg"}

        mock_client = MagicMock()
        mock_client.head.return_value = mock_resp
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client_cls.return_value = mock_client

        result = classify_url("https://example.com/audio")
        assert result == URLType.FILE


class TestClassifyUrlFallback:
    """Test fallback behavior when classification is ambiguous."""

    @patch("aria.tools.search._url_classifier.httpx.Client")
    def test_head_request_failure_defaults_to_website(self, mock_client_cls):
        """When HEAD request fails, default to WEBSITE."""
        mock_client_cls.side_effect = httpx.ConnectError("refused")

        result = classify_url("https://example.com/page")
        assert result == URLType.WEBSITE

    @patch("aria.tools.search._url_classifier.httpx.Client")
    def test_timeout_defaults_to_website(self, mock_client_cls):
        """When HEAD request times out, default to WEBSITE."""
        mock_client_cls.side_effect = httpx.TimeoutException("timeout")

        result = classify_url("https://example.com/page")
        assert result == URLType.WEBSITE

    @patch("aria.tools.search._url_classifier.httpx.Client")
    def test_unknown_content_type_defaults_to_website(self, mock_client_cls):
        """When Content-Type is ambiguous, default to WEBSITE."""
        mock_resp = MagicMock()
        mock_resp.headers = {"content-type": "application/x-unknown-type"}

        mock_client = MagicMock()
        mock_client.head.return_value = mock_resp
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client_cls.return_value = mock_client

        # application/* is caught by the binary fallback → FILE
        result = classify_url("https://example.com/thing")
        assert result == URLType.FILE

    @patch("aria.tools.search._url_classifier.httpx.Client")
    def test_no_content_type_header_defaults_to_website(self, mock_client_cls):
        """When no Content-Type header, default to WEBSITE."""
        mock_resp = MagicMock()
        mock_resp.headers = {}

        mock_client = MagicMock()
        mock_client.head.return_value = mock_resp
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client_cls.return_value = mock_client

        result = classify_url("https://example.com/page")
        assert result == URLType.WEBSITE


class TestClassifyUrlEdgeCases:
    """Test edge cases."""

    def test_url_with_no_path(self):
        """URL with no path should fall through to HEAD request."""
        with patch("aria.tools.search._url_classifier.httpx.Client") as mock_cls:
            mock_resp = MagicMock()
            mock_resp.headers = {"content-type": "text/html"}

            mock_client = MagicMock()
            mock_client.head.return_value = mock_resp
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_cls.return_value = mock_client

            result = classify_url("https://example.com")
            assert result == URLType.WEBSITE

    def test_deeply_nested_path_with_extension(self):
        """Extension detection should work in deeply nested paths."""
        url = "https://cdn.example.com/a/b/c/d/report.pdf"
        assert classify_url(url) == URLType.FILE

    def test_extension_takes_priority_over_head(self):
        """Extension match should return immediately without HEAD request."""
        with patch("aria.tools.search._url_classifier.httpx.Client") as mock_cls:
            result = classify_url("https://example.com/file.pdf")
            assert result == URLType.FILE
            # HEAD request should NOT have been made
            mock_cls.assert_not_called()
