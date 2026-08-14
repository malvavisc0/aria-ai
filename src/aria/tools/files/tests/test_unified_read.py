"""Tests for unified file read operations."""

import json
import os
import tempfile
from pathlib import Path

import pytest

from aria.tools.files.unified_read import (
    ListFilesSchema,
    ReadFileSchema,
    SearchFilesSchema,
    file_info,
    list_files,
    read_file,
    search_files,
)


@pytest.fixture
def temp_dir():
    """Create a temporary directory for testing within the workspace."""
    from aria.tools.constants import BASE_DIR

    tmpdir = Path(tempfile.mkdtemp(dir=str(BASE_DIR)))
    old_cwd = os.getcwd()
    os.chdir(tmpdir)
    yield tmpdir
    os.chdir(old_cwd)


@pytest.fixture
def sample_files(temp_dir):
    """Create sample files for testing."""
    # Create some test files
    (temp_dir / "test1.txt").write_text("Line 1\nLine 2\nLine 3\nLine 4\nLine 5\n")
    (temp_dir / "test2.py").write_text("def hello():\n    print('hello')\n")
    (temp_dir / "subdir").mkdir()
    (temp_dir / "subdir" / "nested.txt").write_text("Nested content\n")

    return temp_dir


class TestReadFile:
    """Tests for read_file function."""

    def test_read_full_file(self, sample_files):
        """Test reading entire file."""
        result = read_file(
            reason="Testing full read",
            file_name=str(sample_files / "test1.txt"),
        )
        data = json.loads(result)

        assert data["status"] == "success"
        assert data["data"]["mode"] == "chunked"
        assert data["data"]["total_lines"] == 5
        assert "Line 1" in data["data"]["lines"][0]

    def test_read_file_chunk(self, sample_files):
        """Test reading file chunk."""
        result = read_file(
            reason="Testing chunk read",
            file_name=str(sample_files / "test1.txt"),
            offset=1,
            length=2,
        )
        data = json.loads(result)

        assert data["status"] == "success"
        assert data["data"]["mode"] == "chunked"
        assert data["data"]["offset"] == 1
        assert data["data"]["lines_returned"] == 2
        assert data["data"]["has_more"] is True
        assert data["data"]["lines"] == ["Line 2", "Line 3"]

    def test_read_file_caps_at_max_lines(self, sample_files):
        """Test that read_file caps lines instead of erroring."""
        result = read_file(
            reason="Testing max lines",
            file_name=str(sample_files / "test1.txt"),
            max_lines=3,
        )
        data = json.loads(result)

        assert data["status"] == "success"
        assert data["data"]["lines_returned"] <= 3
        assert data["data"]["has_more"] is True

    def test_read_nonexistent_file(self, temp_dir):
        """Test error for nonexistent file."""
        result = read_file(
            reason="Testing nonexistent",
            file_name=str(temp_dir / "nonexistent.txt"),
        )
        data = json.loads(result)

        assert data["status"] == "error"


class TestFileInfo:
    """Tests for file_info function."""

    def test_file_info_exists(self, sample_files):
        """Test getting info for existing file."""
        result = file_info(
            reason="Testing file info",
            file_name=str(sample_files / "test1.txt"),
        )
        data = json.loads(result)

        assert data["status"] == "success"
        assert data["data"]["exists"] is True
        assert data["data"]["is_file"] is True
        assert data["data"]["is_directory"] is False
        assert data["data"]["total_lines"] == 5
        assert "size_bytes" in data["data"]
        assert "permissions" in data["data"]

    def test_file_info_directory(self, sample_files):
        """Test getting info for directory."""
        result = file_info(
            reason="Testing directory info",
            file_name=str(sample_files / "subdir"),
        )
        data = json.loads(result)

        assert data["status"] == "success"
        assert data["data"]["exists"] is True
        assert data["data"]["is_file"] is False
        assert data["data"]["is_directory"] is True

    def test_file_info_nonexistent(self, temp_dir):
        """Test getting info for nonexistent file."""
        result = file_info(
            reason="Testing nonexistent",
            file_name=str(temp_dir / "nonexistent.txt"),
        )
        data = json.loads(result)

        assert data["status"] == "success"
        assert data["data"]["exists"] is False


