"""
Tests for files/_internals.py module.

This module tests internal helper functions for file operations.
"""

import json
import stat
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from aria.tools.files._internals import (
    _create_backup,
    _error_response,
    _secure_resolve_dir,
    _secure_resolve_path,
    _validate_inputs,
    validate_and_resolve_two_files,
)
from aria.tools.files.exceptions import FileOperationError, FileSecurityError
from aria.tools.files.unified_read import (
    _build_directory_tree,
    _count_lines_efficiently,
    _count_tree_items,
    _format_permissions_symbolic,
    _read_lines_streaming,
)
from aria.tools.files.write_operations import (
    _atomic_write,
    _modify_lines_streaming,
)


class TestErrorResponse:
    """Test suite for _error_response function."""

    def test_security_error_response(self):
        """Test error response for FileSecurityError."""
        exc = FileSecurityError("Path traversal detected")
        result = _error_response("read", "test.txt", exc)
        data = json.loads(result)
        assert data["status"] == "error"
        assert data["tool"] == "read"
        assert "security" in data["error"]["message"].lower()

    def test_file_operation_error_response(self):
        """Test error response for FileOperationError."""
        exc = FileOperationError("File not found")
        result = _error_response("write", "test.txt", exc)
        data = json.loads(result)
        assert data["status"] == "error"
        assert "operation failed" in data["error"]["message"].lower()

    def test_os_error_response(self):
        """Test error response for OSError."""
        exc = OSError("Disk full")
        result = _error_response("write", "test.txt", exc)
        data = json.loads(result)
        assert data["status"] == "error"
        assert "access denied" in data["error"]["message"].lower()

    def test_permission_error_response(self):
        """Test error response for PermissionError."""
        exc = PermissionError("Access denied")
        result = _error_response("read", "test.txt", exc)
        data = json.loads(result)
        assert data["status"] == "error"
        assert "access denied" in data["error"]["message"].lower()

    def test_unexpected_error_response(self):
        """Test error response for unexpected exceptions."""
        exc = ValueError("Unexpected error")
        result = _error_response("read", "test.txt", exc)
        data = json.loads(result)
        assert data["status"] == "error"
        assert "unexpected" in data["error"]["message"].lower()


class TestValidateInputs:
    """Test suite for _validate_inputs function."""

    def test_valid_inputs(self):
        """Test validation with valid inputs."""
        # Should not raise
        _validate_inputs("test.txt", chunk_size=1024, offset=0, length=100)

    def test_empty_filename(self):
        """Test validation with empty filename."""
        with pytest.raises(FileSecurityError, match="Invalid file name"):
            _validate_inputs("")

    def test_non_string_filename(self):
        """Test validation with non-string filename."""
        with pytest.raises(FileSecurityError, match="Invalid file name"):
            _validate_inputs(123)  # type: ignore[arg-type]

    def test_path_traversal_attempt(self):
        """Test validation detects path traversal."""
        with pytest.raises(FileSecurityError, match="Path traversal"):
            _validate_inputs("../etc/passwd")

    def test_blocked_patterns(self):
        """Test validation detects blocked patterns."""
        with pytest.raises(FileSecurityError, match="blocked patterns"):
            _validate_inputs("test~file.txt")  # ~ is a blocked pattern

    def test_chunk_size_too_large(self):
        """Test validation with chunk size exceeding limit."""
        with pytest.raises(FileSecurityError, match="chunk_size"):
            _validate_inputs("test.txt", chunk_size=100_000_000)

    def test_negative_offset(self):
        """Test validation with negative offset."""
        with pytest.raises(FileSecurityError, match="Negative"):
            _validate_inputs("test.txt", offset=-1)

    def test_negative_length(self):
        """Test validation with negative length."""
        with pytest.raises(FileSecurityError, match="Negative"):
            _validate_inputs("test.txt", length=-1)

    def test_content_size_exceeds_limit(self):
        """Test validation with content exceeding size limit."""
        # MAX_FILE_SIZE is 100MB = 100 * 1024 * 1024
        large_content = "x" * (100 * 1024 * 1024 + 1)
        with pytest.raises(FileSecurityError, match="Content size.*exceeds"):
            _validate_inputs("test.txt", contents=large_content)

    def test_line_length_exceeds_limit(self):
        """Test validation with line exceeding length limit."""
        long_line = "x" * (100_000 + 1)  # Exceeds MAX_LINE_LENGTH
        with pytest.raises(FileSecurityError, match="Line length.*exceeds"):
            _validate_inputs("test.txt", new_lines=[long_line])


