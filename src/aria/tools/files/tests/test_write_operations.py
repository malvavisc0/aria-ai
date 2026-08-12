import json
import shutil
import tempfile
from pathlib import Path

from aria.tools.files import edit_file, write_file


class TestWriteOperations:
    """Test suite for unified write and edit file operations."""

    def setup_method(self):
        self.test_dir = tempfile.mkdtemp()
        self.base_dir = Path(self.test_dir)

        import aria.tools.files._internals as internals_module

        internals_module.BASE_DIR = self.base_dir

        test_file = self.base_dir / "test.txt"
        test_file.write_text("Line 1\nLine 2\nLine 3\nLine 4\nLine 5\n")

    def teardown_method(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    # --- write_file: overwrite mode ---

    def test_write_file_overwrite_new(self):
        result = write_file(
            "Testing file write",
            str(self.base_dir / "new_file.txt"),
            "New content\nSecond line\n",
        )
        data = json.loads(result)

        assert data["tool"] == "write_file"
        assert data["data"]["file_name"] == str(self.base_dir / "new_file.txt")
        assert data["data"]["mode"] == "overwrite"
        assert data["data"]["bytes_written"] == 24
        assert data["data"]["lines_written"] == 2
        assert data["data"]["created"] is True
        assert data["data"]["backup_created"] is False

        new_file = self.base_dir / "new_file.txt"
        assert new_file.exists()
        assert new_file.read_text() == "New content\nSecond line\n"

    def test_write_file_overwrite_existing_creates_backup(self):
        (self.base_dir / "existing.txt").write_text("Original content\n")

        result = write_file(
            "Testing file overwrite",
            str(self.base_dir / "existing.txt"),
            "New content\n",
        )
        data = json.loads(result)

        assert data["tool"] == "write_file"
        assert data["data"]["mode"] == "overwrite"
        assert data["data"]["backup_created"] is True
        assert data["data"]["created"] is False

    def test_write_file_auto_creates_parent_dirs(self):
        result = write_file(
            "Testing auto dir creation",
            str(self.base_dir / "new_dir" / "subdir" / "file.txt"),
            "content\n",
        )
        data = json.loads(result)

        assert data["data"]["created"] is True
        assert (self.base_dir / "new_dir" / "subdir" / "file.txt").exists()

    def test_write_file_empty_content(self):
        result = write_file(
            "Testing empty file",
            str(self.base_dir / "empty.txt"),
            "",
        )
        data = json.loads(result)
        assert data["data"]["lines_written"] == 0
        assert data["data"]["bytes_written"] == 0

    def test_write_file_single_line_no_newline(self):
        content = "Single line content"
        result = write_file(
            "Testing single line",
            str(self.base_dir / "single.txt"),
            content,
        )
        data = json.loads(result)
        assert data["data"]["lines_written"] == 1
        assert data["data"]["bytes_written"] == len(content.encode("utf-8"))

    def test_write_file_single_line_with_newline(self):
        content = "Single line content\n"
        result = write_file(
            "Testing single line with newline",
            str(self.base_dir / "single_newline.txt"),
            content,
        )
        data = json.loads(result)
        assert data["data"]["lines_written"] == 1

    def test_write_file_multiple_lines_no_trailing_newline(self):
        content = "Line 1\nLine 2\nLine 3"
        result = write_file(
            "Testing multiple lines",
            str(self.base_dir / "multi.txt"),
            content,
        )
        data = json.loads(result)
        assert data["data"]["lines_written"] == 3
        assert data["data"]["bytes_written"] == len(content.encode("utf-8"))

    def test_write_file_utf8_bytes(self):
        content = "Hello 你好 🌍\n"
        result = write_file(
            "Testing UTF-8",
            str(self.base_dir / "utf8.txt"),
            content,
        )
        data = json.loads(result)
        assert data["data"]["bytes_written"] == len(content.encode("utf-8"))
        assert data["data"]["lines_written"] == 1

    def test_write_file_exceeds_size_limit(self):
        large_content = "A" * (100 * 1024 * 1024 + 1)

        result = write_file(
            "Testing size limit",
            str(self.base_dir / "large.txt"),
            large_content,
        )
        data = json.loads(result)

        assert data["status"] == "error"
        assert "exceed" in data["error"]["message"].lower()

    def test_write_file_invalid_path(self):
        result = write_file("Testing invalid path", "../outside.txt", "test")
        assert json.loads(result)["status"] == "error"

    # --- write_file: append mode ---

    def test_write_file_append(self):
        result = write_file(
            "Testing append",
            str(self.base_dir / "test.txt"),
            "New line\n",
            mode="append",
        )
        data = json.loads(result)

        assert data["tool"] == "write_file"
        assert data["data"]["mode"] == "append"
        assert data["data"]["bytes_appended"] == 9
        assert data["data"]["new_total_lines"] == 6

    def test_write_file_append_invalid_path(self):
        result = write_file(
            "Testing invalid path",
            "../outside.txt",
            "test",
            mode="append",
        )
        assert json.loads(result)["status"] == "error"

    def test_write_file_invalid_mode(self):
        result = write_file(
            "Testing invalid mode",
            str(self.base_dir / "test.txt"),
            "content",
            mode="invalid",
        )
        assert json.loads(result)["status"] == "error"

    # --- edit_file: insert ---

    def test_edit_file_insert(self):
        result = edit_file(
            "Testing line insertion",
            str(self.base_dir / "test.txt"),
            offset=1,
            new_lines=["Inserted line"],
        )
        data = json.loads(result)

        assert data["tool"] == "edit_file"
        assert data["data"]["operation"] == "insert"
        assert data["data"]["lines_affected"] == 1
        assert data["data"]["offset"] == 1
        assert data["data"]["old_total_lines"] == 5
        assert data["data"]["new_total_lines"] == 6
        assert data["data"]["backup_created"] is True

    # --- edit_file: replace ---

    def test_edit_file_replace(self):
        result = edit_file(
            "Testing line replacement",
            str(self.base_dir / "test.txt"),
            offset=1,
            length=2,
            new_lines=["New line 1", "New line 2"],
        )
        data = json.loads(result)

        assert data["tool"] == "edit_file"
        assert data["data"]["operation"] == "replace"
        assert data["data"]["lines_affected"] == 2
        assert data["data"]["old_total_lines"] == 5
        assert data["data"]["new_total_lines"] == 5
        assert data["data"]["backup_created"] is True

    # --- edit_file: delete ---

    def test_edit_file_delete(self):
        result = edit_file(
            "Testing line deletion",
            str(self.base_dir / "test.txt"),
            offset=1,
            length=2,
        )
        data = json.loads(result)

        assert data["tool"] == "edit_file"
        assert data["data"]["operation"] == "delete"
        assert data["data"]["lines_affected"] == 2
        assert data["data"]["old_total_lines"] == 5
        assert data["data"]["new_total_lines"] == 3
        assert data["data"]["backup_created"] is True

    # --- edit_file: edge cases ---

    def test_edit_file_invalid_path(self):
        result = edit_file(
            "Testing invalid path",
            "../outside.txt",
            offset=0,
            length=1,
        )
        assert json.loads(result)["status"] == "error"

    def test_edit_file_invalid_params(self):
        """length=0 with new_lines=None is invalid."""
        result = edit_file(
            "Testing invalid params",
            str(self.base_dir / "test.txt"),
            offset=0,
        )
        assert json.loads(result)["status"] == "error"
