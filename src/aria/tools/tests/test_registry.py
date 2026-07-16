"""Tests for tool registry."""

from aria.tools.registry import (
    ALL_CATEGORIES,
    AX,
    CORE,
    FILES,
    get_tools,
)


class TestToolRegistry:
    """Test suite for tool registry."""

    def test_get_tools_specific_categories(self):
        """Test loading specific categories."""
        tools = get_tools([CORE])
        tool_names = {t.metadata.name for t in tools}
        assert "reasoning" in tool_names
        # File tools should NOT be in core-only
        assert "write_file" not in tool_names
        assert "read_file" not in tool_names

    def test_no_duplicate_tools_across_categories(self):
        """Test that loading multiple categories doesn't produce duplicates."""
        tools = get_tools([CORE, FILES])
        tool_names = [t.metadata.name for t in tools]
        assert len(tool_names) == len(set(tool_names)), (
            f"Duplicate tools found: "
            f"{[n for n in tool_names if tool_names.count(n) > 1]}"
        )

    def test_all_categories_defined(self):
        """Test that all expected categories are defined."""
        expected = {CORE, FILES, AX}
        assert set(ALL_CATEGORIES) == expected