class TestCountLinesEfficiently:
    """Test suite for _count_lines_efficiently function."""

    def test_count_lines_in_file(self):
        """Test counting lines in a file."""
        with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
            f.write("line1\nline2\nline3\n")
            temp_path = Path(f.name)

        try:
            count = _count_lines_efficiently(temp_path)
            assert count == 3
        finally:
            temp_path.unlink()

    def test_count_lines_os_error(self):
        """Test error handling when file cannot be read."""
        with pytest.raises(FileOperationError, match="Failed to read"):
            _count_lines_efficiently(Path("/nonexistent/file.txt"))


class TestSecureResolvePath:
    """Test suite for _secure_resolve_path function."""

    @staticmethod
    def _workspace():
        """Get the current (possibly monkeypatched) workspace path."""
        from aria.tools.constants import BASE_DIR

        return BASE_DIR

    def test_resolve_existing_file(self):
        """Test resolving path to existing file."""
        # Create file within BASE_DIR
        temp_path = self._workspace() / f"test_resolve_{id(self)}.txt"
        temp_path.write_text("test")

        try:
            # Test with absolute path
            result = _secure_resolve_path(str(temp_path), check_exists=False)
            assert result.exists()
        finally:
            temp_path.unlink()

    def test_resolve_path_traversal(self):
        """Test path traversal behavior with enforce_base_dir flag."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            # Create a file outside tmpdir that we try to access
            outside_file = tmpdir_path / "outside.txt"
            outside_file.write_text("content")

            # With enforce_base_dir=False, path should be allowed
            result = _secure_resolve_path(str(outside_file), enforce_base_dir=False)
            assert result == outside_file.resolve()

            # With enforce_base_dir=True, path should be blocked
            with pytest.raises(FileSecurityError, match="Path traversal"):
                _secure_resolve_path(str(outside_file), enforce_base_dir=True)

    def test_resolve_symlink(self):
        """Test that symlinks are detected (resolve follows them)."""
        ws = self._workspace()
        target = ws / f"test_target_{id(self)}.txt"
        target.write_text("content")
        link = ws / f"test_link_{id(self)}.txt"
        link.symlink_to(target)

        try:
            # Test with absolute path - symlink should be blocked
            with pytest.raises(FileSecurityError, match="Symlinks"):
                _secure_resolve_path(str(link))
        finally:
            link.unlink()
            target.unlink()

    def test_resolve_disallowed_extension(self):
        """Test that disallowed file extensions are blocked."""
        file_path = self._workspace() / f"test_{id(self)}.exe"
        file_path.write_text("content")

        try:
            # Test with absolute path - extension should be blocked
            with pytest.raises(FileSecurityError, match="File type not"):
                _secure_resolve_path(str(file_path))
        finally:
            file_path.unlink()

    def test_resolve_nonexistent_file_check_exists_true(self):
        """Test error when file doesn't exist and check_exists=True."""
        file_path = self._workspace() / f"nonexistent_{id(self)}.txt"
        # Test with absolute path
        with pytest.raises(FileOperationError, match="File not found"):
            _secure_resolve_path(str(file_path), check_exists=True)

    def test_resolve_nonexistent_file_check_exists_false(self):
        """Test resolving nonexistent file with check_exists=False."""
        file_path = self._workspace() / f"nonexistent_{id(self)}.txt"
        # Should not raise with check_exists=False
        result = _secure_resolve_path(str(file_path), check_exists=False)
        assert isinstance(result, Path)


