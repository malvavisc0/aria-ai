"""
Test suite for the download module.

This module tests the download function to ensure it properly
downloads files, saves them to disk, and returns JSON responses with
metadata for AI agent consumption.
"""

import importlib
import importlib.util
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

import httpx
import pytest

from aria.tools.search import download, get_youtube_video_transcription
from aria.tools.search._download_internals import (
    _auto_detect_format,
    _clean_text,
    _create_error_response,
    _create_response,
    _extract_filename_from_response,
    _fetch_file,
    _get_default_headers,
    _get_file_extension,
    _is_binary_content,
    _is_html_content,
    _is_markitdown_supported,
    _markitdown,
    _resolve_download_target,
    _save_bytes_fallback,
    _save_content_to_file,
    _save_html_to_markdown,
    _save_plain_binary,
    _save_text,
    _validate_format,
    _validate_url,
)
from aria.tools.search.download import ContentParsingError, URLDownloadError

_markitdown_available = importlib.util.find_spec("markitdown") is not None
try:
    if _markitdown_available:
        import markitdown  # noqa: F401
except Exception:
    _markitdown_available = False

_needs_markitdown = pytest.mark.skipif(
    not _markitdown_available,
    reason="markitdown not fully importable (missing onnxruntime?)",
)


def _response_data(raw: str) -> dict:
    return json.loads(raw)["data"]


def _response_error(raw: str) -> str:
    return json.loads(raw)["error"]["message"]


class TestURLValidation:
    """Test URL validation functionality."""

    def test_validate_url_valid_http(self):
        """Test validation of valid HTTP URL."""
        url = "http://example.com"
        assert _validate_url(url) == url

    def test_validate_url_valid_https(self):
        """Test validation of valid HTTPS URL."""
        url = "https://example.com"
        assert _validate_url(url) == url

    def test_validate_url_empty(self):
        """Test validation of empty URL."""
        with pytest.raises(URLDownloadError, match="URL cannot be empty"):
            _validate_url("")

    def test_validate_url_invalid_scheme(self):
        """Test validation of URL with invalid scheme."""
        with pytest.raises(
            URLDownloadError, match="Only HTTP and HTTPS URLs are supported"
        ):
            _validate_url("ftp://example.com")

    def test_validate_url_malformed(self):
        """Test validation of malformed URL."""
        with pytest.raises(URLDownloadError, match="Invalid URL format"):
            _validate_url("not-a-url")


class TestFormatValidation:
    """Test output format validation."""

    def test_validate_format_valid(self):
        """Test validation of valid formats."""
        for fmt in ["markdown", "text", "html", "binary", "auto"]:
            assert _validate_format(fmt) == fmt

    def test_validate_format_invalid(self):
        """Test validation of invalid format."""
        with pytest.raises(ContentParsingError, match="Unsupported format"):
            _validate_format("invalid")


class TestContentTypeDetection:
    """Test content type detection functions."""

    def test_is_html_content(self):
        """Test HTML content detection."""
        assert _is_html_content("text/html")
        assert _is_html_content("application/xhtml+xml")
        assert not _is_html_content("text/plain")

    def test_is_binary_content(self):
        """Test binary content detection."""
        assert _is_binary_content("application/pdf")
        assert _is_binary_content("image/png")
        assert not _is_binary_content("text/plain")

    def test_is_markitdown_supported(self):
        """Test MarkItDown support detection."""
        assert _is_markitdown_supported("application/pdf")
        assert _is_markitdown_supported("application/vnd.ms-excel")
        assert not _is_markitdown_supported("image/png")

    def test_auto_detect_format(self):
        """Test automatic format detection."""
        assert _auto_detect_format("text/html") == "markdown"
        assert _auto_detect_format("application/pdf") == "markdown"
        assert _auto_detect_format("image/png") == "binary"
        assert _auto_detect_format("text/plain") == "text"


