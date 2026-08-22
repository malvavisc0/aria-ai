"""Tests for the extras CLI module."""

from aria.cli.extras import (
    _EXCLUDED_BINARIES,
    get_venv_extras,
    get_venv_extras_json,
)


class TestGetVenvExtras:
    """Tests for get_venv_extras()."""

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


class TestGetVenvExtrasJson:
    """Tests for get_venv_extras_json()."""

    def test_returns_dict(self):
        """Should return a dict with expected keys."""
        result = get_venv_extras_json()
        assert isinstance(result, dict)
        assert "categories" in result
        assert "uncategorized" in result
        assert "total" in result

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
