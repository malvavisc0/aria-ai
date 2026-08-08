import json
import os
import shutil
import tempfile
from pathlib import Path

from aria.tools.development import python


class TestArgvHandling:
    """Test argv handling for the unified python tool."""

    def setup_method(self):
        self.test_dir = tempfile.mkdtemp()
        self.base_dir = Path(self.test_dir)
        self.original_cwd = os.getcwd()
        os.chdir(self.test_dir)

    def teardown_method(self):
        os.chdir(self.original_cwd)
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_argparse_with_default_argv(self):
        """
        Test that argparse works with default sys.argv.
        """
        code = """
import argparse
parser = argparse.ArgumentParser()
parser.add_argument('--name', default='World')
args = parser.parse_args()
print(f'Hello {args.name}')
"""
        result = python("Testing argparse", code=code)
        result_dict = json.loads(result)
        assert result_dict["data"]["result"]["success"] is True
        assert (
            "Hello World"
            in Path(result_dict["data"]["result"]["stdout_file"]).read_text()
        )

    def test_argparse_with_custom_argv(self):
        """
        Test that custom argv is properly passed to sys.argv.
        """
        code = """
import argparse
parser = argparse.ArgumentParser()
parser.add_argument('--name', default='World')
args = parser.parse_args()
print(f'Hello {args.name}')
"""
        result = python(
            "Testing argparse with custom argv",
            code=code,
            args=["script.py", "--name", "Custom"],
        )
        result_dict = json.loads(result)
        assert result_dict["data"]["result"]["success"] is True
        assert (
            "Hello Custom"
            in Path(result_dict["data"]["result"]["stdout_file"]).read_text()
        )

    def test_sys_exit_zero(self):
        """
        Test that sys.exit(0) is handled gracefully.
        """
        code = "import sys\nsys.exit(0)\n"
        result = python("Testing sys.exit(0)", code=code)
        result_dict = json.loads(result)
        assert result_dict["data"]["result"]["success"] is True

    def test_sys_exit_nonzero(self):
        """
        Test that sys.exit(1) is handled gracefully.
        """
        code = "import sys\nsys.exit(1)\n"
        result = python("Testing sys.exit(1)", code=code)
        result_dict = json.loads(result)
        assert result_dict["data"]["result"]["success"] is False
        assert result_dict["data"]["result"]["exit_code"] == 1

    def test_argv_isolation(self):
        """
        Test that argv is properly isolated between calls.
        """
        code = "import sys\nprint(' '.join(sys.argv))\n"
        result1 = python(
            "Testing argv isolation",
            code=code,
            args=["test.py", "arg1", "arg2"],
        )
        result_dict1 = json.loads(result1)
        assert (
            "arg1 arg2"
            in Path(result_dict1["data"]["result"]["stdout_file"]).read_text()
        )