class TestListFiles:
    """Tests for list_files function."""

    def test_list_files_flat(self, sample_files):
        """Test flat file listing."""
        result = list_files(
            reason="Testing flat list",
            pattern="*.txt",
            recursive=False,
            path=str(sample_files),
        )
        data = json.loads(result)

        assert data["status"] == "success"
        assert data["data"]["mode"] == "flat"
        assert data["data"]["count"] >= 1

    def test_list_files_recursive(self, sample_files):
        """Test recursive file listing."""
        result = list_files(
            reason="Testing recursive list",
            pattern="*.txt",
            recursive=True,
            path=str(sample_files),
        )
        data = json.loads(result)

        assert data["status"] == "success"
        # Should find both test1.txt and nested.txt
        assert data["data"]["count"] >= 2

    def test_list_files_tree(self, sample_files):
        """Test tree view."""
        result = list_files(
            reason="Testing tree view",
            recursive=True,
            max_depth=2,
            path=str(sample_files),
        )
        data = json.loads(result)

        assert data["status"] == "success"
        assert data["data"]["mode"] == "tree"
        assert "tree" in data["data"]
        assert data["data"]["total_files"] >= 2


class TestSearchFiles:
    """Tests for search_files function."""

    def test_search_by_name(self, sample_files):
        """Test searching by filename."""
        result = search_files(
            reason="Testing name search",
            pattern=r"\.txt$",
            mode="name",
            path=str(sample_files),
        )
        data = json.loads(result)

        assert data["status"] == "success"
        assert data["data"]["mode"] == "name"
        assert data["data"]["count"] >= 1

    def test_search_by_content(self, sample_files):
        """Test searching by content."""
        result = search_files(
            reason="Testing content search",
            pattern="Line 2",
            mode="content",
            path=str(sample_files),
        )
        data = json.loads(result)

        assert data["status"] == "success"
        assert data["data"]["mode"] == "content"
        assert data["data"]["total_matches"] >= 1
        assert len(data["data"]["matches"]) >= 1

    def test_search_invalid_mode(self, sample_files):
        """Test error for invalid mode."""
        result = search_files(
            reason="Testing invalid mode",
            pattern="test",
            mode="invalid",
            path=str(sample_files),
        )
        data = json.loads(result)

        assert data["status"] == "error"
        assert "Invalid mode" in data["error"]["message"]

    def test_search_invalid_regex(self, sample_files):
        """Test error for invalid regex."""
        result = search_files(
            reason="Testing invalid regex",
            pattern="[invalid(",
            mode="name",
            path=str(sample_files),
        )
        data = json.loads(result)

        assert data["status"] == "error"
        assert "Invalid regex" in data["error"]["message"]


class TestToolDocstrings:
    """Path parameters must tell the LLM that absolute paths are required.

    The requirement lives in the Pydantic ``Field`` descriptions (the LLM's
    parameter schema), not the function docstring."""

    def test_read_file_schema_promises_absolute_paths(self):
        desc = ReadFileSchema.model_fields["file_name"].description or ""
        assert "relative to BASE_DIR" not in desc
        assert "Absolute" in desc

    def test_list_files_schema_promises_absolute_paths(self):
        desc = ListFilesSchema.model_fields["path"].description or ""
        assert "relative to BASE_DIR" not in desc
        assert "Absolute" in desc

    def test_search_files_schema_promises_absolute_paths(self):
        desc = SearchFilesSchema.model_fields["path"].description or ""
        assert "relative to BASE_DIR" not in desc
        assert "Absolute" in desc
