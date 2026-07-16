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
    """Test that CORE category loads only 4 tools."""

    def test_core_returns_4_tools(self):
        """CORE should load exactly 4 tools: reasoning, plan, scratchpad, shell."""
        tools = get_tools([CORE])
        names = {t.metadata.name for t in tools}
        assert len(tools) == 4
        assert names == {"reasoning", "plan", "scratchpad", "shell"}

    def test_core_does_not_include_web_search(self):
        """web_search should not be in CORE."""
        tools = get_tools([CORE])
        names = {t.metadata.name for t in tools}
        assert "web_search" not in names

    def test_core_does_not_include_download(self):
        """download should not be in CORE."""
        tools = get_tools([CORE])
        names = {t.metadata.name for t in tools}
        assert "download" not in names

    def test_core_does_not_include_weather(self):
        """get_current_weather should not be in CORE."""
        tools = get_tools([CORE])
        names = {t.metadata.name for t in tools}
        assert "get_current_weather" not in names

    def test_core_does_not_include_knowledge(self):
        """knowledge should not be in CORE."""
        tools = get_tools([CORE])
        names = {t.metadata.name for t in tools}
        assert "knowledge" not in names


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

    def test_files_does_not_include_delete_file(self):
        """delete_file should not be in FILES."""
        tools = get_tools([FILES])
        names = {t.metadata.name for t in tools}
        assert "delete_file" not in names

    def test_files_does_not_include_rename_file(self):
        """rename_file should not be in FILES."""
        tools = get_tools([FILES])
        names = {t.metadata.name for t in tools}
        assert "rename_file" not in names


class TestCorePlusFiles:
    """Test loading CORE + FILES together."""

    def test_core_plus_files_returns_11_tools(self):
        """CORE + FILES should load exactly 11 tools with no duplicates."""
        tools = get_tools([CORE, FILES])
        assert len(tools) == 11

    def test_no_duplicate_names(self):
        """Tool names should be unique when loading CORE + FILES."""
        tools = get_tools([CORE, FILES])
        names = [t.metadata.name for t in tools]
        assert len(names) == len(set(names))

    def test_combined_includes_all_core_and_file_tools(self):
        """Combined load should include all core and file tools."""
        tools = get_tools([CORE, FILES])
        names = {t.metadata.name for t in tools}
        assert "reasoning" in names
        assert "plan" in names
        assert "scratchpad" in names
        assert "shell" in names
        assert "read_file" in names
        assert "write_file" in names
        assert "edit_file" in names


class TestAllCategories:
    """Test that get_tools(None) still loads all categories."""

    def test_none_loads_all_categories(self):
        """get_tools(None) should load tools from all categories."""
        tools = get_tools(None)
        # Should have at least the 11 core+file tools
        assert len(tools) >= 11

    def test_all_categories_defined(self):
        """ALL_CATEGORIES should include all category names."""
        assert CORE in ALL_CATEGORIES
        assert FILES in ALL_CATEGORIES