class TestSecureResolveDir:
    """Test suite for _secure_resolve_dir function."""

    def test_resolve_directory(self):
        """Test resolving directory path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            subdir = tmpdir_path / "subdir"
            subdir.mkdir()

            # With enforce_base_dir=False, absolute paths work anywhere
            result = _secure_resolve_dir(str(subdir), enforce_base_dir=False)
            assert result.is_dir()

    def test_resolve_dir_path_traversal(self):
        """Test path traversal behavior with enforce_base_dir flag."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            # Create a directory outside current BASE_DIR
            outside_dir = tmpdir_path / "outside"
            outside_dir.mkdir()

            # With enforce_base_dir=False, absolute paths work anywhere
            result = _secure_resolve_dir(str(outside_dir), enforce_base_dir=False)
            assert result.is_dir()

            # With enforce_base_dir=True, path outside BASE_DIR
            # should be blocked
            with pytest.raises(FileSecurityError, match="Path traversal"):
                _secure_resolve_dir(str(outside_dir), enforce_base_dir=True)

    def test_resolve_dir_symlink(self):
        """Test that symlinked directories are blocked."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            target_dir = tmpdir_path / "target"
            target_dir.mkdir()
            link_dir = tmpdir_path / "link"
            link_dir.symlink_to(target_dir)

            # Symlinks are blocked
            with pytest.raises(FileSecurityError, match="Symlinks"):
                _secure_resolve_dir(str(link_dir))


class TestReadLinesStreaming:
    """Test suite for _read_lines_streaming function."""

    def test_read_all_lines(self):
        """Test reading all lines from file."""
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt") as f:
            f.write("line1\nline2\nline3\n")
            temp_path = Path(f.name)

        try:
            lines = _read_lines_streaming(temp_path, offset=0, length=0)
            assert lines == ["line1", "line2", "line3"]
        finally:
            temp_path.unlink()

    def test_read_lines_with_offset(self):
        """Test reading lines with offset."""
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt") as f:
            f.write("line1\nline2\nline3\n")
            temp_path = Path(f.name)

        try:
            lines = _read_lines_streaming(temp_path, offset=1, length=0)
            assert lines == ["line2", "line3"]
        finally:
            temp_path.unlink()

    def test_read_lines_with_length(self):
        """Test reading specific number of lines."""
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt") as f:
            f.write("line1\nline2\nline3\n")
            temp_path = Path(f.name)

        try:
            lines = _read_lines_streaming(temp_path, offset=0, length=2)
            assert lines == ["line1", "line2"]
        finally:
            temp_path.unlink()

    def test_read_lines_os_error(self):
        """Test error handling when file cannot be read."""
        with pytest.raises(FileOperationError, match="Failed to read"):
            _read_lines_streaming(Path("/nonexistent.txt"), 0, 0)


class TestModifyLinesStreaming:
    """Test suite for _modify_lines_streaming function."""

    def test_replace_lines(self):
        """Test replacing lines in file."""
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt") as f:
            f.write("line1\nline2\nline3\n")
            temp_path = Path(f.name)

        try:
            old_total, new_total = _modify_lines_streaming(
                temp_path, offset=1, length=1, new_lines=["replaced"]
            )
            assert old_total == 3
            assert new_total == 3
            content = temp_path.read_text()
            assert "replaced" in content
        finally:
            temp_path.unlink()

    def test_insert_lines(self):
        """Test inserting lines in file."""
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt") as f:
            f.write("line1\nline2\n")
            temp_path = Path(f.name)

        try:
            old_total, new_total = _modify_lines_streaming(
                temp_path, offset=1, length=0, new_lines=["inserted"]
            )
            assert new_total == old_total + 1
        finally:
            temp_path.unlink()

    def test_delete_lines(self):
        """Test deleting lines from file."""
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt") as f:
            f.write("line1\nline2\nline3\n")
            temp_path = Path(f.name)

        try:
            old_total, new_total = _modify_lines_streaming(
                temp_path, offset=1, length=1, new_lines=None
            )
            assert new_total == old_total - 1
        finally:
            temp_path.unlink()

    def test_append_lines_beyond_end(self):
        """Test appending lines beyond end of file."""
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt") as f:
            f.write("line1\nline2\n")
            temp_path = Path(f.name)

        try:
            old_total, new_total = _modify_lines_streaming(
                temp_path, offset=10, length=0, new_lines=["appended"]
            )
            assert new_total > old_total
        finally:
            temp_path.unlink()

    def test_modify_lines_error_cleanup(self):
        """Test that temp file is cleaned up on error."""
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt") as f:
            temp_path = Path(f.name)

        temp_path.unlink()  # Delete file to cause error

        with pytest.raises(FileOperationError, match="Failed to modify"):
            _modify_lines_streaming(temp_path, offset=0, length=1, new_lines=["test"])


class TestAtomicWrite:
    """Test suite for _atomic_write function."""

    def test_atomic_write_success(self):
        """Test successful atomic write."""
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt") as f:
            temp_path = Path(f.name)

        try:
            _atomic_write(temp_path, "test content")
            assert temp_path.read_text() == "test content"
        finally:
            temp_path.unlink()

    def test_atomic_write_error_cleanup(self):
        """Test that temp file is cleaned up on error."""
        invalid_path = Path("/invalid/path/file.txt")
        with pytest.raises(FileOperationError, match="Failed to write"):
            _atomic_write(invalid_path, "content")


class TestCreateBackup:
    """Test suite for _create_backup function."""

    def test_create_backup_success(self):
        """Test successful backup creation."""
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt") as f:
            f.write("original content")
            temp_path = Path(f.name)

        try:
            backup_path = _create_backup(temp_path)
            assert backup_path is not None
            assert backup_path.exists()
            assert backup_path.read_text() == "original content"
            backup_path.unlink()
        finally:
            temp_path.unlink()

    def test_create_backup_nonexistent_file(self):
        """Test backup of nonexistent file returns None."""
        result = _create_backup(Path("/nonexistent/file.txt"))
        assert result is None

    def test_create_backup_error(self):
        """Test backup creation error handling."""
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt") as f:
            temp_path = Path(f.name)

        try:
            # Mock shutil.copy2 to raise an exception
            with patch("aria.tools.files._internals.shutil.copy2") as mock:
                mock.side_effect = PermissionError("Access denied")
                result = _create_backup(temp_path)
                assert result is None  # Should return None on error
        finally:
            temp_path.unlink()


class TestBuildDirectoryTree:
    """Test suite for _build_directory_tree function."""

    def test_build_tree_simple(self):
        """Test building directory tree."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            (tmpdir_path / "file1.txt").write_text("content")
            (tmpdir_path / "file2.txt").write_text("content")

            tree = _build_directory_tree(tmpdir_path, 0, 2)
            assert tree["type"] == "directory"
            assert len(tree["children"]) == 2

    def test_build_tree_with_subdirs(self):
        """Test building tree with subdirectories."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            subdir = tmpdir_path / "subdir"
            subdir.mkdir()
            (subdir / "file.txt").write_text("content")

            tree = _build_directory_tree(tmpdir_path, 0, 2)
            assert any(child["type"] == "directory" for child in tree["children"])

    def test_build_tree_max_depth(self):
        """Test that max depth is respected."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            subdir = tmpdir_path / "subdir"
            subdir.mkdir()

            tree = _build_directory_tree(tmpdir_path, 0, 0)
            assert tree["type"] == "directory"
            assert tree["truncated"] is True

    def test_build_tree_permission_error(self):
        """Test handling of permission errors."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)

            # Mock iterdir to raise PermissionError
            with patch.object(Path, "iterdir") as mock_iterdir:
                mock_iterdir.side_effect = PermissionError("Access denied")
                tree = _build_directory_tree(tmpdir_path, 0, 2)
                assert tree["type"] == "directory"
                assert tree["error"] == "Permission denied"


class TestCountTreeItems:
    """Test suite for _count_tree_items function."""

    def test_count_files_and_dirs(self):
        """Test counting files and directories in tree."""
        tree = {
            "type": "directory",
            "children": [
                {"name": "file1.txt", "type": "file"},
                {"name": "file2.txt", "type": "file"},
                {
                    "name": "subdir",
                    "type": "directory",
                    "children": [{"name": "file3.txt", "type": "file"}],
                },
            ],
        }
        files, dirs = _count_tree_items(tree)
        assert files == 3
        assert dirs == 2  # root dir + subdir


class TestFormatPermissionsSymbolic:
    """Test suite for _format_permissions_symbolic function."""

    def test_format_permissions_rwx(self):
        """Test formatting full permissions."""
        mode = stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR
        mode |= stat.S_IRGRP | stat.S_IWGRP | stat.S_IXGRP
        mode |= stat.S_IROTH | stat.S_IWOTH | stat.S_IXOTH
        result = _format_permissions_symbolic(mode)
        assert result == "rwxrwxrwx"

    def test_format_permissions_readonly(self):
        """Test formatting read-only permissions."""
        mode = stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH
        result = _format_permissions_symbolic(mode)
        assert result == "r--r--r--"

    def test_format_permissions_mixed(self):
        """Test formatting mixed permissions."""
        mode = stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP
        result = _format_permissions_symbolic(mode)
        assert result == "rw-r-----"


class TestValidateAndResolveTwoFiles:
    """Test suite for validate_and_resolve_two_files function."""

    @staticmethod
    def _workspace():
        from aria.tools.constants import BASE_DIR

        return BASE_DIR

    def test_validate_two_files_success(self):
        """Test successful validation of two files."""
        ws = self._workspace()
        source = ws / f"test_source_{id(self)}.txt"
        source.write_text("content")
        dest = ws / f"test_dest_{id(self)}.txt"

        try:
            src_path, dest_path = validate_and_resolve_two_files(
                str(source), str(dest), dest_must_exist=False
            )
            assert src_path.exists()
        finally:
            source.unlink(missing_ok=True)
            dest.unlink(missing_ok=True)

    def test_validate_two_files_invalid_source(self):
        """Test validation with invalid source."""
        dest = self._workspace() / f"test_dest_{id(self)}.txt"
        # Path traversal attempt - should be blocked
        with pytest.raises(FileSecurityError, match="Path traversal"):
            validate_and_resolve_two_files("../etc/passwd", str(dest))

    def test_validate_two_files_invalid_dest(self):
        """Test validation with invalid destination."""
        source = self._workspace() / f"test_source_{id(self)}.txt"
        source.write_text("content")
        # Path traversal attempt - should be blocked
        with pytest.raises(FileSecurityError, match="Path traversal"):
            validate_and_resolve_two_files(str(source), "../etc/passwd")
        source.unlink()
