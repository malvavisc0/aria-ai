"""Tests for HTTP request tool."""

import json
from unittest.mock import MagicMock, patch

import httpx

from aria.tools.http import http_request


class TestHttpRequest:
    """Test suite for http_request tool."""

    def test_invalid_method(self):
        """Test that invalid HTTP method is rejected."""
        result = http_request("Test", method="INVALID", url="http://example.com")
        data = json.loads(result)
        assert "error" in data["data"]
        assert "not allowed" in data["data"]["error"]

    @patch("aria.tools.http.functions.httpx.Client")
    def test_successful_get_request(self, mock_client_cls):
        """Test successful GET request."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "application/json"}
        mock_response.text = '{"result": "ok"}'
        mock_response.url = "http://example.com/api"

        mock_client = MagicMock()
        mock_client.request.return_value = mock_response
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client_cls.return_value = mock_client

        result = http_request("Fetch API", method="GET", url="http://example.com/api")
        data = json.loads(result)
        assert data["data"]["status_code"] == 200
        assert data["data"]["content_type"] == "application/json"
        assert data["data"]["body_size"] == len('{"result": "ok"}')
        assert data["data"]["body_file"].endswith(".json")

    @patch("aria.tools.http.functions.httpx.Client")
    def test_timeout_error(self, mock_client_cls):
        """Test timeout handling."""
        mock_client_cls.side_effect = httpx.TimeoutException("timeout")

        result = http_request(
            "Timeout test",
            method="GET",
            url="http://example.com",
            timeout=1,
        )
        data = json.loads(result)
        assert "error" in data["data"]
        assert "timed out" in data["data"]["error"].lower()

    @patch("aria.tools.http.functions.httpx.Client")
    def test_connection_error(self, mock_client_cls):
        """Test connection error handling."""
        mock_client_cls.side_effect = httpx.ConnectError("refused")

        result = http_request("Connect test", method="GET", url="http://example.com")
        data = json.loads(result)
        assert "error" in data["data"]
        assert "connection" in data["data"]["error"].lower()

    def test_method_case_insensitive(self):
        """Test that method is case-insensitive."""
        # Should not raise for method validation
        # (will fail on connection, but method should be accepted)
        result = http_request("Test", method="get", url="http://example.com")
        # Should get a connection error, not a method error
        data = json.loads(result)
        assert "not allowed" not in data["data"].get("error", "")

    @patch("aria.tools.http.functions.httpx.Client")
    def test_http_error_status_returns_error_envelope(self, mock_client_cls):
        """A 4xx/5xx response must report an error, not success."""
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.reason_phrase = "Not Found"
        mock_response.headers = {"content-type": "application/json"}
        mock_response.text = '{"error": "not found"}'
        mock_response.url = "http://example.com/missing"
        mock_response.request = MagicMock()

        mock_client = MagicMock()
        mock_client.request.return_value = mock_response
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client_cls.return_value = mock_client

        result = http_request("Fetch", method="GET", url="http://example.com/missing")
        data = json.loads(result)

        assert data["status"] == "error"
        assert "HTTP 404" in data["error"]["message"]
        assert data["context"]["status_code"] == 404
