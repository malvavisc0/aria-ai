"""Tests for the web_search tool and its error handling."""

import json
from unittest.mock import patch

from aria.tools.search.webserp import web_search


def _response_error(raw: str) -> str:
    payload = json.loads(raw)
    return payload["error"]["message"]


class TestWebSearch:
    """Test suite for web_search tool."""

    def test_empty_query_returns_error(self):
        """Empty query should return an error envelope, not raise."""
        result = web_search("Test", query="")
        payload = json.loads(result)
        assert payload["status"] == "error"
        assert "cannot be empty" in _response_error(result)

    def test_negative_max_results_returns_error(self):
        """Non-positive max_results should return an error envelope."""
        result = web_search("Test", query="hello", max_results=0)
        payload = json.loads(result)
        assert payload["status"] == "error"
        assert "must be positive" in _response_error(result)

    @patch("aria.tools.search.webserp._run_webserp")
    def test_runtime_error_on_nonzero_exit_is_caught(self, mock_run):
        """A RuntimeError from _run_webserp must become an error envelope,
        not escape the tool boundary."""
        mock_run.side_effect = RuntimeError(
            "webserp exited with code 127: command not found"
        )

        result = web_search("Test", query="hello")
        payload = json.loads(result)

        assert payload["status"] == "error"
        assert "code 127" in _response_error(result)

    @patch("aria.tools.search.webserp._run_webserp")
    def test_parse_error_is_caught(self, mock_run):
        """Invalid webserp output should be an error envelope, not raise."""
        mock_run.return_value = "not json"

        result = web_search("Test", query="hello")
        payload = json.loads(result)

        assert payload["status"] == "error"

    @patch("aria.tools.search.webserp._run_webserp")
    def test_success_with_findings(self, mock_run):
        """Valid output should produce a success response with findings."""
        mock_run.return_value = json.dumps(
            {"results": [{"url": "https://example.com", "title": "Example"}]}
        )

        result = web_search("Test", query="hello")
        payload = json.loads(result)

        assert payload["status"] == "success"
        assert payload["data"]["count"] == 1
        assert payload["data"]["findings"][0]["url"] == "https://example.com"