class TestUtilityFunctions:
    """Test utility functions."""

    def test_get_file_extension_from_url(self):
        """Test file extension extraction from URL."""
        ext = _get_file_extension("https://example.com/file.pdf", "application/pdf")
        assert ext == ".pdf"

    def test_get_file_extension_from_content_type(self):
        """Test file extension extraction from content type."""
        ext = _get_file_extension("https://example.com/file", "application/pdf")
        assert ext in [".pdf", ".bin"]

    def test_clean_text(self):
        """Test text cleaning."""
        text = "  Hello   World  \n\n  Test  "
        cleaned = _clean_text(text)
        assert "  " not in cleaned
        assert cleaned.strip() == "Hello World Test"


class TestGetFileFromURL:
    """Test the main download function."""

    @_needs_markitdown
    @patch("aria.tools.search._download_internals.httpx.Client")
    def test_download_html_success(self, mock_client):
        """Test successful HTML download."""
        # Mock HTTP response
        mock_response = Mock()
        mock_response.text = "<html><body>Test</body></html>"
        mock_response.headers = {"content-type": "text/html"}
        mock_response.raise_for_status = Mock()

        mock_client_instance = Mock()
        mock_client_instance.get.return_value = mock_response
        mock_client_instance.__enter__ = Mock(return_value=mock_client_instance)
        mock_client_instance.__exit__ = Mock(return_value=False)
        mock_client.return_value = mock_client_instance

        # Download file
        result_json = download("Testing file download", "https://example.com")
        data = _response_data(result_json)

        # Verify response structure
        assert data["file_path"] is not None
        assert os.path.exists(data["file_path"])

        # Verify metadata
        metadata = data["metadata"]
        assert metadata["url"] == "https://example.com"
        assert metadata["content_type"] == "text/html"
        assert metadata["format"] == "html"
        assert metadata["parsed"] is True  # HTML is parsed to markdown by default
        assert "timestamp" in metadata

        # Verify file content
        with open(data["file_path"]) as f:
            content = f.read()
            assert "Test" in content

    def test_download_invalid_url(self):
        """Test download with invalid URL."""
        result_json = download("Testing file download", "not-a-url")
        err = _response_error(result_json)

        assert "Invalid URL format" in err

    def test_download_empty_url(self):
        """Test download with empty URL."""
        result_json = download("Testing file download", "")
        err = _response_error(result_json)

        assert "URL cannot be empty" in err

    def test_json_response_structure(self):
        """Test that JSON response has correct structure."""
        result_json = download("Testing file download", "invalid-url")
        data = json.loads(result_json)

        # Check required fields
        assert "status" in data
        assert "tool" in data
        assert "reason" in data
        assert "timestamp" in data
        assert "error" in data

    @patch("aria.tools.search._download_internals.httpx.Client")
    def test_download_with_different_formats(self, mock_client):
        """Test download with different output formats."""
        mock_response = Mock()
        mock_response.text = "<html><body>Test</body></html>"
        mock_response.headers = {"content-type": "text/html"}
        mock_response.raise_for_status = Mock()

        mock_client_instance = Mock()
        mock_client_instance.get.return_value = mock_response
        mock_client_instance.__enter__ = Mock(return_value=mock_client_instance)
        mock_client_instance.__exit__ = Mock(return_value=False)
        mock_client.return_value = mock_client_instance

        for fmt in ["auto", "text", "html"]:
            result_json = download(
                "Testing file download", "https://example.com", output=fmt
            )
            data = _response_data(result_json)
            assert os.path.exists(data["file_path"])


class TestIntegration:
    """Integration tests with real HTTP requests."""

    def test_real_download_example_com(self):
        """Test real download from example.com."""
        result_json = download("Testing file download", "https://www.example.com")
        data = _response_data(result_json)

        assert data["file_path"] is not None
        assert os.path.exists(data["file_path"])

        # Verify file has content
        file_size = data["metadata"]["file_size"]
        assert file_size > 0

        # Verify we can read the file
        with open(data["file_path"]) as f:
            content = f.read()
            assert len(content) > 0
            assert "Example Domain" in content

    def test_real_download_with_auto_format(self):
        """Test real download with auto format detection."""
        result_json = download(
            "Testing file download", "https://www.example.com", output="auto"
        )
        data = _response_data(result_json)

        assert data["metadata"]["format"] in ["html", "text", "markdown"]


