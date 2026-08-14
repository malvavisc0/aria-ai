import json
import shutil
import tempfile
from pathlib import Path

from aria.tools.files import copy_file


class TestFileManagement:
    """Test suite for file management operations."""

    def setup_method(self):
        self.test_dir = tempfile.mkdtemp()
        self.base_dir = Path(self.test_dir)

        import aria.tools.files._internals as internals_module

        internals_module.BASE_DIR = self.base_dir

        test_file = self.base_dir / "test.txt"
        test_file.write_text("Line 1\nLine 2\nLine 3\nLine 4\nLine 5\n")

    def teardown_method(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_copy_file(self):
        result = copy_file(
            "Testing copy",
            str(self.base_dir / "test.txt"),
            str(self.base_dir / "copied.txt"),
        )
        data = json.loads(result)

        assert data["tool"] == "copy_file"
        assert data["data"]["source"] == str(self.base_dir / "test.txt")
        assert data["data"]["destination"] == str(self.base_dir / "copied.txt")
