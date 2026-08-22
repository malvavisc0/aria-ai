"""Tests for shared utility functions in utils.py."""

import json
from datetime import datetime

from aria.tools import (
    safe_json,
    tool_error_response,
    tool_response,
    tool_success_response,
    utc_timestamp,
)


class TestToolSuccessResponse:
    """Tests for tool_success_response() function."""

    def test_basic_success_response(self):
        """Should create a basic success response."""
        result = tool_success_response(
            tool="test_tool",
            reason="test reason",
            data={"result": "success"},
        )
        parsed = json.loads(result)

        assert parsed["status"] == "success"
        assert parsed["tool"] == "test_tool"
        assert parsed["reason"] == "test reason"
        assert parsed["data"] == {"result": "success"}
        assert "timestamp" in parsed

    def test_includes_context(self):
        """Should include additional context fields."""
        result = tool_success_response(
            tool="test_tool",
            reason="test reason",
            data={"result": "success"},
            extra_field="extra_value",
        )
        parsed = json.loads(result)

        assert parsed["context"]["extra_field"] == "extra_value"

    def test_error_in_data_sets_status_error(self):
        """A payload carrying an 'error' key must not report success."""
        result = tool_success_response(
            tool="ax",
            reason="missing_reason",
            data={"error": {"code": "missing_reason", "message": "..."}},
        )
        parsed = json.loads(result)

        assert parsed["status"] == "error"
        assert parsed["data"]["error"]["code"] == "missing_reason"


class TestToolErrorResponse:
    """Tests for tool_error_response() function."""

    def test_basic_error_response(self):
        """Should create a basic error response."""

        class TestError(Exception):
            code = "TEST_ERROR"
            recoverable = True
            how_to_fix = "Fix it"

        exc = TestError("Test error message")
        result = tool_error_response(
            tool="test_tool",
            reason="test reason",
            exc=exc,
        )
        parsed = json.loads(result)

        assert parsed["status"] == "error"
        assert parsed["tool"] == "test_tool"
        assert parsed["reason"] == "test reason"
        assert parsed["error"]["code"] == "TEST_ERROR"
        assert parsed["error"]["message"] == "Test error message"
        assert parsed["error"]["recoverable"] is True
        assert parsed["error"]["how_to_fix"] == "Fix it"
        assert "timestamp" in parsed

    def test_error_without_custom_attributes(self):
        """Should handle exceptions without custom attributes."""
        exc = ValueError("Simple error")
        result = tool_error_response(
            tool="test_tool",
            reason="test reason",
            exc=exc,
        )
        parsed = json.loads(result)

        assert parsed["status"] == "error"
        assert parsed["error"]["code"] == "VALUEERROR"
        assert parsed["error"]["recoverable"] is False


class TestToolResponse:
    """Tests for tool_response() convenience function."""

    def test_returns_success_when_no_exception(self):
        """Should return success response when no exception provided."""
        result = tool_response(
            tool="test_tool",
            reason="test reason",
            data={"result": "success"},
        )
        parsed = json.loads(result)

        assert parsed["status"] == "success"
        assert parsed["data"] == {"result": "success"}

    def test_returns_error_when_exception_provided(self):
        """Should return error response when exception provided."""
        exc = ValueError("Error occurred")
        result = tool_response(
            tool="test_tool",
            reason="test reason",
            exc=exc,
        )
        parsed = json.loads(result)

        assert parsed["status"] == "error"
        assert "Error occurred" in parsed["error"]["message"]

    def test_uses_empty_dict_when_data_none(self):
        """Should use empty dict for data when None is provided."""
        result = tool_response(
            tool="test_tool",
            reason="test reason",
            data=None,
        )
        parsed = json.loads(result)

        assert parsed["status"] == "success"
        assert parsed["data"] == {}


class TestUtcTimestamp:
    """Tests for utc_timestamp()."""

    def test_iso_format(self) -> None:
        ts = utc_timestamp()
        assert isinstance(ts, str)
        assert "T" in ts
        datetime.fromisoformat(ts)


class TestSafeJson:
    """Tests for safe_json()."""

    def test_round_trip(self) -> None:
        data = {"key": "value", "number": 42}
        assert json.loads(safe_json(data)) == data

    def test_unicode(self) -> None:
        data = {"text": "Hello 世界"}
        parsed = json.loads(safe_json(data))
        assert parsed["text"] == "Hello 世界"

    def test_non_serializable_falls_back_to_str(self) -> None:
        class NonSerializable:
            pass

        parsed = json.loads(safe_json({"obj": NonSerializable()}))
        assert "NonSerializable" in parsed["obj"]

    def test_nan_returns_error_envelope(self) -> None:
        """NaN must not serialize to an invalid JSON literal."""
        result = safe_json({"price": float("nan")})
        parsed = json.loads(result)
        assert parsed["error"] == "Serialization failed"

    def test_inf_returns_error_envelope(self) -> None:
        """Infinity must not serialize to an invalid JSON literal."""
        result = safe_json({"price": float("inf")})
        parsed = json.loads(result)
        assert parsed["error"] == "Serialization failed"