class TestHeaderGeneration:
    """Test HTTP header generation functions."""

    def test_get_default_headers(self):
        """Test default headers generation."""
        headers = _get_default_headers()
        assert "User-Agent" in headers
        assert "Accept" in headers
        assert "Accept-Language" in headers
        assert "DNT" in headers


class TestFilenameExtraction:
    """Test filename extraction from responses."""

    def test_extract_filename_from_content_disposition(self):
        """Test filename extraction from Content-Disposition header."""
        mock_response = Mock()
        mock_response.headers = {
            "content-disposition": 'attachment; filename="document.pdf"'
        }
        filename = _extract_filename_from_response(mock_response, "https://example.com")
        assert filename == "document.pdf"

    def test_extract_filename_from_url(self):
        """Test filename extraction from URL path."""
        mock_response = Mock()
        mock_response.headers = {}
        filename = _extract_filename_from_response(
            mock_response, "https://example.com/path/file.pdf"
        )
        assert filename == "file.pdf"

    def test_extract_filename_no_match(self):
        """Test filename extraction when no filename available."""
        mock_response = Mock()
        mock_response.headers = {}
        filename = _extract_filename_from_response(
            mock_response, "https://example.com/"
        )
        assert filename is None


class TestFetchFile:
    """Test file fetching with retry logic."""

    @patch("aria.tools.search._download_internals.httpx.Client")
    def test_fetch_file_success(self, mock_client_class):
        """Test successful file fetch."""
        mock_response = Mock()
        mock_response.text = "Test content"
        mock_response.content = b"Test content"
        mock_response.headers = {"content-type": "text/plain"}
        mock_response.raise_for_status = Mock()

        mock_client = Mock()
        mock_client.get.return_value = mock_response
        mock_client.__enter__ = Mock(return_value=mock_client)
        mock_client.__exit__ = Mock(return_value=False)
        mock_client_class.return_value = mock_client

        content, content_type, filename = _fetch_file("https://example.com/test.txt")
        assert content == b"Test content"
        assert content_type == "text/plain"

    @patch("aria.tools.search._download_internals.httpx.Client")
    def test_fetch_file_with_custom_headers(self, mock_client_class):
        """Test file fetch with custom headers."""
        mock_response = Mock()
        mock_response.content = b"Test"
        mock_response.headers = {"content-type": "text/plain"}
        mock_response.raise_for_status = Mock()

        mock_client = Mock()
        mock_client.get.return_value = mock_response
        mock_client.__enter__ = Mock(return_value=mock_client)
        mock_client.__exit__ = Mock(return_value=False)
        mock_client_class.return_value = mock_client

        custom_headers = {"Authorization": "Bearer token"}
        _fetch_file("https://example.com", custom_headers=custom_headers)
        assert mock_client.get.called

    @patch("aria.tools.search._download_internals.httpx.Client")
    def test_fetch_file_size_limit_exceeded(self, mock_client_class):
        """Test file fetch with size limit exceeded."""
        mock_response = Mock()
        mock_response.headers = {
            "content-type": "text/plain",
            "content-length": "999999999",
        }
        mock_response.raise_for_status = Mock()

        mock_client = Mock()
        mock_client.get.return_value = mock_response
        mock_client.__enter__ = Mock(return_value=mock_client)
        mock_client.__exit__ = Mock(return_value=False)
        mock_client_class.return_value = mock_client

        with pytest.raises(URLDownloadError, match="exceeds maximum"):
            _fetch_file("https://example.com", max_size=1000)

    @patch("aria.tools.search._download_internals.httpx.Client")
    @patch("aria.tools.search._download_internals.time.sleep")
    def test_fetch_file_retry_on_timeout(self, mock_sleep, mock_client_class):
        """Test retry logic on timeout."""
        mock_client = Mock()
        mock_client.get.side_effect = httpx.TimeoutException("Timeout")
        mock_client.__enter__ = Mock(return_value=mock_client)
        mock_client.__exit__ = Mock(return_value=False)
        mock_client_class.return_value = mock_client

        with pytest.raises(URLDownloadError, match="Failed to fetch"):
            _fetch_file("https://example.com")

        # Should have retried
        assert mock_client.get.call_count > 1

    @patch("aria.tools.search._download_internals.httpx.Client")
    def test_fetch_file_html_size_check(self, mock_client_class):
        """Test HTML content size checking."""
        large_html = "x" * 200_000_000  # Very large HTML
        mock_response = Mock()
        mock_response.text = large_html
        mock_response.headers = {"content-type": "text/html"}
        mock_response.raise_for_status = Mock()

        mock_client = Mock()
        mock_client.get.return_value = mock_response
        mock_client.__enter__ = Mock(return_value=mock_client)
        mock_client.__exit__ = Mock(return_value=False)
        mock_client_class.return_value = mock_client

        with pytest.raises(URLDownloadError, match="exceeds maximum"):
            _fetch_file("https://example.com", max_size=1000)

    @patch("aria.tools.search._download_internals.httpx.Client")
    def test_fetch_file_binary_size_check(self, mock_client_class):
        """Test binary content size checking."""
        large_content = b"x" * 200_000_000
        mock_response = Mock()
        mock_response.content = large_content
        mock_response.headers = {"content-type": "application/pdf"}
        mock_response.raise_for_status = Mock()

        mock_client = Mock()
        mock_client.get.return_value = mock_response
        mock_client.__enter__ = Mock(return_value=mock_client)
        mock_client.__exit__ = Mock(return_value=False)
        mock_client_class.return_value = mock_client

        with pytest.raises(URLDownloadError, match="exceeds maximum"):
            _fetch_file("https://example.com", max_size=1000)


