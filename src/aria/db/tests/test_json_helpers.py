"""Unit tests for JSON serialization/deserialization helper functions."""

from aria.db.layer import _json_dumps_or_none, _json_loads_or


class TestJsonDumpsOrNone:
    """Test suite for _json_dumps_or_none function."""

    def test_dumps_none_input(self):
        """Test _json_dumps_or_none with None input."""
        result = _json_dumps_or_none(None)
        assert result is None


class TestJsonLoadsOr:
    """Test suite for _json_loads_or function."""

    def test_loads_none_input_with_list_default(self):
        """Test _json_loads_or with None input and list default."""
        result = _json_loads_or(None, default=[])
        assert result == []

    def test_loads_none_input_with_dict_default(self):
        """Test _json_loads_or with None input and dict default."""
        result = _json_loads_or(None, default={})
        assert result == {}

    def test_loads_valid_json_string_list(self):
        """Test _json_loads_or with valid JSON string (list)."""
        json_str = '["tag1", "tag2"]'
        result = _json_loads_or(json_str, default=[])
        assert result == ["tag1", "tag2"]

    def test_loads_valid_json_string_dict(self):
        """Test _json_loads_or with valid JSON string (dict)."""
        json_str = '{"key": "value", "number": 42}'
        result = _json_loads_or(json_str, default={})
        assert result == {"key": "value", "number": 42}

    def test_loads_invalid_json_string(self):
        """Test _json_loads_or with invalid JSON string."""
        result = _json_loads_or("not valid json", default=[])
        assert result == []

    def test_loads_invalid_json_returns_default_dict(self):
        """Test _json_loads_or with invalid JSON returns dict default."""
        result = _json_loads_or("not valid json", default={"error": True})
        assert result == {"error": True}

    def test_loads_already_deserialized_list(self):
        """Test _json_loads_or with already deserialized list."""
        data = ["tag1", "tag2"]
        result = _json_loads_or(data, default=[])
        assert result == data
        assert result is data  # Should return the same object

    def test_loads_already_deserialized_dict(self):
        """Test _json_loads_or with already deserialized dict."""
        data = {"key": "value"}
        result = _json_loads_or(data, default={})
        assert result == data
        assert result is data  # Should return the same object

    def test_loads_empty_string(self):
        """Test _json_loads_or with empty string."""
        result = _json_loads_or("", default=[])
        assert result == []

    def test_loads_whitespace_string(self):
        """Test _json_loads_or with whitespace string."""
        result = _json_loads_or("   ", default=[])
        assert result == []

    def test_loads_nested_json_structure(self):
        """Test _json_loads_or with nested JSON structure."""
        json_str = '{"level1": {"level2": {"level3": "value"}}}'
        result = _json_loads_or(json_str, default={})
        assert result == {"level1": {"level2": {"level3": "value"}}}

    def test_loads_json_with_unicode(self):
        """Test _json_loads_or with unicode characters in JSON."""
        json_str = '["日本語", "émoji", "🚀"]'
        result = _json_loads_or(json_str, default=[])
        assert result == ["日本語", "émoji", "🚀"]

    def test_loads_json_with_special_characters(self):
        """Test _json_loads_or with special characters in JSON."""
        json_str = '["quote\\"test", "newline\\ntest", "tab\\ttest"]'
        result = _json_loads_or(json_str, default=[])
        assert len(result) == 3
        assert '"' in result[0]
        assert "\n" in result[1]
        assert "\t" in result[2]

    def test_loads_json_array_with_mixed_types(self):
        """Test _json_loads_or with JSON array containing mixed types."""
        json_str = '[1, "string", true, null, {"key": "value"}]'
        result = _json_loads_or(json_str, default=[])
        assert result == [1, "string", True, None, {"key": "value"}]

    def test_loads_malformed_json_bracket(self):
        """Test _json_loads_or with malformed JSON (missing bracket)."""
        result = _json_loads_or('["tag1", "tag2"', default=[])
        assert result == []

    def test_loads_malformed_json_quote(self):
        """Test _json_loads_or with malformed JSON (missing quote)."""
        result = _json_loads_or('{"key: "value"}', default={})
        assert result == {}

    def test_loads_number_input(self):
        """Test _json_loads_or with number input (not a string)."""
        result = _json_loads_or(42, default=0)
        assert result == 42

    def test_loads_boolean_input(self):
        """Test _json_loads_or with boolean input (not a string)."""
        result = _json_loads_or(True, default=False)
        assert result is True
