"""Behavioral contract tests for files module.

This module addresses issue #15 from the tools audit: tests should verify
actual behavior, not just export presence. These tests verify:
1. Functions return JSON as documented
2. Error responses have consistent structure
3. Path handling behavior matches documentation

Run with: pytest src/aria/tools/files/tests/test_behavioral_contract.py -v
"""

import inspect
import json
import shutil
import tempfile
from pathlib import Path

from aria.tools.files import edit_file, read_file, unified_read, write_file


class TestFilesReturnJsonContract:
    """Verify file operations return JSON responses."""

    def setup_method(self):
        self.test_dir = tempfile.mkdtemp()
        self.base_dir = Path(self.test_dir)
        import aria.tools.files._internals as internals_module

        internals_module.BASE_DIR = self.base_dir

    def teardown_method(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_write_file_returns_json(self):
        """write_file should return valid JSON with documented fields."""
        result = write_file(
            "Testing",
            str(self.base_dir / "test.txt"),
            "content",
        )
        data = json.loads(result)
        # Verify required fields in actual format
        assert "status" in data
        assert "data" in data
        assert data["status"] == "success"

    def test_write_file_append_returns_json(self):
        """write_file append should return valid JSON response."""
        test_file = self.base_dir / "append_test.txt"
        test_file.write_text("initial\n")

        result = write_file(
            "Testing",
            str(self.base_dir / "append_test.txt"),
            "added\n",
            mode="append",
        )
        data = json.loads(result)
        assert "status" in data
        assert "data" in data
        assert data["data"]["mode"] == "append"

    def test_read_file_returns_json(self):
        """read_file should return valid JSON response."""
        test_file = self.base_dir / "read_test.txt"
        test_file.write_text("test content\n")

        result = read_file(
            "Testing",
            str(self.base_dir / "read_test.txt"),
        )
        data = json.loads(result)
        # Standard envelope: {status, tool, reason, timestamp, data}
        assert "tool" in data
        assert "data" in data
        assert data["status"] == "success"

    def test_edit_file_returns_json(self):
        """edit_file should return valid JSON response."""
        test_file = self.base_dir / "edit_test.txt"
        test_file.write_text("line1\nline2\nline3\n")

        result = edit_file(
            "Testing",
            str(self.base_dir / "edit_test.txt"),
            offset=1,
            length=1,
            new_lines=["replaced"],
        )
        data = json.loads(result)
        assert "status" in data
        assert "data" in data
        assert data["data"]["operation"] == "replace"


class TestFilesErrorResponseContract:
    """Verify error responses have consistent structure."""

    def setup_method(self):
        self.test_dir = tempfile.mkdtemp()
        self.base_dir = Path(self.test_dir)
        import aria.tools.files._internals as internals_module

        internals_module.BASE_DIR = self.base_dir

    def teardown_method(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_invalid_path_returns_error_status(self):
        """Invalid paths should return error status."""
        result = write_file(
            "Testing",
            "/etc/passwd",
            "malicious",
        )
        data = json.loads(result)
        assert data["status"] == "error"
        assert "error" in data
        assert "message" in data["error"]

    def test_nonexistent_file_read_returns_error(self):
        """Reading nonexistent file should return error status."""
        result = read_file(
            "Testing",
            str(self.base_dir / "nonexistent.txt"),
        )
        data = json.loads(result)
        # Standard error envelope: {status, tool, reason, timestamp, error}
        assert data["status"] == "error"
        assert data["error"]["message"] != ""


class TestListFilesParameterNaming:
    """Issue #1: Verify list_files has correct parameter naming.

    The audit found that inventory documented 'dir_name' but implementation
    uses 'pattern', 'recursive', 'max_results'.
    """

    def test_list_files_has_pattern_parameter(self):
        """list_files should have 'pattern' parameter."""
        sig = inspect.signature(unified_read.list_files)
        params = list(sig.parameters.keys())
        assert "pattern" in params, (
            f"list_files should have 'pattern' parameter, got {params}"
        )

    def test_list_files_has_recursive_parameter(self):
        """list_files should have 'recursive' parameter."""
        sig = inspect.signature(unified_read.list_files)
        params = list(sig.parameters.keys())
        assert "recursive" in params

    def test_list_files_has_max_results_parameter(self):
        """list_files should have 'max_results' parameter."""
        sig = inspect.signature(unified_read.list_files)
        params = list(sig.parameters.keys())
        assert "max_results" in params


class TestReadFileParameterNaming:
    """Verify read_file uses correct parameter names."""

    def test_read_file_has_reason_parameter(self):
        """read_file should have 'reason' parameter."""
        sig = inspect.signature(unified_read.read_file)
        params = list(sig.parameters.keys())
        assert "reason" in params

    def test_read_file_has_file_name_parameter(self):
        """read_file should have 'file_name' parameter."""
        sig = inspect.signature(unified_read.read_file)
        params = list(sig.parameters.keys())
        assert "file_name" in params


class TestSearchFilesContract:
    """Verify search_files parameter naming."""

    def test_search_files_has_pattern_parameter(self):
        """search_files should have 'pattern' parameter."""
        sig = inspect.signature(unified_read.search_files)
        params = list(sig.parameters.keys())
        assert "pattern" in params, f"search_files should have 'pattern', got {params}"

    def test_search_files_has_mode_parameter(self):
        """search_files should have 'mode' parameter."""
        sig = inspect.signature(unified_read.search_files)
        params = list(sig.parameters.keys())
        assert "mode" in params