@_needs_markitdown
class TestMarkitdown:
    """Test MarkItDown conversion."""

    def test_markitdown_with_string_content(self):
        """Test MarkItDown with string content."""
        content = "Test content"
        result = _markitdown(content, "text/plain", "https://example.com/test.txt")
        assert isinstance(result, str)

    def test_markitdown_with_bytes_content(self):
        """Test MarkItDown with bytes content."""
        content = b"Test content"
        result = _markitdown(content, "text/plain", "https://example.com/test.txt")
        assert isinstance(result, str)


class TestCleanText:
    """Test text cleaning functionality."""

    def test_clean_text_empty(self):
        """Test cleaning empty text."""
        assert _clean_text("") == ""

    def test_clean_text_whitespace(self):
        """Test cleaning whitespace."""
        text = "  Hello   World  "
        cleaned = _clean_text(text)
        assert cleaned == "Hello World"

    def test_clean_text_control_characters(self):
        """Test removal of control characters."""
        text = "Hello\x00\x01World"
        cleaned = _clean_text(text)
        assert "\x00" not in cleaned
        assert "\x01" not in cleaned


class TestSaveContentToFile:
    """Test content saving functionality."""

    def test_save_text_content(self):
        """Test saving text content."""
        content = "Test content"
        file_path, metadata = _save_content_to_file(
            content,
            "https://example.com/test.txt",
            "text/plain",
            "text",
            download_path=None,
        )
        assert os.path.exists(file_path)
        assert metadata["format"] == "text"
        assert metadata["url"] == "https://example.com/test.txt"

    def test_save_html_content(self):
        """Test saving HTML content."""
        content = "<html><body>Test</body></html>"
        file_path, metadata = _save_content_to_file(
            content,
            "https://example.com/test.html",
            "text/html",
            "html",
            download_path=None,
        )
        assert os.path.exists(file_path)
        assert metadata["format"] == "html"

    def test_save_binary_content(self):
        """Test saving binary content."""
        content = b"\x89PNG\r\n\x1a\n"
        file_path, metadata = _save_content_to_file(
            content,
            "https://example.com/test.png",
            "image/png",
            "binary",
            download_path=None,
        )
        assert os.path.exists(file_path)
        assert metadata["format"] == "binary"

    def test_save_with_custom_path(self):
        """Test saving with custom download path."""
        with tempfile.TemporaryDirectory() as temp_dir:
            custom_path = os.path.join(temp_dir, "custom.txt")
            content = "Test"
            file_path, metadata = _save_content_to_file(
                content,
                "https://example.com/test.txt",
                "text/plain",
                "text",
                download_path=custom_path,
            )
            assert os.path.exists(file_path)
            assert "custom" in file_path

    @patch("aria.tools.search._download_internals._markitdown")
    def test_save_markitdown_supported_binary(self, mock_markitdown):
        """Test saving MarkItDown-supported binary content."""
        # Mock the markitdown conversion to avoid PDF parsing errors
        mock_markitdown.return_value = "Parsed PDF content"

        content = b"%PDF-1.4 test"
        file_path, metadata = _save_content_to_file(
            content,
            "https://example.com/test.pdf",
            "application/pdf",
            "auto",
            download_path=None,
        )
        assert os.path.exists(file_path)
        # Should create original file
        assert metadata["format"] == "binary"
        assert metadata["parsed"] is True


