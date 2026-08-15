"""Tests for slimmed tool registry (CLI architecture changes).

Verifies that the tool registry loads the correct number of tools
after the CLI architecture refactoring removed domain tools from
the agent's direct toolset.
"""

from aria.tools.registry import (
    ALL_CATEGORIES,
    CORE,
    FILES,
    get_tools,
)


class TestSlimmedCoreTools:
    """Test that CORE category loads only execution tools."""

    def test_core_returns_3_tools(self):
        """CORE should load plan, scratchpad, and shell."""
        tools = get_tools([CORE])
        names = {t.metadata.name for t in tools}
        assert len(tools) == 3
        assert names == {"plan", "scratchpad", "shell"}


class TestSlimmedFileTools:
    """Test that FILES category loads only 7 tools."""

    def test_files_returns_7_tools(self):
        """FILES should load exactly 7 tools."""
        tools = get_tools([FILES])
        assert len(tools) == 7

    def test_files_includes_expected_tools(self):
        """FILES should include the expected file operation tools."""
        tools = get_tools([FILES])
        names = {t.metadata.name for t in tools}
        expected = {
            "read_file",
            "write_file",
            "edit_file",
            "file_info",
            "list_files",
            "search_files",
            "copy_file",
        }
        assert names == expected


class TestCorePlusFiles:
    """Test loading CORE + FILES together."""

    def test_core_plus_files_returns_10_tools(self):
        """CORE + FILES should load exactly 10 tools with no duplicates."""
        tools = get_tools([CORE, FILES])
        assert len(tools) == 10

    def test_no_duplicate_names(self):
        """Tool names should be unique when loading CORE + FILES."""
        tools = get_tools([CORE, FILES])
        names = [t.metadata.name for t in tools]
        assert len(names) == len(set(names))


class TestAllCategories:
    """Test that get_tools(None) still loads all categories."""

    def test_none_loads_all_categories(self):
        """get_tools(None) should load tools from all categories."""
        tools = get_tools(None)
        # Should have at least the 10 core+file tools
        assert len(tools) >= 10

    def test_all_categories_defined(self):
        """ALL_CATEGORIES should include all category names."""
        assert CORE in ALL_CATEGORIES
        assert FILES in ALL_CATEGORIES
