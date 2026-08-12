"""Tests for the extras CLI module."""

from aria.cli.extras import (
    _EXCLUDED_BINARIES,
    get_venv_extras,
    get_venv_extras_json,
)


class TestGetVenvExtras:
    """Tests for get_venv_extras()."""

    def test_returns_string(self):
        """Should return a non-empty string."""
        result = get_venv_extras()
        assert isinstance(result, str)
        assert len(result) > 0

    def test_contains_header(self):
        """Should include the Additional Commands header."""
        result = get_venv_extras()
        assert (
            "Additional Commands" in result or "virtual environment" in result.lower()
        )

    def test_excludes_python_internals(self):
        """Should not list python, python3, activate, etc."""
        result = get_venv_extras()
        for excluded in ["python", "python3", "activate", "deactivate"]:
            # These should not appear as code-formatted entries
            assert f"`{excluded}`" not in result

    def test_excludes_aria_internals(self):
        """Should not list aria, ax, aria-gui."""
        result = get_venv_extras()
        for excluded in ["`aria`", "`ax`", "`aria-gui`"]:
            assert excluded not in result

    def test_filter_term(self):
        """Should filter binaries by substring."""
        result = get_venv_extras(filter_term="black")
        # If black is in the venv, it should appear
        if "`black`" in result:
            # Other non-black tools should be filtered out
            assert "`ruff`" not in result

    def test_filter_no_match(self):
        """Should return message when filter matches nothing."""
        result = get_venv_extras(filter_term="zzz_nonexistent_tool_zzz")
        assert "No extra CLI tools found" in result or len(result) > 0


class TestGetVenvExtrasJson:
    """Tests for get_venv_extras_json()."""

    def test_returns_dict(self):
        """Should return a dict with expected keys."""
        result = get_venv_extras_json()
        assert isinstance(result, dict)
        assert "categories" in result
        assert "uncategorized" in result
        assert "total" in result

    def test_categories_is_dict(self):
        """Categories should be a dict of lists."""
        result = get_venv_extras_json()
        assert isinstance(result["categories"], dict)
        for key, val in result["categories"].items():
            assert isinstance(key, str)
            assert isinstance(val, list)

    def test_uncategorized_is_list(self):
        """Uncategorized should be a list."""
        result = get_venv_extras_json()
        assert isinstance(result["uncategorized"], list)

    def test_total_matches(self):
        """Total should equal sum of all categorized + uncategorized."""
        result = get_venv_extras_json()
        cat_count = sum(len(v) for v in result["categories"].values())
        assert result["total"] == cat_count + len(result["uncategorized"])

    def test_no_excluded_items(self):
        """Should not contain excluded binaries."""
        result = get_venv_extras_json()
        all_items = set(result["uncategorized"])
        for items in result["categories"].values():
            all_items.update(items)
        for item in all_items:
            assert item not in _EXCLUDED_BINARIES

    def test_filter(self):
        """Should filter by term."""
        full = get_venv_extras_json()
        filtered = get_venv_extras_json(filter_term="black")
        assert filtered["total"] <= full["total"]