class TestSaveStrategies:
    """Direct tests for the extracted save strategy helpers."""

    def test_resolve_download_target_uses_original_filename(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            download_dir, base, ext = _resolve_download_target(
                temp_dir, "report.pdf", "https://example.com/x", "application/pdf"
            )
            assert download_dir == Path(temp_dir)
            assert base == "report"
            assert ext == ".pdf"

    def test_resolve_download_target_file_path(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            custom = os.path.join(temp_dir, "out.bin")
            download_dir, base, ext = _resolve_download_target(
                custom, None, "https://example.com/x", "application/octet-stream"
            )
            assert base == "out"
            assert ext == ".bin"

    def test_save_plain_binary_writes_bytes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            file_path, metadata = _save_plain_binary(
                b"\x00\x01",
                "application/octet-stream",
                "https://example.com/x",
                ".bin",
                "data",
                Path(temp_dir),
                None,
            )
            assert os.path.exists(file_path)
            assert metadata["format"] == "binary"
            assert metadata["parsed"] is False

    def test_save_bytes_fallback_writes_bytes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            file_path, metadata = _save_bytes_fallback(
                b"\x00\x01",
                "application/octet-stream",
                "https://example.com/x",
                ".bin",
                "data",
                Path(temp_dir),
                None,
            )
            assert os.path.exists(file_path)
            assert metadata["format"] == "binary"

    def test_save_text_text_mode(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            file_path, metadata = _save_text(
                "hello",
                "text/plain",
                "https://example.com/x.txt",
                "text",
                ".txt",
                "content",
                Path(temp_dir),
                None,
            )
            assert metadata["format"] == "text"
            assert Path(file_path).read_text() == "hello"

    @patch("aria.tools.search._download_internals._markitdown")
    def test_save_html_to_markdown_parsed(self, mock_markitdown):
        mock_markitdown.return_value = "# Title"
        with tempfile.TemporaryDirectory() as temp_dir:
            file_path, metadata = _save_html_to_markdown(
                "<html></html>",
                "text/html",
                "https://example.com/x.html",
                ".html",
                "page",
                Path(temp_dir),
                None,
            )
            assert metadata["format"] == "html"
            assert metadata["parsed"] is True
            assert metadata["parsed_file_path"].endswith("page.md")

    @patch("aria.tools.search._download_internals._markitdown")
    def test_save_html_to_markdown_parse_failure(self, mock_markitdown):
        mock_markitdown.side_effect = RuntimeError("boom")
        with tempfile.TemporaryDirectory() as temp_dir:
            file_path, metadata = _save_html_to_markdown(
                "<html></html>",
                "text/html",
                "https://example.com/x.html",
                ".html",
                "page",
                Path(temp_dir),
                None,
            )
            assert metadata["parsed"] is False
            assert metadata["parse_error"] == "boom"


class TestResponseCreation:
    """Test JSON response creation."""

    def test_create_response(self):
        """Test creating success response."""
        metadata = {"url": "https://example.com", "size": 100}
        response = _create_response(
            "download",
            "test reason",
            "/path/to/file",
            metadata,
        )
        data = _response_data(response)
        assert data["file_path"] == "/path/to/file"
        assert data["metadata"] == metadata

    def test_create_error_response(self):
        """Test creating error response."""
        response = _create_error_response("download", "test reason", "Test error")
        err = _response_error(response)
        assert err == "Test error"


class TestYouTubeTranscription:
    """Test YouTube video transcription."""

    @patch("aria.tools.search.youtube._save_content_to_file")
    @patch("aria.tools.search.youtube.YouTubeTranscriptApi")
    def test_youtube_transcription_success(self, mock_api_class, mock_save):
        """Test successful YouTube transcription."""
        mock_api = Mock()
        mock_snippets = [Mock(duration=1.0, text=f"Snippet {i}.") for i in range(5)]
        mock_transcript = Mock(snippets=mock_snippets)
        mock_api.fetch.return_value = mock_transcript
        mock_api_class.return_value = mock_api

        mock_save.return_value = ("/tmp/mock_file.txt", {"file_size": 20})

        result = get_youtube_video_transcription(
            reason="Testing YouTube transcription",
            url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        )

        data = _response_data(result)
        assert data["file_path"] == "/tmp/mock_file.txt"
        assert data["metadata"]["video_id"] == "dQw4w9WgXcQ"
        assert data["metadata"]["transcript_segments"] == 5
        assert data["metadata"]["estimated_duration"] == 5.0

        mock_api_class.assert_called_once()
        mock_api.fetch.assert_called_once_with(
            "dQw4w9WgXcQ", languages=["en"]
        )  # Should match video ID with default language
        mock_save.assert_called_once()
        # The persisted text is paragraphed prose built from snippets, not
        # the library's one-line-per-fragment TextFormatter output.
        saved_text = mock_save.call_args.args[0]
        assert "Snippet 0. Snippet 1. Snippet 2." in saved_text
        assert "\n\n" in saved_text

    def test_youtube_transcription_invalid_url(self):
        """Test YouTube transcription with invalid URL."""
        result = get_youtube_video_transcription(
            "Testing YouTube transcription", "not-a-url"
        )
        err = _response_error(result)
        assert "Invalid URL format" in err


class TestEdgeCases:
    """Test edge cases and error conditions."""

    @patch("aria.tools.search._download_internals.httpx.Client")
    def test_get_file_with_http_error(self, mock_client_class):
        """Test handling of HTTP errors."""
        mock_response = Mock()
        mock_response.status_code = 404
        error = httpx.HTTPStatusError(
            "Not found", request=Mock(), response=mock_response
        )
        mock_response.raise_for_status.side_effect = error

        mock_client = Mock()
        mock_client.get.return_value = mock_response
        mock_client.__enter__ = Mock(return_value=mock_client)
        mock_client.__exit__ = Mock(return_value=False)
        mock_client_class.return_value = mock_client

        result = download("Testing file download", "https://example.com/notfound")
        payload = json.loads(result)
        assert payload["status"] == "error"

    def test_get_file_with_invalid_format(self):
        """Test download with invalid output format."""
        result = download(
            "Testing file download",
            "https://example.com",
            output="invalid_format",
        )
        err = _response_error(result)
        assert "Unsupported format" in err

    @patch("aria.tools.search._download_internals.httpx.Client")
    def test_get_file_generic_exception(self, mock_client_class):
        """Test handling of generic exceptions."""
        mock_client = Mock()
        mock_client.get.side_effect = Exception("Unexpected error")
        mock_client.__enter__ = Mock(return_value=mock_client)
        mock_client.__exit__ = Mock(return_value=False)
        mock_client_class.return_value = mock_client

        result = download("Testing file download", "https://example.com")
        err = _response_error(result)
        assert "Failed to fetch" in err


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
